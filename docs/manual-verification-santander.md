# Manual verification guide — build-plan #6 (Santander checking, end to end)

A step-by-step runbook to thoroughly check the application state after build-plan #6 is
implemented. Work top to bottom. Every step says what to run and what a **pass** looks like.

**Scope of #6:** a real Santander checking PDF goes in → detection → `santander_checking_v1`
parser → normalization into the canonical schema → three-level financial validation → a
`Statement` + `Transaction` rows + a resolved `Account`, or a clean `UNSUPPORTED` if detection
confidence is too low.

**Explicitly NOT testable yet** (later build-plan steps — do not treat as bugs):
deduplication and analytics (#7); categorization, merchant normalization, Privacy Gateway,
LLM summary (#8); any frontend screen (#9); the Windows installer (#10); automatic deletion of
the raw PDF after processing (REQ-CLEAN-001, not yet wired — temp PDFs will still be on disk
under `apps/backend/data/tmp/` after a run).

All commands are run from `apps/backend/` unless noted. Shell is PowerShell on Windows; use
`curl.exe` (not `curl`, which is a PowerShell alias).

---

## 0. One-time setup

```powershell
# from the repo root
cd apps\backend
uv sync
uv run alembic upgrade head
```

- [ ] `uv sync` completes with no error.
- [ ] `alembic upgrade head` ends at the newest revision (the `statement_job.statement_id`
      migration from #6). Re-running it says "nothing to upgrade".

Confirm the OCR toolchain is reachable (needed only if any statement lands on the OCR path;
Santander PDFs are normally native text):

```powershell
tesseract --version
pdftoppm -v
```

- [ ] Both print a version. If `tesseract` is not found, add `C:\Program Files\Tesseract-OCR`
      to PATH and open a new terminal.

Drop your real statements in:

```text
apps\backend\tests\fixtures\statements\local\
```

- [ ] 3+ real Santander checking PDFs are in that folder.
- [ ] `git status` does **not** list them (the repo-wide `*.pdf` ignore rule covers them).

---

## 1. Automated suite — the real gate

This is the primary check. The manual steps below only exist to catch what a synthetic
fixture can't.

```powershell
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

- [ ] `pytest` — all pass, coverage line ≥ 90% (the run fails itself otherwise).
- [ ] These new files ran and passed:
      `test_detection.py`, `test_santander_checking_v1.py`, `test_normalization.py`,
      `test_financial_validation.py`, plus the extended `test_job_queue.py` /
      `test_batches_api.py`.
- [ ] `test_santander_local_golden.py` — **did not skip**. It should report one parametrized
      case per PDF in `tests/fixtures/statements/local/`. If it says "skipped", the folder is
      empty or the files aren't `.pdf`.
- [ ] `ruff check` and `ruff format --check` both clean.

If the local golden test **fails** on a real statement, that is the highest-value signal in
this whole guide — it means the parser or detection is wrong for a layout you actually have.
Note which file and the assertion, and stop here.

---

## 2. Backend end-to-end — happy path

### 2a. Start the backend with the worker running

In a dedicated terminal (leave it running):

```powershell
uv run uvicorn app.main:app --port 8420
```

- [ ] Startup logs show the background worker starting (FastAPI lifespan).
- [ ] `curl.exe -s http://127.0.0.1:8420/health` → `{"status":"ok"}`.

> Use plain `uvicorn` without `--reload` here — `--reload` can spawn a second worker thread.

### 2b. Upload one real Santander statement

In a second terminal, from `apps/backend/`:

```powershell
curl.exe -s -F "files=@tests/fixtures/statements/local/YOUR-STATEMENT.pdf" http://127.0.0.1:8420/batches
```

- [ ] Response is JSON with a `batch_id`, `status: "PROCESSING"`, `uploaded: 1`,
      `validation_failed: 0`, and the file listed as `ACCEPTED`.
- [ ] Copy the `batch_id`.

### 2c. Poll until the batch finishes

```powershell
curl.exe -s http://127.0.0.1:8420/batches/PASTE-BATCH-ID | ConvertFrom-Json | ConvertTo-Json -Depth 5
```

Run it a few times over ~5–10 seconds.

- [ ] The job moves `QUEUED` → `PROCESSING` → `COMPLETED`.
- [ ] Batch `status` ends `COMPLETED` (a clean statement that reconciles) — **not**
      `COMPLETED_WITH_WARNINGS`.
- [ ] The job row has `extraction_method: "NATIVE"` (Santander statements have embedded text),
      `attempt_count: 0`, `failure_reason: null`.
- [ ] The response now includes a `statements` array with one entry:
      `bank: "Santander"`, `account_type: "checking"`, `account_identifier_masked` = last 4
      digits only, `extraction_status: "SUCCESS"`, `validation_result: "VALID"`.

### 2d. Inspect the database against the paper statement

```powershell
uv run python - <<'PY'
from sqlmodel import Session, select
from app.db import engine
from app.models import Statement, Transaction, Account, StatementJob, to_decimal

with Session(engine) as s:
    st = s.exec(select(Statement).order_by(Statement.id)).all()[-1]
    print("STATEMENT")
    print(" bank/type       ", st.bank, st.account_type)
    print(" masked acct     ", st.account_identifier_masked)
    print(" period          ", st.statement_start_date, "->", st.statement_end_date)
    print(" opening/closing ", to_decimal(st.opening_balance_cents), to_decimal(st.closing_balance_cents))
    print(" parser_version  ", st.parser_version)
    print(" extraction/valid", st.extraction_status, st.validation_result)

    txns = s.exec(select(Transaction).where(Transaction.statement_id == st.id)
                  .order_by(Transaction.transaction_date)).all()
    print(f"\nTRANSACTIONS ({len(txns)})")
    credits = sum(t.amount_cents for t in txns if t.direction == "CREDIT")
    debits  = sum(t.amount_cents for t in txns if t.direction == "DEBIT")
    for t in txns:
        print(f"  {t.transaction_date}  {t.direction:6}  {to_decimal(t.amount_cents):>10}  "
              f"p{t.source_page}  {t.description_normalized[:40]}")
    print(f"\n  credits {to_decimal(credits)}  debits {to_decimal(debits)}")
    recon = st.opening_balance_cents + credits - debits
    print(f"  opening + credits - debits = {to_decimal(recon)}   "
          f"closing = {to_decimal(st.closing_balance_cents)}   "
          f"{'MATCH' if recon == st.closing_balance_cents else 'MISMATCH'}")

    acct = s.get(Account, st.account_id)
    print("\nACCOUNT", acct.id, acct.bank, acct.account_type, acct.account_identifier_masked)

    job = s.exec(select(StatementJob).where(StatementJob.batch_id == st.batch_id)).first()
    print("JOB", job.status, "statement_id set:", job.statement_id == st.id)
PY
```

Now cross-check against the actual paper/PDF statement:

- [ ] **Opening balance** matches the statement's "Beginning Balance".
- [ ] **Closing balance** matches "Ending Balance".
- [ ] **Statement period** dates match.
- [ ] **Masked account** = the real last 4 digits, and the full number appears **nowhere**
      (checked properly in step 6).
- [ ] **Transaction count** matches the statement (count deposits + withdrawals + fees +
      interest — everything with a dollar amount that moves the balance).
- [ ] Spot-check **5 transactions**: date, amount to the cent, and DEBIT/CREDIT direction all
      correct.
- [ ] The reconciliation line at the bottom of the script prints **MATCH**.
- [ ] `parser_version` is `santander_checking_v1`.
- [ ] `JOB ... statement_id set: True`.

Repeat 2b–2d for **each** real statement you have. Every one should land `COMPLETED` /
`VALID` / `MATCH` unless you know it genuinely doesn't balance (that's step 4).

---

## 3. Detection and the `UNSUPPORTED` path

### 3a. A non-Santander PDF

Upload any PDF that is **not** a Santander checking statement — a Chase statement, a utility
bill, any random text PDF:

```powershell
curl.exe -s -F "files=@C:\path\to\some-other.pdf" http://127.0.0.1:8420/batches
# then poll GET /batches/{id}
```

- [ ] The job ends `UNSUPPORTED` (not `FAILED`, not `COMPLETED`).
- [ ] `failure_reason` explains it — e.g. "detection confidence 0.30 below threshold 0.70".
- [ ] The batch ends `COMPLETED_WITH_WARNINGS`.
- [ ] The `statements` array is **empty** — no `Statement` row was created (REQ-VAL-005).

Verify no orph/ partial statement row:

```powershell
uv run python -c "from sqlmodel import Session, select, func; from app.db import engine; from app.models import Statement; s=Session(engine); print('statements total:', s.exec(select(func.count()).select_from(Statement)).one())"
```

- [ ] The count only went up by the number of *successful* uploads so far, not by the
      unsupported one.

### 3b. A garbage / near-empty PDF

- [ ] A PDF with almost no text → also `UNSUPPORTED` (low confidence), not a crash.

### 3c. Intake rejects still work (regression from #3)

```powershell
# non-PDF
"not a pdf" | Out-File -Encoding ascii bad.txt
curl.exe -s -F "files=@bad.txt" http://127.0.0.1:8420/batches
```

- [ ] File comes back `VALIDATION_FAILED` with a specific reason, batch `status: "FAILED"`
      (nothing accepted), and **no job** is created for it.

---

## 4. Reconciliation `FAILED` path

Use a statement you know doesn't balance, or make one:

- Easiest: take a real statement PDF, and in step 2b upload it — then in the DB, this path is
  proven only if the parser correctly reports the mismatch. If all your real statements
  balance, create a synthetic bad one by editing the committed sample builder in a scratch
  script, or ask me to add a dedicated `test_req_val_001` fixture (already in the plan's test
  list — so **step 1 already covers this automatically**).

Manual check if you have a genuinely unbalanced statement:

- [ ] Job ends `COMPLETED` (the PDF parsed fine — extraction and parsing succeeded).
- [ ] `validation_result: "FAILED"`.
- [ ] Batch ends `COMPLETED_WITH_WARNINGS`, never plain `COMPLETED`.
- [ ] The `Statement` and `Transaction` rows still exist (a failed-validation statement is
      kept, just flagged — REQ-VAL-003).

---

## 5. Multi-file batch — failure isolation

Upload 3 good Santander PDFs + 1 non-PDF (or 1 non-Santander PDF) in **one** request:

```powershell
curl.exe -s `
  -F "files=@tests/fixtures/statements/local/a.pdf" `
  -F "files=@tests/fixtures/statements/local/b.pdf" `
  -F "files=@tests/fixtures/statements/local/c.pdf" `
  -F "files=@bad.txt" `
  http://127.0.0.1:8420/batches
```

- [ ] The 3 valid statements each produce a `COMPLETED` job and a `VALID` statement.
- [ ] The bad file is `VALIDATION_FAILED` (or its job `UNSUPPORTED` if it was a real PDF).
- [ ] Batch ends `COMPLETED_WITH_WARNINGS` with `processed: 3` and the excluded file counted.
- [ ] The one bad file did **not** block or discard the other three (REQ-INT-005, NFR-REL-001).

---

## 6. Account resolution

### 6a. Same account, two months → one `Account`

Upload two *different months* for the *same* Santander checking account (separate batches is
fine).

```powershell
uv run python -c "from sqlmodel import Session, select; from app.db import engine; from app.models import Account; s=Session(engine); [print(a.id, a.bank, a.account_type, a.account_identifier_masked) for a in s.exec(select(Account)).all()]"
```

- [ ] Exactly **one** `Account` row for that masked number, even though there are two
      `Statement` rows pointing at it (REQ-ACC-002 — not re-created per statement).

### 6b. Different account, same bank → two `Account` rows

Only if you have statements for a second Santander account (different last 4):

- [ ] Two distinct `Account` rows — one per masked number. The two are **not** merged just
      because the bank name matches.

---

## 7. Privacy and traceability

### 7a. Full account number is never stored

Find your real full account number on the paper statement, then:

```powershell
uv run python - <<'PY'
import sqlite3
FULL = "REPLACE_WITH_FULL_ACCOUNT_NUMBER"
con = sqlite3.connect("data/app.db")
hits = []
for (tbl,) in con.execute("select name from sqlite_master where type='table'"):
    cols = [c[1] for c in con.execute(f"PRAGMA table_info('{tbl}')")]
    for row in con.execute(f"select * from '{tbl}'"):
        for col, val in zip(cols, row):
            if isinstance(val, str) and FULL in val:
                hits.append((tbl, col, val))
print("HITS:", hits or "none")
PY
```

- [ ] `HITS: none`. Only the last 4 digits appear anywhere (REQ-ACC-001, techstack §16).

### 7b. Logs don't leak

```powershell
# scroll the uvicorn terminal output, or if you redirected it to a file, grep it
```

- [ ] No full account number, no full raw statement text, no PII dumped in the backend logs
      (REQ-CLEAN-003). Job failure reasons are short and non-sensitive.

### 7c. Every transaction is traceable

From the step 2d output:

- [ ] Every `Transaction` has a non-null `statement_id` and a sensible `source_page`
      (1-indexed, within the statement's page count).
- [ ] `description_raw` is the original text verbatim; `description_normalized` is a cleaned
      version and `description_raw` was **not** overwritten (REQ-NORM-002).
- [ ] `amount_cents` is a non-negative integer; `direction` carries the sign (REQ-NORM-003).

---

## 8. (Optional) Full Electron end to end

Only if you want to see it through the actual app shell (no UI for batches yet, so this just
confirms the sidecar still spawns):

```powershell
cd ..\desktop
pnpm install
pnpm dev
```

- [ ] Electron window opens, the health card shows `{"status":"ok"}` — the backend spawned as
      a sidecar and the new code didn't break startup.

---

## 9. Resetting state between runs

The dev DB accumulates rows across runs. To start clean:

```powershell
# stop the uvicorn terminal first (Ctrl+C), and close DB Browser if open
# from the repo root
cd apps\backend
Remove-Item data\app.db, data\app.db-wal, data\app.db-shm -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force data\tmp -ErrorAction SilentlyContinue
uv run alembic upgrade head
```

- [ ] Fresh `app.db`, no rows, schema at head. (If `app.db` won't delete, something still has
      it open — a stale `uvicorn`/`python` process or DB Browser.)

---

## 10. Sign-off checklist (maps to requirements.md)

Check every box before calling #6 done:

- [ ] `uv run pytest` green, coverage ≥ 90%; `ruff check` / `ruff format --check` clean.
- [ ] `test_santander_local_golden.py` ran against real PDFs and passed (did not skip).
- [ ] A real Santander PDF → `Statement` + `Transaction` rows + one resolved `Account`,
      `validation_result: VALID`, reconciliation MATCH against the paper statement. (REQ-DET-001,
      REQ-NORM-001/003/006, REQ-VAL-001)
- [ ] Detection reads bank/type/layout from **content**, never the filename (rename a file and
      re-upload — same result). (REQ-DET-001)
- [ ] Below-threshold detection → job `UNSUPPORTED`, zero `Statement` rows. (REQ-DET-002,
      REQ-VAL-005)
- [ ] A statement that doesn't reconcile → job `COMPLETED`, `validation_result: FAILED`, rows
      kept, batch `COMPLETED_WITH_WARNINGS`. (REQ-VAL-002/003, REQ-RPT-002)
- [ ] Mixed batch: one bad file never blocks the good ones. (REQ-INT-005, NFR-REL-001)
- [ ] Two statements for one account → one `Account`; two accounts at one bank → two.
      (REQ-ACC-002)
- [ ] Full account number stored nowhere; only last 4. Logs clean. (REQ-ACC-001, REQ-CLEAN-003)
- [ ] Every transaction has `statement_id`, `source_page`, `parser_version` reachable.
      (REQ-NORM-004, REQ-RPT-003)
- [ ] `description_raw` preserved unmodified alongside `description_normalized`. (REQ-NORM-002)
