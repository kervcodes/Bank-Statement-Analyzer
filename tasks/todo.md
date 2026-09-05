# Todo: Build-plan #3 — Intake and validation

Source: `build-plan.md` §3, tracing to `requirements.md` §2 (REQ-INT-001 through 006).

Branch: `feature/intake-validation`, based on `main` (currently `9b1c2b0`, which already
includes the coverage gate from the previous task).

## What already exists vs. what this task adds

- `Batch` (canonical schema, step 2) already has `selected`, `uploaded`, `upload_failed`,
  `processed`, `processing_failed`, `status`. No per-file table exists yet — `Statement`
  (step 2) is documented as only ever representing a *parsed* statement, and `statement_jobs`
  (the job-queue table) doesn't exist until step 5.
- This task needs somewhere to persist "file X in batch Y was accepted / rejected / failed to
  upload, and if accepted, where its temp copy lives" — step 5 needs that to build jobs from.
  Adding a new table for this now, rather than stretching `Statement` or reinventing
  `statement_jobs` early.

## Two decisions I want to confirm before writing code

**1. Size/page limits (REQ-INT-003 doesn't give numbers).** Proposing **25 MB per file, 300
pages per file** as the "supported size/page count" ceiling — generous for a real bank/card
statement (even a dense annual summary), cheap to check before attempting extraction. Tell me
if you want different numbers.

**2. Batch-level counters don't have a slot for "rejected at validation."** Design-notes.md's
upload screen shows four distinct counts — *selected, ready, failed, rejected* — but `Batch`
only has `selected / uploaded / upload_failed / processed / processing_failed`. Two ways to
close that gap:
   - **(a) Add a `validation_failed` column to `Batch`** via a new Alembic migration. Keeps
     every state distinct and matches the UI's four counters exactly. Touches the
     already-merged canonical-schema migration chain (additively, not a rewrite).
     **Recommended** — REQ-INT-002 specifically requires upload-failure and validation-failure
     to be distinct *and testable*, and collapsing them into one counter at the batch level
     would undercut that at the one place (the batch summary) where it's most visible.
   - (b) Reuse `processing_failed` to mean "any file that will never become a Statement,"
     whether the cause is validation-rejection now or an extraction/parsing failure later
     (step 4-6). No schema change, but overloads a field name that `requirements.md`/
     `techstack.md` tie specifically to job *processing*.

   Going with **(a)** unless you say otherwise.

## 1. Dependency

- [x] Add `pypdf` to `apps/backend/pyproject.toml` — lightweight, pure-Python, purpose-built
      for reading PDF structure/metadata (`is_encrypted`, page count, raises on a corrupted
      file) without pulling in the heavier `pdfplumber`/`pdfminer.six` extraction stack a step
      early (that's step 4's dependency, for a different job: reading page *content*).

## 2. Schema change

- [x] `Batch`: add `validation_failed: int` column (decision 2a above)
- [x] New model `IntakeFile` (`app/models/intake.py`): `id`, `batch_id` (FK),
      `original_filename`, `status` (`ACCEPTED` / `UPLOAD_FAILED` / `VALIDATION_FAILED`),
      `failure_reason` (nullable — the specific, actionable reason from REQ-INT-004), `temp_path`
      (nullable, populated only when `ACCEPTED`), `page_count` (nullable), `created_at`
- [x] Alembic migration for both changes
- [x] Export `IntakeFile` from `app/models/__init__.py` alongside the existing models

## 3. Validation service

- [x] `app/services/intake_validation.py`: given raw bytes + filename, return a validation
      result (accepted / rejected + specific reason). Checks, in order:
      1. Extension/content sniff: reject non-PDF outright (REQ-INT-004)
      2. Size check (25 MB default, see decision 1)
      3. Open with `pypdf.PdfReader`: corrupted → reject with "corrupted PDF"; encrypted →
         reject with "password-protected"
      4. Page count check (300 default)
- [x] Pure function, no FastAPI/DB imports, so it's directly unit-testable

## 4. Temp storage

- [x] Accepted files get written to `apps/backend/data/tmp/<batch_id>/<intake_file_id>.pdf`
      (same `data/` dir `db.py` already creates, matching techstack.md's "app's local
      temp/user-data directory")
- [x] Rejected/upload-failed files are never written to temp storage

## 5. API endpoint

- [x] `app/api/batches.py` (new `api/` package, per techstack.md's structure): `POST /batches`,
      `multipart/form-data`, one or more files
      - Create the `Batch` row first (REQ-INT-006: tracked from the moment files are selected)
      - For each file: attempt to read its bytes (an `UPLOAD_FAILED` `IntakeFile` row if that
        raises — e.g. an empty/unreadable part), else run it through the validation service
        and record `ACCEPTED` or `VALIDATION_FAILED`
      - One file's failure never stops the loop over the rest (REQ-INT-005)
      - Update the `Batch` counts (`selected`, `uploaded`, `upload_failed`, `validation_failed`)
        and set `status`: `PROCESSING` if at least one file was accepted, `FAILED` if none were
        (there's no queue to hand accepted files to yet — that's step 5)
      - Response: the batch id/counts plus one entry per file (`filename`, `status`,
        `failure_reason`)
- [x] Wire the router into `main.py`

## 6. Tests

- [x] Unit tests for `intake_validation.py`: non-PDF file, corrupted PDF, password-protected
      PDF, oversized file, too-many-pages file, valid small PDF — generating tiny PDFs
      on-the-fly with `pypdf`/`reportlab`-free stdlib-ish approach (or a minimal hand-built PDF
      byte string) rather than committing binary fixtures for this step; real bank-statement
      fixtures come in step 6 per `techstack.md`'s `tests/fixtures/statements/`
- [x] API test for `POST /batches`: mixed batch (one valid, one corrupted, one
      password-protected, one non-PDF) asserts per-file distinct statuses/reasons and correct
      batch counts/status
- [x] Keep the 90% coverage gate green (`uv run pytest`)

## 7. Docs

- [x] `docs/activity.md` entry for this task
- [x] `README.md` status section if it still says "no intake endpoint yet"

## Review

**What was completed:** the intake and validation flow from build-plan #3 / REQ-INT-001–006.
`POST /batches` accepts one or more PDFs, creates a `Batch` row up front, validates each file
independently against REQ-INT-003/004 (extension, size, corruption, password-protection, page
count), writes accepted files to `data/tmp/<batch_id>/<intake_file_id>.pdf`, and persists a
per-file `IntakeFile` row with a distinct `ACCEPTED`/`UPLOAD_FAILED`/`VALIDATION_FAILED` status
and specific failure reason. Batch counters (`uploaded`, `upload_failed`, new
`validation_failed`) update per file; one file's rejection never stops the rest (REQ-INT-005).

**Both open decisions confirmed by the user before implementation:** 25 MB / 300-page limits,
and adding `Batch.validation_failed` as a new column (migration `a210b74a5423`) rather than
overloading `processing_failed`.

**Found and fixed along the way:** `pypdf` reports `is_encrypted=True` for PDFs that are
encrypted only to restrict printing/copying but have an empty user password — those open
without a prompt and aren't "password-protected" in REQ-INT-003's sense. Fixed by only
rejecting when `PdfReader.decrypt("")` returns `PasswordType.NOT_DECRYPTED` (a real user
password is actually required). Covered by `test_owner_only_encryption_is_accepted`.

**Also closed:** `main.py`/`/health` had 0% test coverage (a known gap flagged by the previous
task). This task was already touching `main.py` to wire in the router, so added the trivial
`test_main.py` rather than let the gap persist.

**Tests/checks run:**
- `uv run pytest` — 39 passed, 96% coverage (gate: 90%)
- `uv run ruff check .` and `uv run ruff format --check .` — both clean
- Manually confirmed accepted files land on disk and rejected files never get a `temp_path`
  (asserted in `test_batches_api.py`)

**Known issues / deliberate gaps:**
- `IntakeFile.status == "UPLOAD_FAILED"` has no test. By the time a multipart request reaches
  this endpoint, Starlette has already parsed it into `UploadFile` objects, so the failure mode
  this branch guards against (`upload.read()` raising `OSError`) isn't realistically reachable
  via `TestClient` without mocking internals — decided that's lower value than a real test.
  Design-notes.md's "upload failed" state may in practice be a frontend-only concept (a local
  file-read error in Electron before the request is even sent); worth revisiting once build-plan
  #9 (frontend) exists and it's clear whether the backend ever actually produces this state.
- No real bank-statement PDF fixtures yet — intentional, per build-plan #6 (`tests/fixtures/
  statements/` is for the first real parser, not this step). This step's tests generate tiny
  PDFs on the fly with `pypdf.PdfWriter`.
- `db.py`'s pre-existing `get_session()` (unused before this task) still has no direct test —
  not touched, out of scope for this task.

**Recommended next step:** build-plan.md #4 — extraction pipeline (native text via `pdfplumber`,
OCR fallback via `pdf2image`/`pytesseract`).
