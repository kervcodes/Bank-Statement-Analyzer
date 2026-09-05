# Todo: Money as integer cents + schema constraints

Source: `techstack.md` §9 (canonical schema, reconciliation), `requirements.md` §6 (REQ-NORM-003),
§8 (REQ-VAL-001), §9 (REQ-DEDUP-002), §17.5 (NFR-MAINT-002).

**Status: approved 2026-09-05 and implemented. See Review at the bottom.**

## Why this task exists

Verification of build-plan #2 found three defects that the passing test suite did not catch.
All three are in the schema produced by commit `f8e978a`, which is not yet merged to `main`.

1. **Money loses precision.** `Decimal` fields land in SQLite as `REAL` (binary float).
   Measured: `Decimal("12345678.91")` round-trips as `Decimal("12345678.9100000001")`.
   Small values survive, large ones don't — so the corruption is magnitude-dependent and
   invisible to tests that use `15.99`. This breaks REQ-DEDUP-002 (exact amount matching)
   and corrupts REQ-VAL-001 reconciliation, whose rounding tolerance would *hide* the drift
   rather than report it.
2. **Foreign keys are not enforced.** SQLite defaults `PRAGMA foreign_keys` to `OFF` per
   connection. Measured: a `Transaction` with `statement_id="does-not-exist-anywhere"` was
   accepted and committed. The declared FKs are currently documentation, not constraints.
3. **State fields are unconstrained free text.** Measured: `direction="NOT_A_REAL_DIRECTION"`
   was accepted. `amount` is documented as always positive (REQ-NORM-003) with nothing
   enforcing it.

Decision on (1): **integer minor units**, chosen over a `Decimal`-as-TEXT type decorator.
Reasoning and the rejected alternative are recorded in the Decision note (see final task).

## Branch

Continue on `feature/canonical-schema` — it is unmerged, so the existing migration gets
revised in place rather than stacking a corrective migration on top of a schema that was
never released. `data/` is gitignored and the local `app.db` is disposable dev data.

## 1. Money conversion boundary

- [x] Add `src/app/models/money.py` with exactly two functions: `to_cents(Decimal) -> int`
      and `to_decimal(int) -> Decimal`. No class, no abstraction — this is the single place
      dollars and cents convert.
- [x] `to_cents` raises on input with more than 2 decimal places rather than silently
      rounding. A parser producing sub-cent precision is a bug worth surfacing loudly;
      silent rounding is the failure mode this whole task exists to remove.
      **Open question for review:** confirm this is the behavior you want before I build it.
- [x] Unit tests for both directions, including `Decimal("12345678.91")`, `Decimal("0.10")`,
      `Decimal("0")`, and the sub-cent rejection case.

## 1b. Derived-value policy (answers question 1)

Integer cents makes addition, subtraction, and comparison exact — which covers reconciliation,
dedup, and every total. Division does not stay exact: averages, category percentages, and
month-over-month deltas produce fractions.

- [x] Rule to follow everywhere downstream: **stored values are always exact integer cents.
      Derived ratios are computed in `Decimal` at read time and never written back to the
      database as if they were exact.** A rounded average persisted as a fact is how a
      "trustworthy" system starts lying.
- [x] Note this rule in `docs/activity.md` so the analytics work in build-plan #7 inherits it.

## 2. Model changes — `src/app/models/canonical.py`

- [x] `Transaction.amount: Decimal` → `amount_cents: int`
- [x] `Transaction.balance_after: Decimal | None` → `balance_after_cents: int | None`
- [x] `Statement.opening_balance` / `closing_balance` → `opening_balance_cents` /
      `closing_balance_cents`, both `int`
- [x] Update the `Transaction` docstring: amount is a non-negative integer count of minor
      units, `direction` carries the sign (REQ-NORM-003 unchanged in meaning)
- [x] Add `Statement.validation_result: str | None` (answers question 3). Nullable because
      validation has not run when the row is created. Values `VALID` / `WARNING` / `FAILED`
      per REQ-VAL-002 and `techstack.md` §9.
