# Todo: Build-plan #8 — Categorization, Privacy Gateway, and the LLM layer

Source: `build-plan.md` §8 → `requirements.md` §11 (REQ-CAT-001..004), §12 (REQ-LLM-001..003,
101..103, 201), `techstack.md` §11–§12, `design-notes.md` §3.4 / §3.7.

## Goal

1. Every transaction gets a **normalized merchant** and a **category** resolved through a fixed
   hierarchy — user override → merchant rule → deterministic rules → LLM classifier → Review.
   Nothing modifies financial data on a weak guess.
2. A **Privacy Gateway** is the one chokepoint for anything sent to an LLM; no other module
   calls a provider client (REQ-LLM-001). It redacts PII and never sends `description_raw`.
3. A **provider abstraction** (Claude + OpenAI), provider and model configured **separately**.
   The app is fully functional with no key (REQ-LLM-102).

## LOCKED decisions (from the owner, this session)

| # | Decision | Lock |
|---|----------|------|
| 1 | Auto-assign threshold | **0.75** to start; a named constant, to be calibrated against labelled real transactions. Optimize **precision on auto-assigned**, not Review-avoidance. |
| 2 | Categories | **Fixed controlled taxonomy** (below). The LLM may never invent a category. |
| 3 | Every category has a **transaction type**: `income` / `expense` / `transfer`. Transfers and income never count as spending. |
| 4 | Category is **layered, non-destructive**: store `predicted_category` + `predicted_confidence` + `predicted_source`, `user_category` (per-txn), and a merchant rule (`CategoryRule`). Effective `category` is resolved from those. |
| 5 | A plain category edit is **transaction-only**. A **merchant-wide** rule is a separate explicit action ("always categorize [merchant] as X"). |
| 6 | **No bulk destructive overwrite.** Deleting a merchant rule restores the prediction — no Undo feature needed in v1. |
| 7 | Resolution order (invariant): `USER OVERRIDE → MERCHANT RULE → DETERMINISTIC RULES → LLM → (conf ≥ 0.75 ? assign : Review)` |
| 8 | Anthropic model | `claude-sonnet-5` |
| 9 | OpenAI model | `gpt-5.6-luna` to start |
| 10 | Model config | `LLM_PROVIDER` + `ANTHROPIC_MODEL` / `OPENAI_MODEL` — **provider and model never coupled in code** |
| 11 | Dev secrets | `.env`, backend/main-process only, renderer never sees a key. `safeStorage` is build-plan #9. |
| 12 | LLM payload | redacted, minimal transaction fields only (`{merchant, description, amount, direction}`) — never PDFs, account numbers, names, addresses. |

### v1 taxonomy (central module — `app/models/taxonomy.py`)

```
income    : Income
transfer  : Transfers, Credit Card Payments
expense   : Housing, Utilities, Groceries, Dining, Transportation, Fuel, Shopping,
            Entertainment, Subscriptions, Healthcare, Insurance, Education, Travel,
            Personal Care, Fees & Interest, Cash & ATM, Taxes, Debt Payments
(special) : Uncategorized
```

`Uncategorized` has no transaction type. **Spending** = debits whose category type is
`expense` **or** is `Uncategorized` (an un-triaged debit is more honestly counted as spend than
hidden). Income and transfer categories are never spending.

## Split into two PRs (like #7)

- **Part 1 — merchant normalization + deterministic categorization + the layered resolution +
  Review lane.** No network, no new dependency. Stands alone (REQ-LLM-102).
- **Part 2 — Privacy Gateway + `LLMProvider` (Claude/OpenAI) + LLM-assisted classification +
  dashboard explanation.** Adds `httpx` as a runtime dep. Includes the build-plan leak test.

## State of the repo

