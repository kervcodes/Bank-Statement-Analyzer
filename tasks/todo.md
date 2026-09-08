# Todo: Build-plan #7 — Deduplication and the analytics engine

Source: `build-plan.md` §7, tracing to `requirements.md` §9 (REQ-DEDUP-001..004), §10
(REQ-ANLY-001..004), §13.1 (REQ-RPT-001..003), NFR-MAINT-002 (dedup confidence scoring is a
must-test area), `techstack.md` §10.

## Goal (what "done" means for this step)

1. When a batch finishes processing, its new statements are checked for duplicates —
   **statement-level first** (same PDF uploaded twice), then **transaction-level** for the
   partial-overlap case (a "last 90 days" statement overlapping three monthly ones). Three
   outcomes, never a silent delete (REQ-DEDUP-003/004): `UNIQUE`, `DUPLICATE` (auto-collapsed,
   excluded from the ledger), `POSSIBLE_DUPLICATE` (kept, flagged for Review).
2. A `GET /analytics` endpoint computes cash flow, spending by category, recurring charges,
   merchant totals, and period-over-period trends **deterministically** over the unified,
   deduplicated ledger (REQ-ANLY-001/003), plus a coverage summary (REQ-RPT-001), as one
   structured JSON payload (REQ-ANLY-004).