- [x] Docstring on both fields stating the REQ-VAL-004 separation explicitly:
      `extraction_status` answers "could we read the document", `validation_result` answers
      "do the numbers reconcile". They are never combined into one score.

## 3. Constraints

- [x] `CHECK (direction IN ('DEBIT', 'CREDIT'))` on `transaction`
- [x] `CHECK (amount_cents >= 0)` on `transaction`
- [x] `CHECK (status IN ('PROCESSING', 'COMPLETED', 'COMPLETED_WITH_WARNINGS', 'FAILED'))`
      on `batch` — values taken from the existing model docstring, which matches
      `techstack.md` §6
- [x] `CHECK (extraction_status IN ('SUCCESS', 'PARTIAL'))` on `statement` (answers
      question 2 — reasoning below)
- [x] `CHECK (validation_result IS NULL OR validation_result IN ('VALID', 'WARNING', 'FAILED'))`
      on `statement`

### Why only SUCCESS and PARTIAL

The enumeration was never the real question. The real question is **whether a `Statement` row
can exist for a file that never parsed** — and the requirements answer it:

- REQ-DET-002: below the detection confidence threshold, a statement is marked `UNSUPPORTED`
  and never parsed at all.
- REQ-EXT-004: an OCR failure is a processing failure, not partial text.
- REQ-PROC-002: per-statement job status already owns the lifecycle
  (`QUEUED`/`PROCESSING`/`RETRYING`/`COMPLETED`/`FAILED`/`UNSUPPORTED`).
- REQ-REV-001 / REQ-REV-003 / REQ-RPT-001: failed and unsupported statements must still be
  visible in Review, retryable, and counted in coverage.

A statement that failed extraction has no bank, no dates, no balances, and no parser version —
every one of which is `NOT NULL` on `Statement` today. So it *cannot* be stored there without
making most of the table nullable.

**Decision: `Statement` stays parsed-only.** If a `Statement` row exists, its numbers are
real. Failure and unsupported states live on the `statement_jobs` table built in build-plan
#5, which already owns that state machine per REQ-PROC-002 and carries the file reference
needed for REQ-REV-003's retry/re-upload action.

That leaves exactly two outcomes a *parsed* statement can hold: `SUCCESS`, or `PARTIAL` where
parsing completed but some transactions came through low-confidence.

**Rejected alternative:** create a `Statement` row per uploaded file at intake, make all
parse-derived fields nullable, and let `extraction_status` carry the full lifecycle
(`PENDING`/`SUCCESS`/`PARTIAL`/`FAILED`/`UNSUPPORTED`). One table to query for Review and
coverage, and failure history survives job cleanup. Rejected because it makes ten columns
nullable and destroys the invariant that a `Statement` row is trustworthy — every downstream
query would need a "is this one actually parsed?" guard, and the first place someone forgets
is a dashboard total.

**Consequence to carry into build-plan #5:** `statement_jobs` rows must be *retained*, not
pruned after completion, or failure history and the "117 of 120" coverage count in
`techstack.md` §9 disappear. Record this when that table is built.

## 4. Foreign key enforcement

- [x] Add a SQLAlchemy `connect` event listener issuing `PRAGMA foreign_keys=ON`, applied to
      every engine the app creates
- [x] Make the test fixture in `tests/test_canonical_models.py` use the same engine
      construction path as `db.py`, so tests actually exercise the pragma. Today the fixture
      builds its own bare engine — a fix applied only to `db.py` would leave the tests
      passing against unenforced FKs, which is how this defect survived the first time.

## 5. Indexes

- [x] Index `transaction.statement_id` (hottest lookup — every statement view and the
      reconciliation pass filters on it)
- [x] Index `transaction.account_id`, `statement.batch_id`, `statement.account_id`
- [x] **Not doing:** composite indexes for dedup matching. REQ-DEDUP-002's exact match
      column set isn't built until build-plan #7; indexing for it now is guessing.

## 6. Migration