- Branch `feature/categorization-privacy-llm` off `feature/analytics-engine` (PR #12, **not yet
  merged** — stacked; #12 merges first).
- `Transaction.category` exists (always `None`). `description_normalized` = parser whitespace
  cleanup only. Pipeline: `processor.process_job` → extract/detect/parse/`normalize`/
  `validate_statement`/`mark_completed`, then `run_dedup_for_batch` on batch completion.
- Analytics (Part B base): `spending_by_category` groups on `category`; `merchant_totals` /
  `recurring_charges` on `description_normalized`.
- Money is integer cents. `httpx` is dev-only today.

## The layered model (Part 1)

`Transaction` gains:
- `merchant_normalized: str | None` (indexed)
- `predicted_category: str | None` — deterministic-rule or (Part 2) LLM output
- `predicted_confidence: float | None`
- `predicted_source: str | None` — CHECK `RULE` / `LLM` / `NONE`
- `user_category: str | None` — CHECK in `CATEGORIES`; a per-transaction override
- `category: str` (default `"Uncategorized"`) — **materialized effective category**, CHECK in
  `CATEGORIES`
- `category_source: str` (default `"NONE"`) — CHECK `USER` / `MERCHANT_RULE` / `RULE` / `LLM` /
  `NONE`; how `category` was decided (drives the Review lane)

New `CategoryRule`: `id`, `merchant` (unique, indexed), `category` (CHECK in `CATEGORIES`),
`created_at`. Only ever user-created.

`resolve_category(session, txn)` (the invariant, decision 7):
1. `txn.user_category` set → `category` = it, `category_source = "USER"`.
2. else a `CategoryRule` for `txn.merchant_normalized` → `category` = rule.category,
   `category_source = "MERCHANT_RULE"`.
3. else `predicted_confidence >= THRESHOLD` → `category` = `predicted_category`,
   `category_source = predicted_source`.
4. else → `category = "Uncategorized"`, `category_source = "NONE"` → shows in Review.

Recompute points: the categorize pass on a new statement; `PUT /transactions/{id}/category`;
`POST` / `DELETE` of a `CategoryRule`.

## Tasks

### Part 1 — Merchant normalization + deterministic categorization

#### P1-1. Taxonomy + model + migration  ✅
- [x] `app/models/taxonomy.py` — `CATEGORIES` (22, ordered), `CATEGORY_TYPE`, `TRANSACTION_TYPES`,
      `category_type`, `is_spending_category`, `category_in_sql`. Re-exported from
      `app/models/__init__.py`.
- [x] `Transaction`: `merchant_normalized` (idx), `predicted_category`, `predicted_confidence`,
      `predicted_source`, `user_category`, `category` (now NOT NULL, default `Uncategorized`),
      `category_source` + 5 CHECKs. `CategoryRule` in `app/models/categorization.py`;
      `CATEGORY_SOURCES` / `PREDICTED_SOURCES` in `canonical.py`.
- [x] Migration `208f30aad50f` — hand-written `batch_alter_table` (backfills NULL `category`
      first, PRAGMA FK off around the rebuild). Verified: fresh up/down/up, and a seeded db
      (2 txns preserved, `category` → `Uncategorized`, integrity + FK checks clean, CHECK fires).

#### P1-2. Merchant normalization — `app/services/merchant_normalization.py`
- [ ] `normalize_merchant(description_normalized) -> str` — pure. Uppercase; strip processor
      prefixes (`SQ *`, `TST* `, `PP*`, `PAYPAL *`, `POS `, `ACH `, `DEBIT CARD PURCHASE`),
      trailing store #s / city+state / dates / ref numbers; map via `MERCHANT_ALIASES`.
- [ ] `tests/test_merchant_normalization.py` — `"UBER *TRIP …"` & `"UBER TECHNOLOGIES"` →
      `"Uber"` (REQ-CAT-002); real-shaped Santander descriptions; unknown merchant → cleaned
      but recognizable.

#### P1-3. Deterministic categorization — `app/services/categorization.py` + `categorization_rules.py`
- [ ] `categorization_rules.py` — `MERCHANT_ALIASES`, `MERCHANT_CATEGORY` (exact merchant →
      category, `RULE_CONFIDENCE_MERCHANT ≈ 0.97`), `KEYWORD_CATEGORY` (token → category,
      `RULE_CONFIDENCE_KEYWORD ≈ 0.80`), credit-side rules. Confidences are named constants
      with a "calibrate against real data" comment.
- [ ] `predict_category(merchant, direction) -> Prediction(category, confidence, source)` —
      deterministic only (LLM hook is Part 2, inserted between keyword rules and the `NONE`
      fallback).
- [ ] `resolve_category(session, txn) -> None` — the decision-7 invariant; writes `category` +
      `category_source`.
- [ ] `categorize_statement(session, statement) -> None` — for each txn: `merchant_normalized`
      = normalize; `predicted_*` = predict; then `resolve_category`. Skips a txn whose
      `user_category` is already set. Idempotent.
- [ ] `tests/test_categorization.py` — merchant-map hit ≥ threshold assigns; keyword hit;
      unknown → `Uncategorized`/`NONE`; a merchant rule beats prediction but loses to
      `user_category`; deleting the rule restores the prediction; `categorize_statement`
      idempotent; a transfer-type category is excluded from spending.

#### P1-4. Pipeline hook
- [ ] `processor.process_job`: `categorize_statement` after `validate_statement`, before
      `mark_completed`. Worker test: a produced statement's transactions come out with
      `merchant_normalized` + a resolved `category`.

#### P1-5. Review lane + correction endpoints
- [ ] `GET /review/categorizations` — txns with `category_source == "NONE"`, grouped by
      `merchant_normalized`, count + sample + the (sub-threshold) `predicted_category`.
- [ ] `app/api/transactions.py` (new) — `PUT /transactions/{id}/category {category}`:
      validate ∈ `CATEGORIES`; set `user_category`; `resolve_category`; return the txn. **This
      one transaction only.**
- [ ] `app/api/category_rules.py` (new) — `GET /category-rules`; `PUT /category-rules
      {merchant, category}` (upsert, then `resolve_category` for every txn of that merchant
      with no `user_category`); `DELETE /category-rules/{merchant}` (delete, then re-resolve —
      predictions restored). Each returns the affected-row count.
- [ ] `GET /batches/{id}`: add `uncategorized_count`.
- [ ] `tests/test_transactions_api.py`, `tests/test_category_rules_api.py` — txn edit is
      isolated; a rule flips only non-user siblings; deleting a rule reverts them; unknown
      category → 422; bad id → 404.

#### P1-6. Analytics on merchant + transaction type
- [ ] `analytics.py`: group `merchant_totals` / `recurring_charges` on `merchant_normalized or
      description_normalized`. `spending_by_category` and the "spending" side of `trends` count
      only spending categories (decision 3 / taxonomy helper). `cash_flow` stays literal
      credits/debits but gains a `transfers_cents` line so a checking↔savings transfer is
      visible, not hidden.
- [ ] Update `test_analytics.py`; add: two raw descriptions for one merchant now aggregate;
      a `Transfers` debit is **not** in `spending_by_category`.

#### P1-7. Part 1 checks & docs
- [ ] `uv run pytest` (≥ 90), `ruff check`, `ruff format --check`.
- [ ] `docs/activity.md`; `README.md` Status; `docs/manual-verification-categorization.md`.
- [ ] `tasks/todo.md` Part 1 Review.

### Part 2 — Privacy Gateway + LLM

> Load the `claude-api` skill before writing any Anthropic client code.

#### P2-1. Privacy Gateway — `app/services/privacy_gateway.py`
- [ ] `sanitize_text(s) -> str` — redact digit runs ≥ 6, card 13–19 digit groups, SSN, email,
      phone, `ZELLE|VENMO|PAYPAL TO/FROM <name>` tails. Conservative.
- [ ] `build_categorization_payload(merchant, description_normalized, amount_cents, direction)`
      and `build_explanation_payload(analytics)` — small dicts, every string through
      `sanitize_text`, **`description_raw` never a field**.
- [ ] `tests/test_privacy_gateway.py` — account/routing/card/SSN/email/phone/`VENMO <name>`
      redacted; merchant survives; payloads never carry `description_raw`.

#### P2-2. Provider abstraction — `app/llm/`
- [ ] `base.py` — `LLMProvider` protocol (`categorize`, `explain`), `CategorySuggestion`,
      `LLMUnavailable`. `null.py` — `NullProvider`. `anthropic.py` / `openai.py` — `httpx`,
      **model passed in, not hard-coded**, timeouts, any error → `LLMUnavailable`.
- [ ] `uv add httpx` (promote to runtime); commit note.
- [ ] `get_provider()` — `LLM_PROVIDER` + `{ANTHROPIC,OPENAI}_MODEL` + key from env; no key →
      `NullProvider`.
- [ ] `tests/test_llm_providers.py` — `NullProvider`; the two clients via a monkeypatched
      `httpx` transport (no network); missing key → `NullProvider`.

#### P2-3. The single gateway — `app/services/llm_gateway.py`
- [ ] `suggest_category(merchant, description_normalized, amount_cents, direction)` and
      `explain_analytics(analytics)` — payload → `privacy_gateway` → `get_provider()`. The only
      module that touches both a payload and a provider.
- [ ] `tests/test_llm_gateway.py` — **the build-plan leak test**: a merchant/description
      carrying an account number and a full name; assert the string handed to the
      (monkeypatched) provider contains neither. Assert nothing outside `app/llm/` +
      `llm_gateway.py` imports `app.llm.*`.

#### P2-4. Wire the LLM in
- [ ] `predict_category`: after keyword rules and before `NONE`, if a provider is configured
      call `llm_gateway.suggest_category`; result becomes `predicted_*` with
      `predicted_source = "LLM"` (still subject to the 0.75 gate in `resolve_category`).
      Deterministic path byte-identical when no provider.
- [ ] `GET /analytics/explanation` — `build_analytics` → `llm_gateway.explain_analytics` →
      `{provider, model, text}` or `{provider: null, text: null}` (REQ-LLM-201).
- [ ] Tests: assisted path with a fake provider; no-provider path identical to Part 1;
      endpoint with and without a provider.

#### P2-5. Part 2 checks & docs
- [ ] `pytest` (≥ 90), `ruff`, format.
- [ ] `docs/activity.md`; `README.md` Status / Next up (→ #9); extend the manual-verification
      doc (sanitizer + provider + "works with no key").
- [ ] `tasks/todo.md` Part 2 Review.

## Review

### Part 1 — _(filled in when Part 1 is done)_

### Part 2 — _(filled in when Part 2 is done)_
