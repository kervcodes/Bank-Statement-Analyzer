# Manual verification guide — build-plan #8 Part 1 (categorization)

A runbook to check the application after rule-based categorization + merchant normalization is
implemented. Work top to bottom; every step says what to run and what a **pass** looks like.

**Scope of Part 1:** each transaction gets a `merchant_normalized` and a `category`, resolved
`USER → MERCHANT RULE → deterministic prediction (≥ 0.75) → Review`. The prediction is stored
separately and never destroyed. `GET /review/categorizations`, `PUT /transactions/{id}/category`,
and `PUT /category-rules` are the write paths. Analytics now groups on the normalized merchant
and excludes transfers/income from spending.

**NOT in scope yet** (Part 2 / later): the LLM fallback for unknown merchants, the Privacy
Gateway, the plain-English dashboard summary; any frontend screen; the Electron `safeStorage`
key handling. Categories will be mostly the deterministic ones plus a large `Uncategorized`
bucket until Part 2 and real use build up merchant rules.

All commands run from `apps/backend/`. Shell is PowerShell; use `curl.exe`.

---

## 1. Automated suite — the real gate

```powershell
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

- [ ] `pytest` — all pass, coverage ≥ 90%.
- [ ] These ran and passed: `test_merchant_normalization.py`, `test_categorization.py`,
      `test_transactions_api.py`, `test_category_rules_api.py`, and the new cases in
      `test_review_api.py` / `test_analytics.py`.
- [ ] `test_categorization.py::test_deleting_a_merchant_rule_restores_the_prediction` passed —
      that is the non-destructive invariant.

---

## 2. Migration

```powershell
uv run alembic upgrade head
```

- [ ] Ends at `208f30aad50f`. Re-running says nothing to do.
- [ ] `sqlite3 data/app.db ".schema transaction"` shows `merchant_normalized`,
      `predicted_category`, `predicted_confidence`, `predicted_source`, `user_category`,
      `category` (NOT NULL, default `'Uncategorized'`), `category_source`, and five new
      `ck_transaction_*` CHECK constraints. `category_rule` table exists.
- [ ] Any pre-existing transactions now have `category = 'Uncategorized'`, not NULL.

---

## 3. End to end — process real statements

Start the backend (`uv run uvicorn app.main:app --port 8420`), upload 2–3 real Santander
statements (see `docs/manual-verification-santander.md` §2), wait for the batches to finish.

```powershell
uv run python - <<'PY'
from collections import Counter
from sqlmodel import Session, select
from app.db import engine
from app.models import Transaction

with Session(engine) as s:
    txns = s.exec(select(Transaction)).all()
    print(f"{len(txns)} transactions")
    print("by category:", Counter(t.category for t in txns).most_common())
    print("by source  :", Counter(t.category_source for t in txns).most_common())
    for t in txns[:20]:
        print(f"  {t.transaction_date}  {t.direction:6} {t.amount_cents/100:>9.2f}  "
              f"{(t.merchant_normalized or '')[:22]:22}  {t.category:16} ({t.category_source})")
PY
```

- [ ] Every transaction has a non-empty `merchant_normalized` and a `category` (never NULL).
- [ ] `category_source` is one of `RULE` / `NONE` (no `USER` / `MERCHANT_RULE` / `LLM` yet).
- [ ] Recognizable merchants are sensible: a streaming service → `Subscriptions`, a gas
      station → `Fuel`, a grocery store → `Groceries`, payroll/deposits → `Income`.
- [ ] Spot-check 10 auto-assigned (`RULE`) transactions against the statement — the category
      should be **right**, not just plausible. A wrong auto-assignment is the highest-value
      bug here (the 0.75 gate exists to prevent exactly that).
- [ ] Things the rules genuinely don't know → `category = Uncategorized`,
      `category_source = NONE`. That is correct behaviour, not a failure.

---

## 4. The Review lane

```powershell
curl.exe -s http://127.0.0.1:8420/review/categorizations | ConvertFrom-Json | ConvertTo-Json -Depth 5
```

- [ ] Returns `groups`, one per unknown merchant, each with `transaction_count`, `total_cents`,
      an optional `suggested_category` (a sub-threshold guess), and a `sample_description`.
- [ ] Sorted by `total_cents` descending (biggest unknowns first).
- [ ] A confidently categorized merchant (e.g. Netflix) does **not** appear.
- [ ] `GET /batches/{id}` shows a matching `uncategorized_count`.

---

## 5. A per-transaction correction (transaction-scoped)

Pick an `Uncategorized` transaction id from step 3.

```powershell
curl.exe -s -X PUT "http://127.0.0.1:8420/transactions/PASTE-ID/category" `
  -H "Content-Type: application/json" -d '{\"category\":\"Groceries\"}' | ConvertFrom-Json
```

- [ ] Response: `category: "Groceries"`, `category_source: "USER"`, `predicted_category` still
      shows the original guess (not destroyed).
- [ ] **Another** transaction from the same merchant is **unchanged** — a plain edit is one row
      only.
- [ ] `GET /category-rules` is still empty.
- [ ] An unknown category name → HTTP 422. An unknown transaction id → HTTP 404.

---

## 6. A merchant-wide rule (retroactive + future)

```powershell
curl.exe -s -X PUT "http://127.0.0.1:8420/category-rules" `
  -H "Content-Type: application/json" -d '{\"merchant\":\"MERCHANT-NAME\",\"category\":\"Shopping\"}' | ConvertFrom-Json
```

- [ ] Response `transactions_recategorized` = the count of that merchant's transactions that
      had no hand override.
- [ ] Those transactions now show `category_source: "MERCHANT_RULE"`.
- [ ] A transaction you hand-corrected in step 5 is **not** touched by the rule.
- [ ] Upload a *new* statement with the same merchant → it picks up the rule automatically.
- [ ] `DELETE /category-rules/MERCHANT-NAME` → the rule's transactions revert to their stored
      prediction (`category_source` back to `RULE` or `NONE`), nothing left stale.

---

## 7. Analytics reflects categories and excludes transfers

```powershell
curl.exe -s http://127.0.0.1:8420/analytics | ConvertFrom-Json | ConvertTo-Json -Depth 6
```

- [ ] `spending_by_category` now has real buckets, not one `Uncategorized` lump (assuming some
      merchants were recognized).
- [ ] If any transaction is categorized `Transfers` or `Credit Card Payments`, its amount is
      **not** in `spending_by_category` and **not** in `merchant_totals`; it **is** in
      `cash_flow[].transfers_cents`.
- [ ] `cash_flow[].spending_cents` ≤ `cash_flow[].debits_cents` for every month.
- [ ] `merchant_totals` entries are normalized names ("Amazon", not "AMZN MKTP US*A1B2").

---

## 8. Sign-off checklist (maps to requirements.md)

- [ ] `uv run pytest` green ≥ 90%; `ruff` clean.
- [ ] Deterministic rule/merchant mapping runs before any LLM (REQ-CAT-001) — and there is no
      LLM yet, so categorization works fully without one.
- [ ] Merchant normalization happens before categorization; the two shapes of one merchant
      collapse (REQ-CAT-002).
- [ ] Below-threshold results are `Uncategorized` + Review, never a confident guess
      (REQ-CAT-003).
- [ ] A correction is stored and re-applied: per-transaction by default, merchant-wide on the
      explicit rule action; deleting the rule is non-destructive (REQ-CAT-004).
- [ ] Transfers and income never count as spending anywhere in analytics.