- [x] Revise `alembic/versions/514aa3a0a621_create_canonical_schema.py` in place to emit the
      new columns, CHECK constraints, and indexes
- [x] Delete the local `apps/backend/data/app.db`, re-run `alembic upgrade head`, confirm the
      schema in DB Browser shows `INTEGER` amount columns and non-zero `Indices`

## 7. Tests that would have caught all three defects

These are the point of the task. NFR-MAINT-002 already requires dedicated tests for
reconciliation; these sit one layer below it.

- [x] **Precision:** store `12345678.91` (as cents), read back, assert exact equality
- [x] **Reconciliation arithmetic:** `opening + credits - debits == closing` computed in
      integer cents, asserting exact equality with no tolerance — proving the tolerance in
      REQ-VAL-001 is there for statement quirks, not for storage error
- [x] **FK enforcement:** inserting a transaction with a nonexistent `statement_id` raises
      `IntegrityError`
- [x] **CHECK enforcement:** `direction="SIDEWAYS"` raises; `amount_cents=-1` raises;
      `extraction_status="MAYBE"` raises; `validation_result="OK"` raises
- [x] **REQ-VAL-004 separation:** a statement with `extraction_status="SUCCESS"` and
      `validation_result="FAILED"` is a legal, storable state — the two signals are
      independent and one does not constrain the other
- [x] Update the two existing round-trip tests for the renamed columns

## 8. Close out

- [x] `uv run pytest` — 29 passed
- [x] Ruff installed and run (approved 2026-09-05): `uv add --dev ruff`, `uv run ruff check .`
      found 13 style issues (import sorting, `Union`/`X|Y` modernization, `datetime.UTC`,
      a `dict()`-as-literal rewrite in a test) — none were correctness bugs. 12 auto-fixed,
      1 (`dict()` → literal) fixed by hand since ruff didn't offer an automatic fix for it.
      `uv run ruff format .` reformatted 3 files, purely cosmetic (quote style, line
      wrapping). Re-ran the full test suite after both — still 29 passed.
- [x] Append to `docs/activity.md`: the three defects, how each was found, the decision and
      its rejected alternative
- [x] Draft a decision note for `09 Decisions/` in the vault covering integer cents vs.
      `Decimal`-as-TEXT, with the reasoning and the rejected option preserved
- [x] Second decision note: `Statement` is parsed-only, failures live on `statement_jobs`,
      with the nullable-Statement alternative and why it was rejected
