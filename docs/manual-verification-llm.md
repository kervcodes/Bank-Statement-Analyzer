# Manual verification guide — build-plan #8 Part 2 (Privacy Gateway + LLM)

A runbook to check the LLM layer. Work top to bottom.

**Scope of Part 2:** one Privacy Gateway that is the only place an outbound LLM payload is
built (allowlist of `merchant` / `description` / `amount` / `direction`, description sanitized,
fail-closed); an OpenAI + Anthropic provider abstraction (provider and model configured
separately, fallback only on provider failure); LLM-assisted categorization for merchants the
rules miss; `GET /analytics/explanation`.

**NOT in scope:** the Electron `safeStorage` keychain and the Settings screen "test connection"
button (build-plan #9). Part 2 reads env vars only.

All commands run from `apps/backend/`. Shell is PowerShell; use `curl.exe`.

---

## 1. Automated suite — the real gate

```powershell
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

- [ ] `pytest` all pass, coverage ≥ 90%. **No test makes a real network call** — every
      provider test uses `httpx.MockTransport`.
- [ ] `test_privacy_gateway.py`, `test_llm_providers.py`, `test_llm_gateway.py` ran and passed.
- [ ] `test_llm_gateway.py::test_account_number_and_name_never_reach_the_provider` passed —
      that is the build-plan's required leak test.
- [ ] `test_llm_gateway.py::test_only_the_gateway_imports_app_llm` passed — the import
      boundary holds.

---

## 2. Works with NO key (REQ-LLM-102)

With no `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` set, start the backend and process a couple of
real statements (see `docs/manual-verification-santander.md` §2).

```powershell
curl.exe -s http://127.0.0.1:8420/analytics/explanation | ConvertFrom-Json
curl.exe -s http://127.0.0.1:8420/review/categorizations | ConvertFrom-Json | ConvertTo-Json -Depth 4
```

- [ ] `/analytics/explanation` → `{"provider": null, "model": null, "text": null}`, HTTP 200
      (never 500).
- [ ] Categorization still runs — recognizable merchants are categorized by the rules,
      unknowns are `Uncategorized` and show in `/review/categorizations`.
- [ ] Nothing in the backend logs mentions an LLM call.

---

## 3. Privacy boundary — capture what would be sent

Without a key, add a temporary print to see the sanitized payload the gateway builds. In a
Python REPL (`uv run python`):

```python
from app.services.privacy_gateway import build_categorization_payload
p = build_categorization_payload(
    merchant_normalized="Zelle",
    description_normalized="ZELLE TRANSFER TO JOHN DOE 877-000-1111 ACCT 4012888812345678 rent",
    amount_cents=120000,
    direction="DEBIT",
)
print(p.model_dump_json())
```

- [ ] Output is a JSON object with **exactly** `merchant`, `description`, `amount`,
      `direction` — nothing else.
- [ ] The account number, the phone number, and "JOHN DOE" are **not** in it (the P2P tail is
      dropped entirely).
- [ ] `build_categorization_payload(..., direction="REFUND")` raises `PrivacyBlockedError`
      (fail closed).

---

## 4. With a key — end to end (spends a few cents)

Set a key (real spend — a handful of small calls):

```powershell
$env:LLM_PROVIDER = "openai"
$env:OPENAI_API_KEY = "sk-..."
# $env:OPENAI_MODEL defaults to gpt-5.6-luna
```

Restart the backend. Process statements that contain merchants the built-in rules don't know
(a local restaurant, a regional utility, a niche subscription).

- [ ] Some previously-`Uncategorized` transactions now show `category_source: "LLM"` with a
      sensible category (check the DB as in `docs/manual-verification-categorization.md` §3).
- [ ] A merchant the LLM is unsure about (low confidence) stays `Uncategorized` /
      `category_source: NONE`, with `predicted_category` populated — it went to Review, the
      guess was kept.
- [ ] Watch the backend logs / network: the request body sent to the provider contains only
      the four allowlisted fields. No account numbers, names, or raw statement text.

```powershell
curl.exe -s http://127.0.0.1:8420/analytics/explanation | ConvertFrom-Json
```

- [ ] `provider: "openai"`, `model: "gpt-5.6-luna"`, `text` is a short plain-English summary
      that only references figures present in `GET /analytics`.

---

## 5. Fallback (provider failure only)

- [ ] Set `OPENAI_API_KEY` to a deliberately invalid value and set a valid `ANTHROPIC_API_KEY`.
      Reprocess an unknown-merchant statement → categorization still gets LLM suggestions
      (served by Anthropic; `category_source: "LLM"`), because an auth error is a provider
      failure.
- [ ] Set a *valid* `OPENAI_API_KEY` again. A low-confidence answer from OpenAI must **not**
      trigger an Anthropic call — confirm from logs that only one provider was hit per unknown
      merchant.

---

## 6. Sign-off checklist (maps to requirements.md)

- [ ] `uv run pytest` green ≥ 90%; `ruff` clean; no real network in the suite.
- [ ] Every LLM path goes through `app/services/llm_gateway.py`; no other module imports
      `app.llm.*` (REQ-LLM-001) — enforced by a test.
- [ ] The outbound payload is a 4-field allowlist built from primitives; account/routing/card
      numbers, names, addresses, phone, email, and `description_raw` never cross the boundary
      (REQ-LLM-002/003).
- [ ] The app is fully functional with no key — deterministic analytics, rule-based
      categorization, and the dashboard do not depend on the LLM (REQ-LLM-102).
- [ ] Provider and model are separate env vars; the fallback fires only on a provider failure.
- [ ] `GET /analytics/explanation` labels its provider and is never the source of a number
      (REQ-LLM-201).
