# Todo: Canonical schema and local database

Source: `build-plan.md` #2, `techstack.md` §9 (canonical schema), `requirements.md` §6
(REQ-NORM-*) and §7 (REQ-ACC-*).

Goal for this task only: `Batch`, `Statement`, `Transaction`, `Account` as SQLModel classes,
Alembic wired up, a local SQLite database created from this schema. No API endpoints, no
validation/dedup/analytics logic — just the models, the migration, and round-trip tests.

Branch: `feature/canonical-schema` (stacked on `docs/verification-and-cleanup` → `feature/monorepo-skeleton` → `main`, since PRs #1/#2 are still open)

## Spec gaps found while reading — need your call before I write code

`techstack.md` §9 only fully defines `Transaction` and `Statement` fields; `Batch` and
`Account` aren't specified in any *current* doc. The old `architecture.md` (deleted in commit
`56d1f06`, superseded by `build-plan.md`/`requirements.md`/`techstack.md`) had a full ER
diagram including both. I'm proposing to carry its `Batch`/`Account` field lists forward since
nothing newer replaces them, plus two small reconciliations:

1. **`Transaction.statement_id` vs. `source_statement_id`** — `techstack.md` §9 names the
   field `statement_id`; `requirements.md` REQ-NORM-004 calls it `source_statement_id`. I read
   these as the same field described two ways (traceability languagevs. schema language), not
   two separate fields — there's no signal anywhere of a second, distinct provenance field.
   **Proposing:** name it `statement_id` (matches the literal schema definition in techstack.md,
   the doc build-plan #2 cites for the model itself).
2. **`extraction_confidence` nullable** — not marked optional in techstack.md's list, but the
   deleted `architecture.md` noted natively-extracted text (via `pdfplumber`) has no confidence
   source at all — only OCR produces one. This is a real technical constraint, not spec
   padding. **Proposing:** keep it nullable, matching that reasoning.
3. **Dropping old-ER fields not in the current docs** — `architecture.md` also had `currency`
   on `Statement` and `merchant_normalized`/`category_source`/`category_confidence` on
   `Transaction`. None of these are in `techstack.md` §9's current list, the app is US-only for
   v1 (no multi-currency need), and the categorization fields belong to build-plan #8, not #2.
   **Proposing:** leave all of these out now; Alembic makes adding them later a normal
   migration when #8 actually needs them, not a schema redesign.
4. **`Statement.account_id` / `Transaction.account_id` nullable** — per the processing flow
   (intake creates a `Statement` row before parsing; account identity is resolved during
   extraction/normalization, build-plan #3–#4), a `Statement` can exist before its account is
   known. **Proposing:** nullable FK now; tightened later if build-plan #3 shows it should
   always be set by the time a row exists.

If any of these calls seem wrong, say so before I implement — this is exactly the kind of
decision that's cheap to change now and annoying to migrate later.

## Proposed fields (pending the above)

- **Batch**: `id` (str/UUID, PK), `created_at` (datetime), `selected` (int), `uploaded` (int),
  `upload_failed` (int), `processed` (int), `processing_failed` (int), `status` (str —
  `PROCESSING` / `COMPLETED` / `COMPLETED_WITH_WARNINGS` / `FAILED`)
- **Account**: `id` (str/UUID, PK), `bank` (str), `account_type` (str),
  `account_identifier_masked` (str)
- **Statement**: `id` (str/UUID, PK), `batch_id` (FK → Batch), `account_id` (FK → Account,
  nullable), `bank` (str), `account_type` (str), `account_identifier_masked` (str),
  `statement_start_date` (date), `statement_end_date` (date), `opening_balance` (Decimal),
  `closing_balance` (Decimal), `parser_version` (str), `extraction_status` (str)
- **Transaction**: `id` (str/UUID, PK), `statement_id` (FK → Statement), `account_id` (FK →
  Account, nullable), `transaction_date` (date), `posted_date` (date), `description_raw` (str),
  `description_normalized` (str), `amount` (Decimal, positive), `direction` (str —
  `DEBIT`/`CREDIT`), `balance_after` (Decimal, optional), `category` (str, optional),
  `source_bank` (str), `extraction_confidence` (float, optional/nullable), `source_page` (int)

## Backend work

- [x] `uv add sqlmodel alembic`
- [x] `uv add --dev pytest`
- [x] `src/app/models/canonical.py` — the four SQLModel table classes above
- [x] `src/app/db.py` — engine/session setup, SQLite path at `apps/backend/data/app.db` (already
  covered by the repo's root `.gitignore` `data/` rule — never committed)
- [x] `uv run alembic init alembic`, wire `alembic/env.py` to `SQLModel.metadata` and the app's
  DB URL
- [x] `uv run alembic revision --autogenerate -m "create canonical schema"`, review the
  generated migration by hand before applying
- [x] (found during review) autogenerate emitted `sqlmodel.sql.sqltypes.AutoString()` without
  importing `sqlmodel` — a known gap in Alembic's default template with SQLModel. Fixed the
  generated migration directly and patched `alembic/script.py.mako` so future migrations don't
  hit the same `NameError`.
- [x] `uv run alembic upgrade head` — confirmed `data/app.db` created with all four tables
  (`account`, `batch`, `statement`, `transaction`) plus `alembic_version`
- [x] `tests/test_canonical_models.py` — in-memory SQLite engine (isolated from the dev DB),
  write and read back a `Statement` with related `Transaction` rows, assert the round-trip

## Out of scope for this task

- Any API endpoints
- Validation logic (build-plan #6), dedup (#7), analytics (#7), categorization (#8)
- `ValidationResult`/`AnalyticsResult` tables — not requested by build-plan #2, added when
  their consuming logic is actually built

## Review

**What was completed:** `Batch`, `Account`, `Statement`, `Transaction` SQLModel classes in
`src/app/models/canonical.py`, per the reconciled field lists above (approved: `statement_id`
naming, nullable `extraction_confidence`/`account_id`, old-ER fields not in current docs
dropped). Alembic wired up (`alembic/env.py` imports `SQLModel.metadata` and the app's DB URL
from `src/app/db.py`), one migration generated and applied, SQLite database created at
`apps/backend/data/app.db` (gitignored). Two round-trip tests in `tests/test_canonical_models.py`.

**Tests/checks run:**

- `uv run alembic revision --autogenerate -m "create canonical schema"` → detected all four
  tables correctly
- `uv run alembic upgrade head` → verified via `sqlite3`/Python that `account`, `batch`,
  `statement`, `transaction`, `alembic_version` all exist in `data/app.db`
- `uv run pytest -v` → 2 passed, no warnings

**Known issues:**

- Alembic's autogenerated migration referenced `sqlmodel.sql.sqltypes.AutoString()` without
  importing `sqlmodel` — would have raised `NameError` on `alembic upgrade`. Fixed in the
  generated file and in `alembic/script.py.mako` so it won't recur on future migrations.
- No API endpoints wire these models in yet (by design — out of scope for this task).

**Recommended next step:** build-plan.md #3 — intake and validation endpoint
(REQ-INT-001–006), which will be the first thing to actually create `Batch`/`Statement` rows
through the API rather than directly in tests.
