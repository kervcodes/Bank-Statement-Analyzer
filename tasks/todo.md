# Todo: Build-plan #8 Part 2 — Privacy Gateway + LLM layer

Branch `feature/privacy-llm-gateway` off `feature/categorization-privacy-llm` (Part 1, PR #13).
Rebase onto `main` once #13 merges. Source: `build-plan.md` §8, `requirements.md` §12
(REQ-LLM-001..003, 101..103, 201), `techstack.md` §11–§12.

> **Load the `claude-api` skill before writing the Anthropic client.**

## Goal

1. A **Privacy Gateway** (`app/services/privacy_gateway.py`) is the *only* place a payload is
   built for an LLM and the *only* place PII is stripped. No other module imports a provider
   client (REQ-LLM-001).
2. A **provider abstraction** (`app/llm/`) with an OpenAI and an Anthropic client, **provider
   and model configured separately** by env var. The app is byte-identical to Part 1 when no
   key is set (REQ-LLM-102).
3. **LLM-assisted categorization** fills the gap the deterministic rules leave: a merchant the
   rules don't know gets one LLM classification, still subject to the 0.75 gate.
4. **`GET /analytics/explanation`** — a plain-English summary of the analytics payload, clearly
   labelled with its provider (REQ-LLM-201). Never the source of a number.

## LOCKED decisions (owner, this session)

| # | Decision |
|---|----------|
| 1 | **OpenAI is primary**: `OPENAI_MODEL=gpt-5.6-luna`. Fallback: `ANTHROPIC_MODEL=claude-sonnet-5`. |
| 2 | Fallback fires **only on provider failure** — timeout, rate limit, HTTP/API error, unparseable response. |
| 3 | **Never** call the fallback because the primary returned low confidence. A low-confidence LLM result → Review, exactly like any sub-0.75 prediction. |
| 4 | Provider and model are separate env vars: `LLM_PROVIDER` (`openai`\|`anthropic`, default `openai`), `OPENAI_MODEL`, `ANTHROPIC_MODEL`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`. |
| 5 | The payload to a provider is the **minimum redacted fields for classification** — `{merchant, description, amount, direction}`-shaped. Never raw statements, `description_raw`, names, account/routing numbers, addresses, phone, email. |
| 6 | Dev secrets: `.env`, backend process only. `safeStorage` + the Settings screen are build-plan #9 — Part 2 reads env vars and notes the handoff. |

## Part 1 invariants to PRESERVE (do not redesign unless Part 2 exposes a real bug)

- Resolution order: `USER OVERRIDE → MERCHANT RULE → prediction ≥ 0.75 → Review`.
- `predicted_*` stays separate from `user_category`; predictions are never discarded.
- Merchant rules are non-destructive (delete restores the prediction).
- Transfers and income never count as spending; `Uncategorized` debits do.
- Merchant normalization runs **locally, before** anything crosses the network.

## Tasks

### P2-1. Privacy Gateway — `app/services/privacy_gateway.py`  (pure, no network)  ✅
Locked (owner): allowlist type not scrub; never serialize a `Transaction`; `merchant` from
`merchant_normalized`; sanitize `description` before construction; **fail closed** →
`PrivacyBlockedError` → no LLM → Review; no raw content ever an LLM arg; no logging of raw/
pre-sanitized content; tests prove the serialized payload has no forbidden fields / seeded PII
using adversarial examples.
- [x] `OutboundTransaction` — a frozen, `extra="forbid"` Pydantic model with exactly
      `merchant` / `description` / `amount` / `direction`. `OutboundAnalytics` similarly for
      the explanation path (aggregates only — no statement ids, bank names, or account ids).
- [x] `sanitize_text` — SSN, email, spaced-card (13–19), phone, digit-run ≥ 7, a P2P line
      (`ZELLE|VENMO|CASHAPP|PAYPAL|…` → whole tail dropped), `TRANSFER/WIRE/PYMT/… TO|FROM
      <Name>` name tail.
- [x] `build_categorization_payload(*, merchant_normalized, description_normalized,
      amount_cents, direction)` — four primitives in, `OutboundTransaction` out. Raises
      `PrivacyBlockedError` on a bad direction, a non-int amount, a residual-PII scan hit
      (defense in depth), or nothing left to classify.
- [x] `build_explanation_payload(analytics)` — `OutboundAnalytics`; every merchant through
      `sanitize_text`; ids/bank/account dropped.
- [x] `tests/test_privacy_gateway.py` (23) — adversarial `ZELLE TO JOHN DOE`, card/account/
      routing numbers, phone, email, SSN, names in transfer descriptions all gone from the
      **serialized** payload; ordinary merchants survive; every fail-closed path; the
      allowlist rejects an extra field. **188 passed, privacy_gateway.py 100% coverage.**

### P2-2. Provider abstraction — `app/llm/`
- [ ] `base.py` — `LLMProvider` Protocol: `categorize(payload: dict) -> CategorySuggestion | None`,
      `explain(payload: dict) -> str | None`; `CategorySuggestion(category: str, confidence:
      float)`; `LLMUnavailable(Exception)`; a `name` / `model` attribute for labelling.
- [ ] `null.py` — `NullProvider`: both methods return `None`. Used when no key is configured.
- [ ] `openai.py` — `OpenAIProvider(api_key, model, *, timeout=20, client=None)`. `httpx` POST
      to the chat/completions endpoint; system prompt pins the output to a JSON object
      `{"category": <one of CATEGORIES>, "confidence": 0..1}` and forbids inventing a category;
      parse + validate against `CATEGORIES` (unknown → treat as no suggestion). Any
      non-2xx / network error / bad JSON → `raise LLMUnavailable`. `client` injectable for
      tests (an `httpx.Client` with a `MockTransport`).
- [ ] `anthropic.py` — `AnthropicProvider(...)`, same contract, `/v1/messages`, `x-api-key` +
      `anthropic-version` headers (confirm via the `claude-api` skill).
- [ ] `providers.py` — `configured_providers() -> list[LLMProvider]`: read env; the one named
      by `LLM_PROVIDER` first, the other second, each included only if its key is present;
      empty list → caller falls back to `NullProvider`.
- [ ] `uv add httpx` (promote from dev to runtime). `.env.example` updated with the five vars.
- [ ] `tests/test_llm_providers.py` — `NullProvider` returns `None`; `OpenAIProvider` /
      `AnthropicProvider` parse a good mocked response, and turn a 500 / a timeout / malformed
      JSON into `LLMUnavailable`; `configured_providers()` ordering for each `LLM_PROVIDER`
      value and with keys missing.

### P2-3. The single gateway — `app/services/llm_gateway.py`
- [ ] `suggest_category(*, merchant, description_normalized, amount_cents, direction) ->
      CategorySuggestion | None` — build payload via `privacy_gateway`, then try each provider
      in order: return the first **successful** result; on `LLMUnavailable` move to the next
      (decision 2); a *successful low-confidence* result is returned as-is, **not** retried on
      the fallback (decision 3). No providers / all failed → `None`.
- [ ] `explain_analytics(analytics) -> ExplanationResult` — `{provider: str | None, model: str
      | None, text: str | None}`. Same provider-failure fallback; no provider → all `None`.
- [ ] `tests/test_llm_gateway.py`:
      - **The build-plan leak test** — a transaction whose `description_normalized` carries a
        full account number and a person's name; run through `suggest_category` with a fake
        provider that records the payload; assert the recorded payload contains **neither** the
        account number nor the name, and no `description_raw`.
      - Fallback on primary `LLMUnavailable`; **no** fallback when the primary returns a
        low-confidence suggestion.
      - Import-boundary test: nothing outside `app/llm/` and `app/services/llm_gateway.py`
        imports `app.llm.*` (walk the source tree).

### P2-4. Wire the LLM into categorization + a new endpoint
- [ ] `categorization.py`: replace the `_llm_prediction` stub. `categorize_statement` gains a
      second phase — collect the **unique** `(merchant, direction)` of transactions whose
      deterministic `predicted_source == "NONE"` and `user_category is None`; call
      `llm_gateway.suggest_category` **once per unique merchant**; a valid suggestion sets
      `predicted_category` / `predicted_confidence` / `predicted_source = "LLM"` on every
      matching transaction; then `resolve_category` as before (the 0.75 gate is unchanged).
      `predict_category` stays deterministic-only and its tests unchanged.
- [ ] `app/api/analytics.py`: `GET /analytics/explanation?start=&end=` → `build_analytics` →
      `llm_gateway.explain_analytics` → `{provider, model, text}` (all `None` when no key).
- [ ] Tests: `test_categorization.py` — a fake provider fills a `NONE` prediction as `LLM`
      above threshold → assigned; a low-confidence LLM suggestion → `Uncategorized` / Review;
      the no-provider path is unchanged from Part 1. `test_analytics_explanation.py` — endpoint
      with a fake provider and with none (200 + nulls, never 500).

### P2-5. Checks & docs
- [ ] `uv run pytest` (≥ 90), `ruff check`, `ruff format --check`. No real network in the suite.
- [ ] `docs/activity.md`; `README.md` Status / Next up (→ #9); extend
      `docs/manual-verification-categorization.md` with the sanitizer + provider + "works with
      no key" checks (or a new `manual-verification-llm.md`).
- [ ] `tasks/todo.md` Review section.

## Review

_(filled in when Part 2 is done)_
