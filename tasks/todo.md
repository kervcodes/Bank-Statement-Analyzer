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

### P2-2. Provider abstraction — `app/llm/`  ✅
- [x] `base.py` — `LLMProvider` Protocol (`categorize` / `explain`), `CategorySuggestion`,
      `LLMUnavailable`, and `parse_category_suggestion` (fence-strips, finds the first `{…}`,
      validates the category ∈ `CATEGORIES`, clamps confidence). **`None` = answered-but-unusable
      (→ Review, no fallback); `LLMUnavailable` = failed (→ fallback).**
- [x] `null.py` — `NullProvider`, both methods `None`.
- [x] `openai_provider.py` / `anthropic_provider.py` — raw `httpx` (deviation from the
      `claude-api` skill's SDK recommendation — noted in `docs/activity.md`; rationale: the
      codebase has no SDKs, keeps its dep surface small, and one transport = uniform
      `MockTransport` testing). Injectable `client` for tests. Any HTTP/parse error →
      `LLMUnavailable`. Anthropic: parses the first `text` block (thinking-block safe);
      `categorize` disables thinking, `explain` leaves it adaptive.
- [x] `providers.py` — `configured_providers()`: `LLM_PROVIDER` (default `openai`) picks the
      order; each provider included only if its key is present; `[]` when neither.
- [x] `uv add httpx` (promoted to runtime; removed the dev duplicate). `.env.example` created
      with `LLM_PROVIDER` / `OPENAI_*` / `ANTHROPIC_*`.
- [x] `tests/test_llm_providers.py` (18) — all `app/llm/` files at 100%. Good reply parsed;
      unknown category / malformed → `None`; fenced JSON parsed; 500 / timeout / 429 →
      `LLMUnavailable`; Anthropic skips a leading thinking block; `configured_providers()`
      ordering for each `LLM_PROVIDER` and with keys missing. **205 passed, 97%.**

### P2-3. The single gateway — `app/services/llm_gateway.py`  ✅
- [x] `suggest_category(...)` — build payload via `privacy_gateway` (a
      `PrivacyBlockedError` → `None`, no provider called); try each provider in order; on
      `LLMUnavailable` move to the next; **any answer** (a suggestion, a low-confidence
      suggestion, or `None`) ends the walk — the fallback is never used for a weak/absent
      answer, only for a failure.
- [x] `explain_analytics(analytics) -> Explanation` (`provider` / `model` / `text`, all `None`
      with no provider or all failed).
- [x] `tests/test_llm_gateway.py` (13) — **the leak test**: a description with an account
      number, a name, a phone and an email → the recorded provider payload contains none of
      them and exactly the four allowlisted keys. Fallback on `LLMUnavailable`; **no** fallback
      on a low-confidence answer or a `None`. Privacy-blocked → no provider call. Import-boundary
      walk: only `llm_gateway.py` imports `app.llm.*`.

### P2-4. Wire the LLM into categorization + a new endpoint  ✅
- [x] `categorization.py`: `_llm_prediction` stub removed; `predict_category` is now
      deterministic-only. `categorize_statement` runs `_llm_fill` between the rule pass and
      `resolve_category` — one `suggest_category` call per unique `(merchant, direction)` whose
      deterministic `predicted_source == "NONE"`, setting `predicted_source = "LLM"` on the
      group. The 0.75 gate in `resolve_category` is untouched, so a weak LLM answer → Review
      with the prediction retained. No provider → `suggest_category` returns `None` → identical
      to Part 1.
- [x] `app/api/analytics.py`: `GET /analytics/explanation?start=&end=` → `{provider, model,
      text}`, all `null` with no key.
- [x] Tests: `test_categorization.py` — LLM fills a `NONE` merchant (one call for two rows);
      low-confidence LLM → `Uncategorized`/`NONE`, `predicted_category` kept; no-provider path
      unchanged. `test_analytics.py` — the explanation endpoint with a fake provider and with
      none.

### P2-5. Checks & docs  ✅
- [x] `uv run pytest` (221 passed, 97%), `ruff check`, `ruff format --check`. No real network.
- [x] `docs/activity.md`; `README.md` Status / Next up (→ #9); `docs/manual-verification-llm.md`.
- [x] `tasks/todo.md` Review section (below).

## Review

### Part 2 — Privacy Gateway + LLM layer (this PR)

**Completed:** `app/services/privacy_gateway.py` (allowlist payload types + `sanitize_text` +
fail-closed), `app/llm/` (`LLMProvider` protocol, `NullProvider`, `OpenAIProvider` /
`AnthropicProvider` on raw `httpx`, `configured_providers()`), `app/services/llm_gateway.py`
(the single chokepoint + fallback rule), the LLM phase in `categorize_statement`, and
`GET /analytics/explanation`. `httpx` promoted to a runtime dep. Branch
`feature/privacy-llm-gateway` off `main` (Part 1 = PR #13 merged).

**Locked decisions honoured:** OpenAI primary (`gpt-5.6-luna`), Anthropic fallback
(`claude-sonnet-5`); fallback **only** on `LLMUnavailable` (timeout / rate limit / HTTP / API /
parse error), never on low confidence — a weak answer goes to Review like any sub-0.75
prediction; provider and model are separate env vars; the outbound payload is a 4-field
allowlist model built from primitives (never a serialized `Transaction`); merchant
normalization stays local and pre-network; all Part 1 invariants preserved.

**Deviation:** raw `httpx` for both provider clients rather than the `anthropic` SDK the
`claude-api` skill recommends. Rationale: the codebase has no SDKs anywhere, keeps a small
dependency surface (same ethos as "no pandas"), the calls are single JSON POSTs, and one
transport gives uniform `MockTransport` testing. Contained behind `LLMProvider` — an SDK swap
later touches one file.

**Tests:** `uv run pytest` — **_TBD_ passed, _TBD_% coverage** (gate 90). No real network
(every provider test uses `httpx.MockTransport`). New: `test_privacy_gateway.py` (24),
`test_llm_providers.py` (18), `test_llm_gateway.py` (13, incl. the build-plan leak test and
the import-boundary walk), plus `test_categorization.py` / `test_analytics.py` additions.

**Known / follow-ups:**
- Live-server E2E with a real key not run. `docs/manual-verification-llm.md` is the runbook.
- `gpt-5.6-luna` API shape assumed to be chat-completions; `anthropic-version: 2023-06-01`.
  Confirm against a real call when a key is available.
- Electron `safeStorage` + the Settings screen (real key handling) are build-plan #9; Part 2
  reads env vars only.
- Confidence calibration (the 0.75 gate, the rule confidences, and now the LLM's self-reported
  confidence) still needs a labelled pass over the 12 real statements.
