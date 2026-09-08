# Manual verification guide — build-plan #7 Part B (analytics engine)

A step-by-step runbook to check the application state after the analytics engine
(`build-plan.md` #7, Part B) is implemented. Work top to bottom. Every step says what to run
and what a **pass** looks like.

**Scope of Part B:** `GET /analytics?start=&end=` computes, deterministically over the
deduplicated + validated ledger, a single JSON payload: monthly cash flow, spending by
category, top merchants, recurring charges, month-over-month trends, and a coverage summary.
No new schema, no migration.

**Explicitly NOT in scope yet** (later steps — do not treat as bugs): rule-based categorization
and merchant normalization, the Privacy Gateway, any LLM summary (#8); every frontend screen
including the dashboard that will render this payload (#9); CSV/JSON ledger export
(REQ-RPT-102); click-through from a number to its transactions (REQ-RPT-101). Categories are
almost all `Uncategorized` and merchants are the lightly-cleaned description string — that is
expected until #8.

All commands run from `apps/backend/` unless noted. Shell is PowerShell on Windows; use
`curl.exe` (not `curl`).

---

## 1. Automated suite — the real gate

This is the primary check.

```powershell
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

- [ ] `pytest` — all pass, coverage ≥ 90%.
- [ ] `test_ledger.py` and `test_analytics.py` ran and passed.
- [ ] In `test_analytics.py`, `test_recurring_detects_monthly_with_drifting_amount` passed —
      that is the build-plan's explicit "slightly varying amount" case (`15.99 / 15.99 /
      16.49 / 16.49` → monthly recurring).
- [ ] `test_reuploaded_statement_does_not_double_analytics` passed — a re-uploaded statement is
      collapsed by dedup and analytics totals do not change.
- [ ] `ruff check` / `ruff format --check` clean.

---

## 2. Empty ledger — no 500

Start from a clean DB (`section 5` of `docs/manual-verification-santander.md`), then, with the
backend running:

```powershell
uv run uvicorn app.main:app --port 8420
# second terminal:
curl.exe -s http://127.0.0.1:8420/analytics | ConvertFrom-Json | ConvertTo-Json -Depth 5
```

- [ ] HTTP 200 (not 500).
- [ ] `cash_flow`, `spending_by_category`, `merchant_totals`, `recurring_charges` are all `[]`.
- [ ] `trends.current_period` is `null`, all `*_delta_cents` are `0`, all `*_ratio` are `null`.
- [ ] `coverage.transaction_count` is `0`, `coverage.excluded` is `[]`.

---

## 3. Real data — totals match the statements

Process 2–3 real consecutive Santander statements (see
`docs/manual-verification-santander.md` §2 for the upload + poll steps). Wait until every
batch is terminal, then:

```powershell
curl.exe -s http://127.0.0.1:8420/analytics | ConvertFrom-Json | ConvertTo-Json -Depth 6
```

Cross-check against the paper statements:

- [ ] `cash_flow` has one entry per calendar month covered, keyed `"YYYY-MM"`, oldest first.
- [ ] For one month, `credits_cents / 100` equals that statement's total deposits/credits, and
      `debits_cents / 100` equals its total withdrawals/debits. `net_cents == credits_cents -
      debits_cents`.
- [ ] `spending_by_category` — a single `"Uncategorized"` bucket whose `total_cents` equals the
      sum of all `debits_cents` across `cash_flow` (categorization is #8).
- [ ] `merchant_totals` — at most 10 entries, sorted by `total_cents` descending, debits only
      (no payroll / transfers-in). Each `merchant` is a recognizable description string.
- [ ] `coverage.statements_included` equals the number of statements you processed;
      `coverage.statements_excluded` is `0` if none failed or duplicated.
- [ ] `coverage.ledger_start` / `ledger_end` equal the earliest and latest transaction dates
      across everything you uploaded.

### 3a. Date window

```powershell
curl.exe -s "http://127.0.0.1:8420/analytics?start=2026-02-01&end=2026-02-28" | ConvertFrom-Json | ConvertTo-Json -Depth 6
```

- [ ] `cash_flow` now has only the February bucket.
- [ ] `coverage.ledger_start` / `ledger_end` fall inside the window.
- [ ] `curl.exe -s -o NUL -w "%{http_code}" "http://127.0.0.1:8420/analytics?start=nonsense"`
      prints `422`.

---

## 4. Recurring charges

Recurring detection needs ≥ 3 charges to the same description at a regular cadence. Real
statements may or may not contain a clean example (a streaming subscription, a gym, insurance).

- [ ] If your data has an obvious monthly subscription appearing 3+ times, it shows up in
      `recurring_charges` with `cadence: "monthly"`, `occurrences` ≥ 3, and a
      `typical_amount_cents` close to what you actually pay.
- [ ] A merchant you were charged by only once or twice does **not** appear.
- [ ] Irregular, variable-amount spending (groceries, gas at different stations) does **not**
      appear.

If nothing qualifies, that is a valid result — note it and rely on the automated
`test_analytics.py` recurring cases.

---

## 5. Deduplication does not double the numbers (the key integration check)

1. Process one real statement in its own batch. Record `analytics` → note `cash_flow` and
   `coverage.transaction_count`.
2. Upload the **same PDF again** in a new batch. Wait for it to finish.
3. `GET /analytics` again.

- [ ] `cash_flow` is **identical** to step 1 — the re-upload added nothing.
- [ ] `coverage.transaction_count` is unchanged.
- [ ] `coverage.statements_excluded` increased by 1, and `coverage.excluded` lists the second
      statement with `reason: "DUPLICATE"`.
- [ ] `GET /review/duplicates` still returns `{"possible_duplicates": []}` for an exact
      re-upload (nothing ambiguous).

---

## 6. Trends

With at least two months of data:

- [ ] `trends.current_period` is the most recent month with transactions; `previous_period` is
      the month before it.
- [ ] `spending_delta_cents == current month debits − previous month debits` (check against
      the `cash_flow` array).
- [ ] `spending_delta_ratio` is a string like `"0.1234"` or `"-0.0500"` (4 decimal places), or
      `null` if the previous month had zero debits.

---

## 7. Sign-off checklist (maps to requirements.md)

- [ ] `uv run pytest` green, coverage ≥ 90%; `ruff check` / `ruff format --check` clean.
- [ ] `GET /analytics` returns one structured JSON payload; every amount is an integer
      `*_cents`, every ratio a string. (REQ-ANLY-004)
- [ ] Cash flow, category totals, merchant totals, recurring charges, and trends are all
      computed by code — no LLM involved, works with no LLM key configured. (REQ-ANLY-001,
      REQ-LLM-102)
- [ ] Analytics reads only the deduplicated, validated ledger — a `FAILED` or `DUPLICATE`
      statement and a `DUPLICATE` transaction contribute nothing; a re-upload doesn't change
      any total. (REQ-ANLY-003, REQ-VAL-003)
- [ ] Recurring detection matches on merchant + cadence + a *similar* (not identical) amount.
      (REQ-ANLY-002)
- [ ] The coverage summary reports statements included vs excluded (with reason) and the real
      date range, alongside the totals. (REQ-RPT-001)
- [ ] Empty ledger → 200 with zeros/empty lists, never a 500.