- [x] Updated `requirements.md` (approved 2026-09-05): added REQ-NORM-006 (integer minor
      units, reject sub-cent input rather than round), REQ-VAL-005 (`Statement` is
      parsed-only), and expanded REQ-VAL-004 to name the two concrete fields
      (`extraction_status`, `validation_result`) and their values. Also fixed
      REQ-NORM-004's stale `source_statement_id` to the field name actually implemented,
      `statement_id` (per the naming decision from build-plan #2).
- [x] Rebuilt `data/app.db` — DB Browser (and several stale backend dev processes still
      holding a connection) had the file locked; closed them and re-ran
      `alembic upgrade head`. Verified via direct SQLite inspection: `INTEGER` money columns,
      5 CHECK constraints, 4 indexes, all four tables present.
- [x] Commit `feature/canonical-schema`

## Out of scope

- API/serialization boundary (cents → display dollars). No endpoints exist yet; this belongs
  with build-plan #3.
- A SQL view for human-readable amounts in DB Browser. Worth having, but it's ergonomics,
  not correctness — raise it after the schema is right.
- Any parser, extraction, or job-queue work (build-plan #4 and #5).
- The `statement_jobs` table itself. The decision above says failures live there, but that
  table is build-plan #5's work. Nothing in this task depends on it existing yet.
- A `source_filename` on `Statement`. REQ-REV-003 requires a failed statement to offer a
  re-upload prompt, which needs the filename — but under the decision above that belongs on
  `statement_jobs`, not here. Raised so it isn't lost; not built now.

## Answers recorded (2026-09-05)

1. **Sub-cent input → raise, never round.** Confirmed: no cent amounts are lost, and nothing
   is silently discarded. Added the derived-value rule as §1b, because "stay accurate" has a
   second half — exact storage is only half the guarantee if a rounded average gets written
   back as a fact.
2. **`extraction_status` → `SUCCESS` / `PARTIAL`.** Resolved by following the requirements
   rather than guessing; the reasoning and the rejected alternative are in §3 above.
3. **Both fields exist.** `extraction_status` and `validation_result` are now separate
   columns with separate CHECK constraints and a test asserting they vary independently.

## Remaining question

**Scope check.** Answering (2) grew this task: it now settles where failed statements live,
which is really a build-plan #5 decision made early. That is defensible — the migration is
already open and the alternative is a nullable-everything schema that gets harder to undo
later — but it is scope growth on a task that started as "fix the money type." Confirm you
want the `Statement`-stays-parsed-only decision made now, or tell me to constrain
`extraction_status` to `SUCCESS`/`PARTIAL` and defer the rest to #5.

---

## Review

**Completed.** All three defects found during build-plan #2 verification are fixed, and the
schema now enforces what it previously only documented.

### What changed

- New `src/app/models/money.py` - `to_cents` / `to_decimal`, the single conversion boundary.
  Sub-cent input raises `SubCentPrecisionError` rather than rounding.
- `canonical.py` - money columns are integer cents (`amount_cents`, `balance_after_cents`,
  `opening_balance_cents`, `closing_balance_cents`); added `validation_result`; added five
  CHECK constraints and four indexes.
- `db.py` - `PRAGMA foreign_keys=ON` via an `Engine`-level `connect` listener, registered on
  the class rather than one instance so every engine (including the tests') is covered.
- New `tests/conftest.py` - shared fixtures that import `app.db`, so the suite runs against the
  same engine configuration as the app. The old fixture built a bare engine, which is exactly
  why the FK defect was invisible.
- Migration `514aa3a0a621` revised in place (branch unmerged, `data/` gitignored, no released
  schema to preserve).

### Tests performed

- `uv run pytest` - **29 passed** (was 2).
- **Mutation check:** with the `foreign_keys` pragma temporarily removed, both orphan tests
  fail with "DID NOT RAISE IntegrityError" and pass again once restored. The tests exercise the
  protection rather than decorating it.
- **Migration verified against a scratch database:** INTEGER money columns, zero float columns
  remaining, 4 indexes, 5 CHECK constraints.

### Known issues

1. **`apps/backend/data/app.db` still holds the OLD schema.** DB Browser had the file open, so
   the delete failed and Alembic - seeing the version already at head - did nothing. Close DB
   Browser, delete `data/app.db`, re-run `uv run alembic upgrade head`. The migration itself is
   already proven correct on a scratch DB; this is the dev file only.
2. **Ruff is not installed.** `CLAUDE.md` sections 17 and 24 both call for `ruff check` and
   `ruff format --check`, but ruff is absent from `pyproject.toml` and `uv run ruff` fails with
   "program not found". The repo's stated conventions do not match its tooling. Either add it
   as a dev dependency or amend those sections - not done here, since adding a dependency
   unprompted is out of scope for this task (CLAUDE.md section 11).
3. **`requirements.md` is behind the code.** It does not state the storage unit and does not
   enumerate `extraction_status` or `validation_result`. Both are decided now. Updating a spec
   file needs explicit approval, so it was not touched.

### Carried into build-plan #5

- `statement_jobs` rows must be **retained**, not pruned on completion, or failure history and
  the "117 of 120" coverage figure disappear.
- `source_filename` belongs on `statement_jobs` (REQ-REV-003 needs it for the re-upload
  prompt), not on `Statement`.

### Recommended next step

Close DB Browser and rebuild the local database (issue 1), then decide on ruff (issue 2) and
whether to update `requirements.md` (issue 3). After that, build-plan #3 - intake and
validation endpoint.
