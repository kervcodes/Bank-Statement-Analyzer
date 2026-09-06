# Todo: Build-plan #5 — Background job queue

Source: `build-plan.md` §5, tracing to `requirements.md` §3 (REQ-PROC-001 through 103) and
`techstack.md` §6.

## Goal (what "done" means for this step)

An upload to `POST /batches` creates one `statement_job` per accepted file, a background worker
picks each job up and runs it through the extraction pipeline from build-plan #4
(`extract_text()`), retries retryable failures up to 2 times, and a `BatchCoordinator` flips the
batch to `COMPLETED` / `COMPLETED_WITH_WARNINGS` once every job reaches a terminal state — end
to end, no manual step.

**Not in scope** (later build-plan steps): bank detection, parsers, `Statement` rows,
normalization, financial validation, analytics. At this step a "COMPLETED" job means *the PDF's
text was extracted*, nothing more. `UNSUPPORTED` is in the status enum (REQ-PROC-002) but is
not reachable until build-plan #6 adds detection — it's carried now so the schema doesn't
change again then.

## State of the repo right now

- Branch `feature/extraction-pipeline` (build-plan #4) is **PR #7, still open**, CI green,
  mergeable. `main` is at build-plan #3.
- `IntakeFile` rows with `status="ACCEPTED"` and a `temp_path` already exist after intake
  (build-plan #3). This step reads those.
- `extract_text(pdf_path) -> ExtractionResult` exists and raises `ExtractionFailedError` on OCR
  failure (build-plan #4).
- `Batch` already has counter columns: `processed`, `processing_failed` (currently only ever 0).
- `db.py` registers an `Engine`-level connect listener (currently just `PRAGMA foreign_keys=ON`).
- Bare `TestClient(app)` is used in tests — FastAPI lifespan events do **not** fire, so a
  lifespan-started worker stays off during tests automatically.

## Step 0 — merge PR #7 first (recommended, your call)

The last two times PRs were stacked on feature branches instead of `main`, `main` silently fell
behind and needed a catch-up PR (#4). To avoid a repeat: **merge PR #7 now**, then this work
branches off an updated `main`. If you'd rather not, I'll base `feature/job-queue` on
`feature/extraction-pipeline` and it becomes a stacked PR — workable, just needs care at merge
time.

## Decisions to confirm before I write code

**1. Worker concurrency model.** `techstack.md` §6 specifies
`concurrent.futures.ProcessPoolExecutor` (OCR/parsing are CPU-bound). For this step I recommend
**deviating to a single background thread running a sequential poll loop**:
  - The queue/retry/coordinator *machinery* is what #5 is about, and it's identical either way.
  - `ProcessPoolExecutor` on Windows uses `spawn` — every job argument and the work function
    must be picklable, child processes each need their own DB engine, and it makes the test
    suite genuinely painful and flaky.
  - Throughput isn't a real problem yet (no measured slow batch, no parsers).
  - Revisit to a process pool in a later step *if* OCR throughput becomes a measured
    bottleneck — it's a change contained to one module (`workers/pool.py`).

  Alternative if you want to stay closer to the spec: `ThreadPoolExecutor` with 2 workers (I/O
  during extraction releases the GIL; CPU-bound OCR won't parallelize, but the retry/coordinator
  race handling gets exercised properly). Say which you want.

**2. Extracted text is not persisted at this step.** The job runs `extract_text()`, records
`extraction_method` (`NATIVE`/`OCR`) and `page_count` on the job row for observability, then
marks `COMPLETED`. It does **not** store the page text — build-plan #6's parser pipeline
re-runs extraction as its first step (extraction of native text is cheap; OCR is the rare
case). Keeps this step from growing a text-storage/cleanup concern that belongs with #6.
Confirm, or say you'd rather cache the text on the job now.

**3. SQLite concurrency pragmas.** Once a background writer exists alongside request handlers,
concurrent writes to one SQLite file produce `database is locked`. I'll add
`PRAGMA journal_mode=WAL` and `PRAGMA busy_timeout=5000` to the existing connect listener in
`db.py`. Standard for this exact setup, low risk. Confirm.

**4. New read endpoint `GET /batches/{batch_id}`.** Returns the batch counters, status, and a
per-job status list. Needed to verify "end to end" here and it's what build-plan #9's History /
progress screens (TanStack Query polling, `techstack.md` §3) will call. Small and thin.
Confirm.

**5. Worker auto-starts via FastAPI lifespan** in dev/packaged runs; stays off under the test
suite's bare `TestClient(app)`. Tests drive the worker explicitly by calling
`run_worker_once()` / `process_job()`. Confirm.

## Retry classification (REQ-PROC-101 / 102)

- `ExtractionFailedError` from build-plan #4 → **retryable** (it wraps OCR-engine failures, a
  corrupt render, a missing binary — the "worker crash / OCR timeout" class in REQ-PROC-101).
  Retried up to 2 times (3 attempts total), then → `FAILED`.
- Deterministic failures (corrupted / password-protected / non-PDF) are already filtered out at
  intake (build-plan #3), so no deterministic-failure path is reachable from extraction alone
  yet. The classification hook (`RetryableJobError` vs letting other exceptions fall through to
  a non-retried `FAILED`) is put in place now for build-plan #6 to use.
- An unexpected exception (not `ExtractionFailedError`) → non-retryable `FAILED`, logged. Not
  swallowed.

## Job state machine

```
QUEUED ──claim──► PROCESSING ──success──────► COMPLETED   (terminal)
                       │
                       ├─ retryable fail, attempts left ─► RETRYING ──re-queue──► (claimable)
                       │
                       ├─ retryable fail, no attempts ───► FAILED       (terminal)
                       │
                       └─ non-retryable fail ────────────► FAILED       (terminal)

(UNSUPPORTED: terminal, not produced until build-plan #6)
```

`RETRYING` rows are claimable alongside `QUEUED` (claimer picks `status IN ('QUEUED','RETRYING')`).
Claiming is one atomic `UPDATE ... WHERE id = ? AND status IN (...)` returning rowcount, so two
workers can't grab the same job.

## Tasks

### 1. Model + migration
- [x] `app/models/jobs.py`: `StatementJob` SQLModel (`statement_job` table) + `JOB_STATUSES`
      tuple + CHECK constraint, matching the `canonical.py` / `intake.py` precedent.
      Fields: `id`, `batch_id` (FK, indexed), `intake_file_id` (FK → `intake_file.id`, indexed),
      `pdf_path` (str — the reference, REQ-PROC-003: never the bytes), `status` (default
      `QUEUED`), `attempt_count` (default 0), `max_attempts` (default 3), `failure_reason`
      (nullable), `extraction_method` (nullable), `page_count` (nullable), `created_at`,
      `updated_at`.
- [x] Export from `app/models/__init__.py`; add to `alembic/env.py`'s model import line.
- [x] `uv run alembic revision --autogenerate -m "add statement_job table"`, review the
      generated migration (fix the known `sqlmodel.sql.sqltypes` import gap if it recurs),
      `uv run alembic upgrade head`.

### 2. Queue repository — `app/workers/queue.py`
- [x] `enqueue_job(session, *, batch_id, intake_file_id, pdf_path) -> StatementJob`
- [x] `claim_next_job(session) -> StatementJob | None` — atomic claim, sets `PROCESSING`
- [x] `mark_completed(session, job, *, method, page_count)`
- [x] `mark_failed(session, job, reason)`
- [x] `record_retryable_failure(session, job, reason)` — increments `attempt_count`; sets
      `RETRYING` (re-queue) if `attempt_count < max_attempts`, else `FAILED`
- [x] Pure DB functions, no FastAPI imports, no extraction imports.

### 3. Processor — `app/workers/processor.py`
- [x] `class RetryableJobError(Exception)` — the classification hook #6 will raise from parser
      code.
- [x] `process_job(session, job) -> None`: load the PDF path, call `extract_text()`, on success
      `mark_completed`; on `ExtractionFailedError` / `RetryableJobError` →
      `record_retryable_failure`; on any other exception → `mark_failed` + `logger.exception`.
- [x] After every terminal or retry transition, call `BatchCoordinator.refresh(session,
      batch_id)`.

### 4. Batch coordinator — `app/workers/coordinator.py`
- [x] `refresh(session, batch_id)`: in one transaction, count that batch's jobs by status.
      While any job is non-terminal → leave batch `PROCESSING`. Once all terminal:
      set `batch.processed` = COMPLETED job count, `batch.processing_failed` = FAILED +
      UNSUPPORTED count, and `batch.status`:
        - `COMPLETED` if `processing_failed == 0` **and** `validation_failed == 0` **and**
          `upload_failed == 0` (REQ-RPT-002: any exclusion at all → warnings)
        - `COMPLETED_WITH_WARNINGS` otherwise
- [x] Idempotent — safe to call repeatedly and from concurrent workers.

### 5. Worker runner — `app/workers/pool.py`
- [x] `run_worker_once(session_factory) -> bool`: claim one job, process it, return whether one
      ran. This is the unit tests drive.
- [x] `run_worker_loop(stop_event)`: poll `run_worker_once` on a short sleep until stopped.
- [x] `start_background_worker()` / `stop_background_worker()`: spawn/join the daemon thread.
- [x] Wire into a FastAPI `lifespan` in `app/main.py` (replacing the bare `app = FastAPI()`).

### 6. Wire intake → queue — `app/api/batches.py`
- [x] After an `IntakeFile` is written as `ACCEPTED`, `enqueue_job(...)` for it.
- [x] Batch starts `PROCESSING` when ≥1 job was queued (unchanged), `FAILED` when 0 accepted
      (unchanged — no jobs, nothing to coordinate).
- [x] `GET /batches/{batch_id}` → `{batch fields, jobs: [{id, status, attempt_count,
      failure_reason, extraction_method}]}`; 404 when unknown.

### 7. Tests — `tests/test_job_queue.py`, extend `tests/test_batches_api.py`
- [x] `conftest.py`: a `job`/`queued_job` fixture; a synthetic native-text PDF helper (reuse
      the hand-built-PDF approach from `test_extraction.py` — move it to `conftest.py` or a
      small `tests/_pdf.py` helper rather than duplicating).
- [x] Happy path: enqueue → `run_worker_once` → job `COMPLETED`, `extraction_method == "NATIVE"`.
- [x] `claim_next_job` returns `None` on an empty queue; claims exactly one when two are queued;
      a claimed job is not re-claimable (simulates two workers).
- [x] Retry: monkeypatch `extract_text` to raise `ExtractionFailedError` →
      first two failures leave the job `RETRYING` with rising `attempt_count`, third →
      `FAILED`. (REQ-PROC-101, and NFR-MAINT-002 calls out retry-state transitions as a
      must-test area.)
- [x] Non-retryable: monkeypatch `extract_text` to raise `ValueError` → job `FAILED`
      immediately, `attempt_count == 1`, no retry.
- [x] Coordinator: batch with 2 jobs stays `PROCESSING` until both terminal; 2×COMPLETED →
      `COMPLETED`; 1 COMPLETED + 1 FAILED → `COMPLETED_WITH_WARNINGS`; a batch that also had an
      intake `validation_failed` and 1 COMPLETED job → `COMPLETED_WITH_WARNINGS`.
- [x] REQ-PROC-004: a `VALIDATION_FAILED` `IntakeFile` never gets a `statement_job` row.
- [x] REQ-PROC-003: assert the job stores a path string, and that the row has no column holding
      file bytes.
- [x] API: `POST /batches` with one good PDF, then `run_worker_once`, then
      `GET /batches/{id}` shows the job `COMPLETED` and batch `COMPLETED`.
- [x] Name tests with REQ IDs where it's natural (`test_req_proc_101_*`).
- [x] Keep total coverage ≥ 90%.

### 8. Checks
- [x] `uv run pytest` (coverage gate), `uv run ruff check .`, `uv run ruff format --check .`
- [x] Manual end-to-end once: start the backend, `POST /batches` a real native-text PDF, poll
      `GET /batches/{id}` until `COMPLETED`.

### 9. Docs
- [x] `docs/activity.md` entry (append).
- [x] `README.md` "Status" + "Next up" sections.

## Review

### What was completed

All 9 task groups. `statement_job` model + migration `06a9bc8c453d`; a pure-DB queue
repository (`workers/queue.py`); the processor with retry classification
(`workers/processor.py`, `RetryableJobError` hook for #6); the idempotent batch coordinator
(`workers/coordinator.py`); the worker runner + `BackgroundWorker` thread wired into a FastAPI
`lifespan` (`workers/pool.py`, `main.py`); intake → queue wiring and `GET /batches/{batch_id}`
(`api/batches.py`); SQLite WAL/busy_timeout pragmas (`db.py`); the shared `tests/_pdf.py` PDF
helper.

### Important changes / deviations

- **Single polling thread, not `ProcessPoolExecutor`** (techstack.md §6) — decision #1, confirmed.
  Contained to `workers/pool.py`; revisit if OCR throughput becomes a measured bottleneck.
- **`mark_failed` now increments `attempt_count`** — the plan's non-retryable test expects
  `attempt_count == 1`, and `mark_failed` wasn't counting the attempt. Now every failure path
  counts the run. A first-try success still leaves `attempt_count == 0` (`mark_completed` doesn't
  count); left as-is rather than doing an "increment at claim" refactor the plan didn't ask for.
- Extracted text is **not persisted** at this step (decision #2) — build-plan #6 re-runs
  extraction.

### Tests performed

`uv run pytest` — 57 passed, 96% coverage (gate 90%). `ruff check` / `ruff format --check` clean.
New: happy path, empty queue, claim-exactly-one + not-reclaimable (two-worker race), REQ-PROC-101
(retry ×2 then FAIL), REQ-PROC-102 (non-retryable fails immediately), coordinator (4 cases incl.
intake-rejection-alone → warnings), REQ-PROC-003 (path not bytes), REQ-PROC-004 (rejected file
gets no job), `BackgroundWorker` thread lifecycle, `POST /batches` → worker → `GET /batches/{id}`
end-to-end, 404. Manual e2e against a real uvicorn server with the lifespan worker running:
PDF + `.txt` → job `COMPLETED` (NATIVE) → batch `COMPLETED_WITH_WARNINGS`.

### Known issues

- Two OCR tests in `test_extraction.py` fail locally unless `C:\Program Files\Tesseract-OCR` is
  on the shell PATH (a build-plan #4 environment quirk, not a regression). CI installs tesseract.
- `workers/pool.py` lines 54 / 66–71 / 73 uncovered — the `start()` re-entry guard and the
  loop's defensive `except`. Edge paths; total coverage still 96%.
- Branch is stacked on `feature/extraction-pipeline` (PR #7), not `main`.

### Recommended next step

Merge PR #7, then this branch's PR, then build-plan #6 — bank detection and parsing (the first
consumer of `RetryableJobError` and the point `UNSUPPORTED` becomes reachable).
