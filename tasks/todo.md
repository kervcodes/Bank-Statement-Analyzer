# Todo: Reduce Uncategorized coverage in categorization pipeline

Branch `feature/categorization-coverage`, created off `origin/main` (`0483a48` + README PR #19).
Source: user's investigation request (2026-09-20) + follow-up correction (2026-09-20) + live
inspection of `apps/backend/data/app.db` (aggregate counts only — no PII/raw statement text
quoted anywhere below, per the 2026-09-08 privacy-incident rule).

**STATUS: diagnosis + revised design only. No code changed yet. Waiting for approval before
implementation.**

## Revision note (supersedes the first version of this plan)

The first draft proposed a flat `BJ's -> Groceries` rule and unconditionally stripping a
`MOBILE - ` bank channel prefix during merchant normalization. **Both are wrong and are dropped.**
Real data shows the same real-world merchant produces different categories depending on
transaction subtype:

```text
MOBILE - BJS...     -> Fuel       (BJ's gas-pump card channel)
BJ's Fuel #...       -> Fuel       (explicit "FUEL" in the descriptor)
BJ's Wholesale ...   -> Groceries  (in-warehouse purchase)
```

A single `merchant -> category` mapping cannot express this. The fix is a new rule tier, not a
bigger flat dictionary. See "Revised rule hierarchy" below.

## Real-data baseline (2,516 transactions, current `app.db`)

```text
predicted_source:  NONE = 1,598 (63.5%)   RULE = 918 (36.5%)   LLM = 0 (0%)
category:          Uncategorized = 1,321 (52.5% of all transactions)
category_source:   NONE=1,321  RULE=907  MERCHANT_RULE=285  USER=3
```

**The LLM has never produced a single prediction in this dataset — 0 out of 2,516 rows have
`predicted_source = LLM`.** That one fact still drives most of the diagnosis below; nothing in
the correction changes it.

## Root causes, ranked by estimated impact (unchanged from the original diagnosis)

1. **No backfill/reprocessing path exists.** `categorize_statement()` runs once, at ingestion,
   from `workers/processor.py:65`, and nowhere else. `recategorize_transaction()`
   (`services/categorization.py:160`, used by `PUT /category-rules` and
   `PUT /transactions/{id}/category`) only re-resolves from already-stored `predicted_*` columns
   — it never re-runs `predict_category` or `suggest_category`. Every transaction imported before
   an LLM key existed, or before a rule existed, stays exactly as it was forever. This is still
   the single biggest lever regardless of every other fix below.
2. **Deterministic coverage gap** for common chains (Wendy's, Burger King, Aldi, BJ's, 7-Eleven,
   Home Depot, Nordstrom, Advance Auto Parts) and missing toll/generic-fee keywords.
3. **Merchant normalization fragments one real merchant into multiple canonical strings**
   (unhandled `MOBILE - ` prefix in some cases, unstripped city suffixes, apostrophe/hyphen
   sensitivity in aliases) — revised below to fix this without discarding subtype information.
4. **Ruled out:** privacy gateway blocking, and the 0.75 threshold — neither is implicated; ~~see
   the original diagnosis text for the full reasoning~~ (kept from the first draft, unaffected by
   this correction).

## The real design problem: merchant identity vs. transaction subtype vs. category

Three separate concepts were being conflated into one flat dictionary:

1. **Merchant identity** — "this is BJ's Wholesale Club," independent of which department or
   channel the charge came through. This is what `merchant_normalized` should express, and what
   analytics/"top merchants" should group by.
2. **Transaction subtype / context** — "this specific charge was at the fuel pump," carried by
   words in the original description (`FUEL`, `WHOLESALE`, `GAS`, or in some cases the payment
   channel itself, e.g. `MOBILE`) that a fully-collapsed merchant name throws away.
3. **Category** — the output, which depends on *both* merchant identity and subtype, not on
   merchant identity alone.

**Key architectural fact that makes this fixable without a bigger data model:** `description_normalized`
is preserved on the transaction untouched by merchant normalization (confirmed in
`parsers/santander_checking_v1.py::_normalize_description` — it only collapses whitespace and
strips a trailing ref/date token; it does not remove words like `FUEL` or `MOBILE`).
`predict_category()` already receives both `merchant` and `description_normalized` as separate
arguments. So subtype information is never actually lost from the data — it is only lost from the
**rule model**, which currently has nowhere to express "merchant X, when the description also
contains Y, means category Z, overriding merchant X's own default."

**Guardrail this design depends on:** any subtype/contextual pattern match must read
`description_normalized` (or the merchant+description haystack), never `merchant_normalized`.
`merchant_normalized` is allowed to keep collapsing aggressively for display/identity purposes —
that collapsing is safe precisely because subtype detection never depends on it.

## Revised rule hierarchy

```text
user override (existing)
  -> user merchant rule (existing: CategoryRule, one row per merchant)
  -> [Phase 2, not built now] user contextual rule (merchant + description pattern)
  -> built-in description-pattern / merchant-contextual rule   <- NEW (this change)
  -> built-in merchant default rule (existing MERCHANT_CATEGORY)
  -> built-in generic keyword rule (existing KEYWORD_CATEGORY)
  -> LLM fallback (existing, currently dead code in practice — see backfill above)
  -> Review / Uncategorized (existing)
```

### New tier: built-in merchant-contextual rules

One new ordered structure in `categorization_rules.py`, checked in `predict_category` **before**
the flat `MERCHANT_CATEGORY` default lookup, keyed by the already-resolved canonical merchant name
and matched against `description_normalized` (not `merchant_normalized`):

```text
MERCHANT_CONTEXTUAL_RULES: dict[str, tuple[tuple[str, str], ...]] = {
    "BJ's Wholesale Club": (("FUEL", "Fuel"), ("MOBILE", "Fuel")),
    "Costco": (("GAS", "Fuel"), ("FUEL", "Fuel")),
    "7-Eleven": (("FUEL", "Fuel"), ("GAS", "Fuel")),
}
```

Revised `predict_category` order becomes: exact merchant match -> **if a contextual rule exists
for that merchant AND a pattern hits `description_normalized`, return that category** -> else the
merchant's own default -> keyword fallback -> direction default -> `NONE`. This is the smallest
change that lets a specific pattern override a merchant default: one new dict, one new `if` before
the existing merchant-default return, no schema change, no migration, no new API surface.

This also means the `MOBILE - ` prefix question is now lower-stakes than the first draft treated
it: `_PREFIXES` in `merchant_normalization.py` can still be extended to strip a leading
`MOBILE - ` token when computing the *display* `merchant_normalized` (fixing the truncated-name
bug for merchants with no alias, e.g. the "Mobile - Black" case), because the contextual-rule tier
never reads `merchant_normalized` for subtype detection — it reads `description_normalized`, where
`MOBILE` (and `FUEL`, `WHOLESALE`, etc.) always survives regardless of what normalization does to
the display name.

### Reviewed the other flagged merchants for the same problem

| Merchant | Real ambiguity | Recommendation |
|---|---|---|
| BJ's | Fuel vs Groceries | Contextual rule (`FUEL`/`MOBILE` -> Fuel), default -> Groceries |
| Costco | Fuel vs Groceries | Contextual rule (`GAS`/`FUEL` -> Fuel), default -> Groceries. **Pre-existing bug found**: today `Costco` unconditionally maps to `Groceries` with no fuel case at all — any Costco gas purchase already in the database is almost certainly mis-categorized right now, independent of the Uncategorized problem. Worth fixing regardless of scope. |
| 7-Eleven | Fuel vs convenience-store purchase | Contextual rule (`FUEL`/`GAS` -> Fuel), default -> **Shopping** (closest existing taxonomy fit for a non-fuel convenience purchase; taxonomy has no "Convenience" category — flagging as a decision, see below) |
| Walmart | Groceries vs general Shopping | **No reliable text signal.** Big-box POS descriptors don't indicate department. Leave as a single default (`Shopping`, unchanged); document the limitation rather than guess. |
| Target | Groceries vs general Shopping | Same as Walmart — no reliable signal, leave as-is, document the limitation. |
| Amazon | Shopping vs Subscriptions/digital | Already partly handled: `Prime Video` is modeled as its own separate merchant identity today (own alias, own category), not as an Amazon subtype. Inconsistent with the merchant-identity-vs-subtype model above, but changing it affects "top merchants" analytics grouping — **out of scope for this change**, flagged for awareness only, not proposed as a fix here. |
| CVS / Walgreens | Healthcare vs ordinary front-store retail | **Likely no reliable text signal** either (front-store and pharmacy purchases typically share the same POS descriptor) — same treatment as Walmart/Target: leave the existing default, document the limitation. Will confirm against real descriptor samples during implementation before ruling this out completely. |

Deliberately **not** turning this into a rule for every merchant with any theoretical ambiguity —
only where a real text signal exists to act on (BJ's, Costco, 7-Eleven). Everywhere else, a
documented "we can't tell from the text, this is a known limitation" is more honest than a rule
that looks precise but doesn't actually discriminate.

## Everything else from the first draft that is unaffected by this correction

- **Backfill/re-categorization function** (`recategorize_all_uncategorized`, explicit endpoint,
  never touches `user_category` or an active merchant rule, idempotent) — unchanged, still the
  top-priority item.
- **Merchant normalization fixes** for city suffixes, apostrophe/hyphen alias matching, and the
  `merchant_normalized IS NULL` (245 rows) investigation — unchanged, still needed, still subject
  to the same guardrail (identity normalization may collapse aggressively; categorization logic
  must not depend on that collapsed value for subtype decisions).
- **Observability** (`skip_reason` on the Review response, no schema change) — unchanged.
- **Evaluation fixture and metrics reporting** — unchanged, and should now include explicit
  contextual-rule cases (BJ's Fuel vs BJ's Wholesale, Costco Gas vs Costco default) as accuracy
  checks, not just coverage checks.
- **Tests** — add: merchant-contextual rule wins over merchant default (BJ's Fuel case, Costco Gas
  case); merchant default still applies when no contextual pattern matches (BJ's Wholesale,
  Costco default); contextual rule never fires for the wrong merchant (a `FUEL` keyword elsewhere
  doesn't accidentally trigger a BJ's-scoped rule).

## Open questions / decisions needed before implementation

1. **7-Eleven non-fuel default category** — recommend `Shopping` (no `Convenience` category
   exists in the taxonomy). Confirm.
2. **City-suffix normalization approach** — general heuristic gated to only fire after a
   store-number token was stripped (recommended in the first draft) vs. a hardcoded town list.
   Confirm the general/gated approach.
3. **Backfill trigger surface** — explicit `POST /categorization/recategorize` endpoint plus a
   Review-screen button (recommended) vs. automatic on every LLM settings save. Recommend
   explicit-only given real LLM latency/cost.
4. **`merchant_normalized IS NULL` (245 rows)** — still needs its own root-cause read of the
   ingestion path before committing to a fix; first step of implementation, reported back before
   writing a fix.
5. **Phase 2 user-defined contextual rules** (a user's own "BJ's + Fuel -> X" override, not just
   "BJ's -> X") — is a `CategoryRule` schema change (add an optional description-pattern column) +
   new API surface. Recommend deferring to a follow-up rather than building it in this change,
   since the built-in contextual-rule tier already resolves every concrete case raised so far.
   Confirm you're OK deferring this, or want it pulled into this change now.
6. **Costco Fuel mapping** — this is a correctness fix to *already-shipped* behavior (existing
   default silently mis-categorizes Costco gas as Groceries today), not just new coverage.
   Confirming you want it bundled into this PR rather than filed separately, since it's the same
   code path and same root cause (missing contextual tier).

## Review

**Done.** All items implemented per the revised design, on `feature/categorization-coverage`
(off `origin/main`). Full details, including the exact numbers and every file touched, are in
`docs/activity.md`'s 2026-09-20 entry — summary here:

- New merchant-contextual rule tier (`MERCHANT_CONTEXTUAL_RULES`) so BJ's/Costco/7-Eleven resolve
  Fuel vs. their own default from `description_normalized`, never the collapsed
  `merchant_normalized`. Also fixed a pre-existing Costco correctness bug found while reviewing
  the other flagged merchants (gas was silently landing as Groceries).
- New deterministic aliases/keywords for the reported chains (Aldi, Wendy's, Burger King,
  7-Eleven, Home Depot, Nordstrom, Advance Auto Parts, Burlington, Dollar Tree/General) plus
  toll/generic-fee keywords. Deliberately did **not** add OpenAI/Cursor AI/GitHub/Star Market/
  Roche Brothers/Life360/etc. — left for the LLM fallback per the original instruction.
- Fixed two real merchant-normalization bugs: a trailing city/branch name after a store number
  previously blocked stripping *both* tokens (regex anchor failure), and an unhandled
  `"MOBILE - "` bank channel prefix was truncating real merchant names.
- **The backfill capability** (`recategorize_pending` + `POST /categorization/recategorize`) —
  the fix identified as highest-impact in the diagnosis. Explicit/user-triggered, not automatic.
- Observability: `skip_reason` on `/review/categorizations`, added without a schema change or an
  `app.llm` import outside the gateway (would have broken the existing hard boundary test).

**Tests:** 33 new, 292 total, 97.85% coverage, `ruff check` + `ruff format --check` clean.
`tests/test_categorization_eval.py` reports real coverage/accuracy metrics against a fixture
(`tests/fixtures/categorization_eval.py`) rather than just asserting pass/fail.

**Measured against a scratch copy of the real `app.db`** (copied, measured, then deleted — never
touched the live file): `recategorize_pending()` alone, with **no LLM key configured**, took real
Uncategorized from 1,371/2,516 (54.5%) to 907/2,516 (36.0%) — 464 fewer Uncategorized
transactions, from deterministic fixes only. A configured LLM key would improve this further for
the genuine long-tail merchants (Cursor AI, OpenAI, GitHub, Life360, Princh.com, Village Speech).

**Known limitations, documented not built (open decisions from the plan, not yet asked of the
owner):**
- User-defined contextual rules (vs. built-in) deferred — would need a `CategoryRule` schema
  change; the built-in tier already resolves every concrete case raised.
- Walmart/Target Groceries-vs-Shopping and CVS/Walgreens pharmacy-vs-front-store: left as single
  defaults, undocumented signal in the descriptor text to reliably split them — flagged rather
  than guessed.
- The `merchant_normalized IS NULL` root cause (two 2026-09-09 statements) was traced to a
  plausible historical explanation (see `docs/activity.md`) but not proven with certainty; moot
  either way since the backfill fixes the symptom.

**Verification performed:** full backend test suite + ruff, plus a real-data measurement run
(above). **Not performed:** no frontend changes were made (none were requested — the pasted
investigation scope was backend-only), so there is no "Recheck Uncategorized" button in the UI
yet; the new endpoint exists but is not wired to a frontend action. Flagging this in case it's
wanted as a follow-up.

**Recommended next step:** owner review of the diff, then decide on committing/pushing (per this
session's git rules, nothing has been pushed) and whether the frontend trigger is wanted now or
as a separate follow-up.
