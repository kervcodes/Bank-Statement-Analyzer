"""A small, representative categorization evaluation sample.

Not real statement data (see the 2026-09-08 privacy rule: no raw statement
text is ever committed to the repo) -- synthetic descriptions built from the
same *shapes* seen in real Uncategorized transactions: chain restaurants and
warehouse clubs with store-number/city suffixes, a bank-specific "MOBILE - "
channel prefix, toll/fee keywords, and unknown SaaS/local-business merchants
that only the LLM fallback should resolve.

Each case declares which tier of the hierarchy is expected to resolve it, so
`test_categorization_eval.py` can report real coverage/accuracy numbers, not
just pass/fail:

- "deterministic" -- resolved by a built-in merchant/contextual/keyword rule,
  no LLM call.
- "llm"           -- the deterministic rules leave it `NONE`; the (stubbed)
  LLM provides a high-confidence answer that clears the auto-assign gate.
- "review"        -- correctly stays Uncategorized: either the stub LLM
  answers with confidence below the gate, or there is no signal at all.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class EvalCase:
    description: str
    direction: str
    expected_category: str | None
    expected_tier: str  # "deterministic" | "llm" | "review"


CASES: tuple[EvalCase, ...] = (
    # --- deterministic: existing coverage, unaffected by this change -------
    EvalCase("NETFLIX.COM CARD PURCHASE", "DEBIT", "Subscriptions", "deterministic"),
    EvalCase(
        "STARBUCKS STORE 5 BOSTON /MA US CARD PURCHASE",
        "DEBIT",
        "Dining",
        "deterministic",
    ),
    EvalCase("PAYROLL DEPOSIT ACME CORP", "CREDIT", "Income", "deterministic"),
    # --- deterministic: newly-added chains (real Uncategorized examples) ---
    EvalCase("ALDI 123 CAMBRIDGE MA", "DEBIT", "Groceries", "deterministic"),
    EvalCase("WENDY'S #2284 STOUGHTON", "DEBIT", "Dining", "deterministic"),
    EvalCase("BURGER KING #23973", "DEBIT", "Dining", "deterministic"),
    EvalCase("HOME DEPOT #789 QUINCY", "DEBIT", "Shopping", "deterministic"),
    EvalCase("ADVANCE AUTO PARTS #456", "DEBIT", "Shopping", "deterministic"),
    EvalCase("E-ZPASS MA WALTHAM", "DEBIT", "Transportation", "deterministic"),
    EvalCase("CAPITAL ONE CRCARDPMT", "DEBIT", "Credit Card Payments", "deterministic"),
    # --- deterministic: merchant-contextual tier (subtype overrides default) -
    EvalCase("BJ'S FUEL #9101", "DEBIT", "Fuel", "deterministic"),
    EvalCase("MOBILE - BJS", "DEBIT", "Fuel", "deterministic"),
    EvalCase("BJS WHOLESALE #123", "DEBIT", "Groceries", "deterministic"),
    EvalCase("COSTCO GAS #445", "DEBIT", "Fuel", "deterministic"),
    EvalCase("COSTCO WHOLESALE #445", "DEBIT", "Groceries", "deterministic"),
    # --- LLM fallback: unknown merchants deterministic rules can't place ----
    # (deliberately NOT hard-coded rules -- exactly the long-tail case the
    # LLM fallback exists for; the test stub answers these confidently.)
    EvalCase("OPENAI", "DEBIT", "Subscriptions", "llm"),
    EvalCase("GITHUB INC. SAN", "DEBIT", "Subscriptions", "llm"),
    EvalCase("CURSOR AI POWERED", "DEBIT", "Subscriptions", "llm"),
    EvalCase("VILLAGE SPEECH LLC", "DEBIT", "Healthcare", "llm"),
    # --- correctly stays in Review ------------------------------------------
    EvalCase("ZZQ MYSTERY VENDOR 99", "DEBIT", None, "review"),  # no signal at all
    EvalCase("PRINCH.COM", "DEBIT", None, "review"),  # stub is unsure
)