**Not in scope** (later steps): rule-based categorization + merchant normalization + the
Privacy Gateway + any LLM call (#8) — analytics here runs on `category` as it stands (mostly
`Uncategorized`) and groups recurring charges by `description_normalized`; the Review UI, the
Dashboard, and every other screen (#9); packaging (#10). No user-facing "merge / keep both"
action yet — this step produces the data those buttons will act on.

## State of the repo right now

- `main` is at build-plan #6 (PR #10 merged). The pipeline ends at per-statement financial
  validation; `Statement.validation_result` is `VALID` / `WARNING` / `FAILED`.
- `Transaction` has `category` (always `None` so far) and `description_normalized` (light
  whitespace cleanup only — real merchant normalization is #8).
- `workers/coordinator.py::refresh_batch` is called after every job transition and flips the
  batch to a terminal status once all jobs are terminal. It is idempotent.
- Money is integer cents everywhere; `Decimal` only at read time for ratios (`models/money.py`).
- No analytics or dedup code exists yet.

## Decisions to confirm before I write code

**1. Where dedup runs.** Inside `refresh_batch`, at the moment it transitions a batch from
`PROCESSING` to a terminal status (guarded so it runs **once** per batch). It dedups that
batch's new `VALID`/`WARNING` statements against the existing ledger. Rationale: dedup mutates
the ledger and only needs to happen when statements are added, not on every analytics read.

**2. Analytics is computed on demand**, not materialized. `GET /analytics` runs the whole
computation from the DB each call (optionally filtered by date range). For a single-user local
app with thousands of transactions this is fast enough and avoids a cache-invalidation
concern. Revisit if a real batch makes it slow.

**3. No `pandas`.** `techstack.md` §10 suggests it "for the aggregation-heavy parts". I
recommend **plain Python + `Decimal` + stdlib** (`itertools.groupby`, dict accumulation)
instead: it's arithmetic over a few thousand rows, and `pandas` (plus `numpy`) is a heavy
dependency to bundle into the PyInstaller binary in #10 for no measured benefit. Add it later
if aggregation ever becomes a measured bottleneck. Say if you'd rather stay on the spec.

**4. Statement-level duplicate = exact match** on `(account_id, statement_start_date,
statement_end_date, opening_balance_cents, closing_balance_cents)`. That is the same statement
period with the same reconciled endpoints — a re-upload. → `HIGH` confidence → the newer
statement becomes `DUPLICATE` of the older, **all its transactions** are marked `DUPLICATE`
too, and transaction-level dedup is skipped for it. This catches essentially every real case
("I uploaded March twice").

**5. Transaction-level dedup** runs only for statements **not** flagged as whole-statement
duplicates, and only compares transactions across **different statements of the same account
whose periods overlap**. Match key: `(transaction_date, amount_cents, direction,
description_normalized)`.
  - Exactly one match in an older statement, on a date inside the period overlap → `HIGH` →
    the newer transaction becomes `DUPLICATE`.
  - Several candidate matches (e.g. two identical charges in each statement) → **all kept**,
    the newer ones marked `POSSIBLE_DUPLICATE` (REQ-DEDUP-004: a missed duplicate is
    acceptable, a wrongly deleted real transaction is not). This is the design-notes §3.4
    "08/14 Starbucks $7.82 (statement A) / (statement B)" case.
  - No match → `UNIQUE`.
  Two identical same-day charges **within one statement** are never compared to each other —
  they are both real.

**6. Reconciliation is not re-checked after collapse.** A `DUPLICATE` transaction keeps its
row (for traceability, REQ-RPT-003) and its statement's `validation_result` is unchanged; it
is simply excluded from the ledger view analytics reads. The statement it duplicates already
reconciled on its own.

**7. New nullable `Transaction.reference_id`** column added now (the Santander parser doesn't
extract one yet; REQ-DEDUP-002 names it as a signal). Populated by a later parser change; the
dedup code uses it as a tie-breaker when present.

**8. The "unified deduplicated ledger"** that analytics reads = transactions where
`dedup_status != 'DUPLICATE'` **and** whose statement has `dedup_status != 'DUPLICATE'`
**and** `validation_result != 'FAILED'` (REQ-VAL-003). `WARNING` statements and
`POSSIBLE_DUPLICATE` transactions **are** included (kept-both).

**9. Analytics amounts are integer cents** in the JSON (`*_cents` fields), consistent with the
rest of the codebase; percentages / trend ratios are `Decimal`-computed and returned as
strings. The frontend (#9) formats for display; #8 will build the LLM its own sanitized shape.

## New / changed models (one migration)

- `Statement`: `dedup_status: str` (default `"UNIQUE"`, CHECK in `UNIQUE` / `DUPLICATE` /
  `POSSIBLE_DUPLICATE`), `duplicate_of_id: str | None` FK → `statement.id` (indexed).
- `Transaction`: `dedup_status: str` (same values + CHECK), `duplicate_of_id: str | None` FK →
  `transaction.id` (indexed), `reference_id: str | None`.
- `DEDUP_STATUSES` tuple in `models/canonical.py`, exported from `models/__init__.py`.

## Tasks

### Part A — Deduplication

#### A1. Model + migration
- [x] Add the columns/constraints above to `canonical.py`; export `DEDUP_STATUSES`.
- [x] `uv run alembic revision --autogenerate`; review (SQLite needs `batch_alter_table` for
      the new FKs/constraints — same as migration `69a3cd180f72`); `uv run alembic upgrade head`.

#### A2. Dedup service — `app/services/deduplication.py`
- [x] `dedup_statement(session, statement) -> DedupOutcome` — statement-level exact match
      (decision 4). If matched: set `dedup_status`/`duplicate_of_id` on the statement and all
      its transactions, return early.
- [x] `dedup_transactions(session, statement)` — transaction-level (decision 5), only for
      non-whole-duplicate statements. Pure DB reads + writes, no FastAPI imports.
- [x] `run_dedup_for_batch(session, batch_id)` — orchestrates: for each `VALID`/`WARNING`
      statement in the batch (oldest first), statement-level then transaction-level. Idempotent
      (safe to re-run: an already-classified statement is skipped).

#### A3. Hook into the coordinator
- [x] `refresh_batch`: when it transitions the batch `PROCESSING` → terminal, call
      `run_dedup_for_batch` before returning. Guard so it fires once.

#### A4. Read endpoint
- [x] `GET /batches/{id}` (extend): each statement gains `dedup_status`; add a top-level
      `possible_duplicate_count` for the batch.
- [x] `GET /review/duplicates` — the flagged `POSSIBLE_DUPLICATE` transactions grouped with
      what they match (feeds design-notes §3.4). Thin; no actions yet.

#### A5. Tests — `tests/test_deduplication.py` (NFR-MAINT-002)
- [x] Statement-level: upload the same synthetic statement in two batches → the second
      statement is `DUPLICATE`, `duplicate_of_id` points at the first, all its transactions
      `DUPLICATE`, ledger count unchanged.
- [x] Not a duplicate: a different month for the same account → both `UNIQUE`.
- [x] Transaction-level overlap: a statement covering a range that overlaps an existing one,
      sharing some transactions → the shared ones in the newer statement are `DUPLICATE`, the
      non-overlapping ones `UNIQUE`.
- [x] Ambiguous: two identical same-day charges in each of two overlapping statements → newer
      ones `POSSIBLE_DUPLICATE`, nothing deleted, all four rows still present.
- [x] Same-day identical charges within one statement are both `UNIQUE`.
- [x] `run_dedup_for_batch` is idempotent (second call is a no-op).
- [x] A `FAILED`-validation statement is skipped by dedup entirely.

### Part B — Analytics engine

**Branch:** `feature/analytics-engine` off updated `main` (PR #11 merged). No new migration —
Part B is read-only over the schema Part A shipped.

#### Decisions to confirm before I write Part B code

**B-a. No `pandas`** (restating decision 3 now that it's live): plain Python + `Decimal` +
stdlib. Say if you want the spec's `pandas` instead.

**B-b. Period = calendar month, keyed `"YYYY-MM"`.** `cash_flow` buckets by calendar month;
`trends` compares the latest month that has data against the one before it, within the filtered
ledger. No partial-month proration. Weekly/other periods are a later concern (`period=` arg
exists but only `"month"` is implemented).

**B-c. Recurring detection (REQ-ANLY-002).** Group debits by `description_normalized`
(casefolded). A group qualifies as recurring when: ≥ 3 occurrences; the median gap between
consecutive dates falls within tolerance of a known cadence — weekly (7d), biweekly (14d),
monthly (28–31d), annual (~365d), tolerance ±25% of the cadence; and every amount is within
±15% of the group's median amount. Output per match: `{merchant, cadence,
typical_amount_cents (median), occurrences, first_seen, last_seen}`. Groups that fail any test
are simply not reported (no "irregular" bucket).

**B-d. Response shape.** One `Analytics` Pydantic model, nested sub-models. Every money field
is integer `*_cents`. Every ratio/delta is `Decimal`-computed and serialized as a string
(e.g. `"-0.1250"`, 4 dp) alongside its absolute `*_cents` counterpart. `GET /analytics` takes
optional `start` / `end` as ISO `date` (inclusive); FastAPI rejects a malformed date as 422.

**B-e. Coverage summary (REQ-RPT-001).** Reports statements *included* vs *excluded* (each
excluded one with a reason: `FAILED` / `DUPLICATE`), the actual transaction-date span of the
ledger, and the live transaction count. "Expected vs processed" (the user saying "I expect 12
months") is a Dashboard/#9 concern — not invented here.

#### B1. Ledger query — `app/services/ledger.py`
- [x] `ledger_transactions(session, *, start=None, end=None) -> list[Transaction]` — the
      unified deduplicated ledger (decision 8), optional date filter on `transaction_date`.
- [x] `coverage_summary(session, *, start=None, end=None) -> Coverage` — statements included vs
      excluded (with reason: `FAILED` / `DUPLICATE`), date range actually covered, counts
      (REQ-RPT-001).

#### B2. Analytics — `app/services/analytics.py`
- [x] `cash_flow(txns, *, period="month")` — per-period credits / debits / net, in cents.
- [x] `spending_by_category(txns)` — debit totals grouped by `category` (`None` →
      `"Uncategorized"`).
- [x] `merchant_totals(txns, *, limit=10)` — top debit merchants by total, grouped on
      `description_normalized`.
- [x] `recurring_charges(txns)` — group debits by `description_normalized`; for groups of ≥ 3,
      detect a regular cadence (weekly / biweekly / monthly / annual, within a tolerance) and a
      similar amount (within a small % band, REQ-ANLY-002); return
      `{merchant, cadence, typical_amount_cents, occurrences, first_seen, last_seen}`.
- [x] `trends(txns)` — current period vs previous: spending and net cash-flow deltas, as
      `Decimal` ratios rendered to strings.
- [x] `build_analytics(session, *, start, end) -> Analytics` — assembles all of the above plus
      `coverage`. Pure functions; `Decimal` for every ratio, integer cents for every amount;
      never calls anything in `app/parsers` or an LLM.

#### B3. Endpoint
- [x] `GET /analytics?start=&end=` → the `Analytics` Pydantic model. `main.py` wires the router.
- [x] Works with an empty ledger (returns zeros / empty lists, `coverage` reflecting nothing
      processed) — no 500.

#### B4. Tests — `tests/test_analytics.py`, `tests/test_ledger.py`
- [x] Ledger excludes `DUPLICATE` transactions, `DUPLICATE` statements, and `FAILED`
      statements; includes `WARNING` and `POSSIBLE_DUPLICATE`.
- [x] Cash flow / merchant totals / spending-by-category on a hand-built set of transactions →
      exact expected cents.
- [x] Recurring: monthly charges to "NETFLIX" at `15.99, 15.99, 16.49, 16.49` → detected as
      monthly recurring with a typical amount (build-plan #7 explicitly asks for the
      slightly-varying-amount case).
- [x] Recurring: 3 charges to one merchant at random intervals → **not** flagged recurring
      (plus: unstable amount, and a repeated date → also not flagged).
- [x] Trends: two periods with known totals → correct delta strings.
- [x] `coverage_summary` lists an excluded `FAILED` statement with its reason.
- [x] `GET /analytics` end to end via `TestClient` on a small seeded ledger; empty-ledger case;
      bad-date → 422.

### C. Checks & docs
- [x] `uv run pytest` (coverage gate ≥ 90 — **128 passed, 96%**), `uv run ruff check .`,
      `uv run ruff format --check .` all clean.
- [x] Two batches where batch 2 re-uploads a statement from batch 1 → `GET /analytics` totals
      identical to batch 1 alone; `GET /review/duplicates` empty for an exact re-upload —
      covered by `test_reuploaded_statement_does_not_double_analytics`. Live-server run still
      pending (dev DB locked by DB Browser, same as Part A).
- [x] `docs/activity.md` entry (append); `README.md` Status / Next up (→ #8).
- [x] `docs/manual-verification-analytics.md` — step-by-step manual verification runbook.
- [x] `tasks/todo.md` Review section (below).

## Review

### Part A — Deduplication (this PR)

**Completed:** model + migration `6518b8bf3cfe`, `app/services/deduplication.py`, the
`refresh_batch` hook, `GET /batches/{id}` additions, the new `GET /review/duplicates`
(`app/api/review.py`), and `APP_DATABASE_URL` in `app/db.py`.

**Deviations from the plan:**
- **`Statement.created_at` added too** — `Statement` had no timestamp, and dedup needs to pick
  the *older* statement as canonical. Folded into the same migration.
- **Migration disables SQLite FK enforcement around the batch rebuild** (`PRAGMA
  foreign_keys=OFF`). `batch_alter_table` rebuilds `statement` / `transaction`, and the
  `DROP TABLE` step trips FK enforcement when the db has rows. Tested on a fresh db and a
  seeded one. `alembic/env.py` was tried as the place for this but the PRAGMA there silently
  makes `batch_alter_table` a no-op — reverted, done in the migration instead.
- **`dedup_statement` returns `None`, not a `DedupOutcome` dataclass** — the plan named a
  return type that nothing consumed; the functions mutate rows and `run_dedup_for_batch`
  orchestrates. Simpler.
- **No user-facing merge/keep action** and dedup **does not change batch status** — a
  re-uploaded duplicate is expected, not a warning.

**Tests:** `uv run pytest` — **105 passed, 96% coverage** (gate 90). `ruff` clean. New:
`test_deduplication.py` (7), `test_review_api.py` (2), one `test_batches_api.py` two-batch
worker-path case.

**Known / follow-ups:**
- Live-server manual E2E for dedup not run — dev `data/app.db` is locked by an open DB
  Browser. The two-batch worker test covers the same path.
- The `min(created_at, id)` canonical-picker only matters when several existing statements
  match at once (rare); for a plain re-upload the one prior statement is unambiguous.

### Part B — Analytics engine (this PR, branch `feature/analytics-engine` off updated main)

**Completed:** `app/services/ledger.py` (`ledger_transactions` + `coverage_summary`),
`app/services/analytics.py` (six pure functions + `build_analytics`), `app/api/analytics.py`
(`GET /analytics?start=&end=`), wired in `main.py`. `tests/test_ledger.py` (7) and
`tests/test_analytics.py` (21). No migration — Part B is read-only over Part A's schema.

**Key design points:**
- **The ledger is defined once**, in `ledger.py`: row not `DUPLICATE`, statement not
  `DUPLICATE`, statement validated `VALID`/`WARNING`. Everything in `analytics.py` takes the
  resulting `list[Transaction]` — it never re-queries.
- **No `pandas`** (decision B-a, confirmed) — `defaultdict` accumulation + `statistics` +
  `Decimal`.
- **Periods are calendar months** (`"YYYY-MM"`); `trends` = latest month with data vs the one
  before. `cash_flow`'s `period=` arg raises on anything but `"month"`.
- **Recurring:** ≥ 3 same-description debits, median inter-charge gap within ±25% of a known
  cadence (7 / 14 / 30 / 365 d), all amounts within ±15% of the median amount. Non-qualifying
  groups are omitted entirely.
- **Money stays integer cents; ratios are 4-dp strings** (`"0.2500"`), `None` when the base
  is zero.

**Deviations from the plan:** none of substance.
- `_amounts_are_stable` needed no zero-median special case — a zero median gives a zero
  tolerance band, which already admits only exact-zero amounts.
- Added `first_seen` to `RecurringCharge` alongside the planned `last_seen` (both are cheap and
  the dashboard will want the span).
- The planned "manual: two batches, re-upload doesn't double" check is implemented as a test
  (`test_reuploaded_statement_does_not_double_analytics`) rather than left as a live-only step.

**Tests:** `uv run pytest` — **128 passed, 96% coverage** (gate 90). `ruff check` /
`ruff format --check` clean. `ledger.py` and `analytics.py` at ~100% line coverage.

**Known / follow-ups:**
- Live-server manual E2E not run — dev `data/app.db` still locked by DB Browser (same
  constraint as Part A). `docs/manual-verification-analytics.md` is the runbook for when it's
  free; the automated DB + `TestClient` tests cover the same paths.
- `spending_by_category` and `merchant_totals` group on `description_normalized` /
  `category` as they stand today (~all `Uncategorized`, lightly-cleaned descriptions). Real
  categorization and merchant normalization are build-plan #8 and will improve these with no
  API change.
- Only monthly cash-flow buckets are implemented; weekly/quarterly is a later concern if a
  screen needs it.
