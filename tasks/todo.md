# Todo: recover stuck/orphaned processing jobs

Branch `fix/stale-processing-jobs` off `main`, independent of `fix/auto-migrate-on-startup`
(that branch's work is stashed on its own branch, untouched by this one).

## Problem

Reported: batch `7af8bba1` has sat at "Processing", 0/6, since 2026-09-09 with no way to act
on it. Confirmed in the dev DB: all 6 `statement_job` rows are `PROCESSING`, `attempt_count: 0`,
`updated_at` staggered ~1.7s apart (consistent with the backend being restarted/crashing
repeatedly, each restart claiming the next queued job before dying again) — none ever reached a
terminal status.

**Root cause:** `CLAIMABLE_JOB_STATUSES = ("QUEUED", "RETRYING")` (`models/jobs.py:31`) does not
include `PROCESSING`. If the backend process dies or restarts while a job is claimed (crash, a
hung OCR call in the single-threaded worker — `services/extraction.py` has no timeout around
`pdfplumber`/`poppler`/`tesseract`), that job is permanently excluded from being claimed again.
`refresh_batch` never sees all-terminal, so the batch stays `PROCESSING` forever. There is also
no API to inspect or act on this — `api/batches.py` has no retry/cancel endpoint.

**Out of scope (documented, not built):** a hard timeout around OCR extraction. Doing that
properly needs process isolation, which conflicts with the existing intentional single-thread
design in `pool.py` (see its module docstring) — bigger change than this bug needs today.

## Design (owner-approved: startup recovery + a manual retry endpoint)

Shared helper `reclaim_processing_jobs(session, *, batch_id=None, min_age_seconds=None)` in
`app/workers/queue.py`:
- Selects `PROCESSING` jobs (optionally scoped to one batch, optionally only those whose
  `updated_at` is older than `min_age_seconds`).
- For each: `attempt_count += 1`; status -> `RETRYING` if `attempt_count < max_attempts` else
  `FAILED`; `failure_reason` records that it was interrupted, not why the job itself failed.
- Returns the count reclaimed. Caller commits and calls `refresh_batch` for affected batch ids
  (a job reclaimed straight to `FAILED` can make the batch newly terminal).

Two callers:
1. **Startup recovery** — `main.py` lifespan, before `worker.start()`. No worker is running yet,
   so every `PROCESSING` row is guaranteed orphaned: `reclaim_processing_jobs(session)`, no age
   filter, all batches.
2. **Manual retry** — `POST /batches/{batch_id}/retry`. The worker *may* be actively running here,
   so only reclaim jobs stale for >= 60s (`min_age_seconds=60`) to avoid racing a job that is
   legitimately mid-flight. If the batch isn't `PROCESSING`, or nothing was stale enough to
   reclaim, return 409 with a clear reason. On success, return the reclaimed count and refreshed
   batch status.

## Tasks

- [x] C1. `reclaim_processing_jobs()` in `app/workers/queue.py`.
- [x] C2. Wire startup recovery into `main.py` lifespan, before `worker.start()`.
- [x] C3. `POST /batches/{batch_id}/retry` in `api/batches.py` (404 unknown batch, 409 nothing
      stale/not PROCESSING, 200 with reclaimed count + batch status on success).
- [x] C4. Tests (`test_job_queue.py` / `test_batches_api.py` / `test_main.py`):
  - fresh restart with orphaned `PROCESSING` rows -> all reclaimed regardless of age
  - a job already at `max_attempts` -> reclaimed straight to `FAILED`, batch re-evaluated
  - retry endpoint: stale (>60s) `PROCESSING` job -> reclaimed, 200
  - retry endpoint: recent (<60s) `PROCESSING` job -> left alone, 409
  - retry endpoint: batch not in `PROCESSING` -> 409
  - retry endpoint: unknown batch id -> 404
  - lifespan wiring test (`get_session` + worker stubbed, never touches the real DB/thread)
- [x] C5. Docs: `docs/activity.md` entry; noted the OCR-timeout follow-up as a known limitation
      (not building it now).
- [x] C6. Unblock batch `7af8bba1` for real — verified against a **copy** of the real dev DB
      (`apps/backend/data/app.db`, copied to scratch, never mutated): all 6 jobs reclaimed on
      startup, reprocessed by the real worker against the real source PDFs (still on disk),
      batch ended `COMPLETED`, 6/6 processed, 0 failed. Scratch copy deleted after verification.
      The real `app.db` itself is untouched — merging this branch and restarting the real
      backend will apply the same fix to it.

## Review

**Done:** `reclaim_processing_jobs()` in `app/workers/queue.py`, called (a) from `main.py`'s
lifespan before `worker.start()` with no filters — nothing is running yet, so every
`PROCESSING` row is guaranteed orphaned — and (b) from the new `POST /batches/{batch_id}/retry`
in `api/batches.py`, gated to jobs stale 60s+ so it can't race a job the worker is legitimately
still on.

**Flow:** reclaim increments `attempt_count` like any other failed attempt (so a job that keeps
getting orphaned still terminates at `FAILED` after `max_attempts`, never loops forever),
flips it to `RETRYING`, and lets the existing worker/coordinator machinery take it from there —
no new job-processing path.

**Tests:** 8 new (4 in `test_job_queue.py` for `reclaim_processing_jobs()` itself, 3 in
`test_batches_api.py` for the retry endpoint's 404/409/200 paths, 1 in `test_main.py` for the
lifespan wiring). 233 backend tests pass, 97.6% coverage, ruff clean.

**Verified against real data:** dry run on a scratch copy of the actual dev DB (never mutated
the real file) reclaimed batch `7af8bba1`'s 6 orphaned jobs and reprocessed them end to end via
the real worker against the real source PDFs — batch went `PROCESSING` -> `COMPLETED`, 6/6,
0 failed.

**Known follow-up (documented, not in scope):** no execution timeout around OCR extraction
(`services/extraction.py`). A hung `pytesseract`/`poppler` call would still block the
single-threaded worker indefinitely; a proper fix needs process isolation, which conflicts with
`pool.py`'s existing intentional single-thread design.

**Recommended next step:** owner review (branch `fix/stale-processing-jobs`), then merge to
`main`; restarting the real backend after merge applies the startup recovery to the actual
`app.db` and unsticks batch `7af8bba1` for real.
