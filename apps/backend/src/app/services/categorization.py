"""REQ-CAT-001/003: assign each transaction a category through a fixed hierarchy.

```text
USER OVERRIDE  ->  MERCHANT RULE  ->  MERCHANT-CONTEXTUAL RULE  ->  MERCHANT DEFAULT
      ->  GENERIC KEYWORD RULE  ->  LLM (build-plan #8 pt 2)
      ->  confidence >= AUTO_ASSIGN_THRESHOLD ?  assign  :  Uncategorized (Review)
```

The prediction (`predicted_*`) is stored separately from the effective `category`
and is never discarded, so removing a user override or a merchant rule restores
it with no bulk row rewrite (REQ-CAT-004).

`predict_category` is deterministic-only, and checks a merchant's own
contextual pattern (`MERCHANT_CONTEXTUAL_RULES`) before that same merchant's
flat default -- a warehouse club sells both groceries and gas, and a single
`merchant -> category` mapping cannot express that. The LLM step runs in
`categorize_statement` as a separate phase over the transactions the rules left
`NONE` -- one call per unique merchant, always through `llm_gateway` (never a
provider client directly), and still subject to the 0.75 gate.

`categorize_statement` runs once, at ingestion, and `recategorize_pending` (an
explicit later backfill over every transaction not fixed by a user override)
share the same `_predict_and_resolve` body, so there is one prediction
pipeline, not two that can drift apart. `recategorize_transaction` is
deliberately different: it only re-resolves from the already-stored
prediction (a user edit or a merchant-rule change doesn't need a fresh guess).
"""

from collections import defaultdict
from dataclasses import dataclass

from sqlmodel import Session, col, select

from app.models import CategoryRule, Statement, Transaction
from app.services.categorization_rules import (
    CONFIDENCE_DIRECTION,
    CONFIDENCE_KEYWORD,
    CONFIDENCE_MERCHANT,
    KEYWORD_CATEGORY,
    MERCHANT_CATEGORY,
    MERCHANT_CONTEXTUAL_RULES,
)
from app.services.llm_gateway import suggest_category
from app.services.merchant_normalization import normalize_merchant

# The gate between "assign automatically" and "send to Review". Deliberately
# high: modifying someone's financial record on a weak guess is worse than
# asking them to confirm. A starting value — calibrate against real labelled
# transactions, optimizing precision on auto-assigned (tasks/todo.md decision 1).
AUTO_ASSIGN_THRESHOLD = 0.75


@dataclass(frozen=True)
class Prediction:
    category: str | None
    confidence: float
    source: str  # "RULE" | "LLM" | "NONE"


NO_PREDICTION = Prediction(category=None, confidence=0.0, source="NONE")


def predict_category(
    merchant: str, description_normalized: str, direction: str
) -> Prediction:
    """The deterministic automated guess for one transaction — a merchant's own
    contextual pattern (if any) beats that same merchant's default category,
    which beats keyword rules, which beat a direction-based default for
    credits. No network; the LLM step is a separate phase in
    `categorize_statement`.

    Contextual matching always reads `description_normalized`, never
    `merchant_normalized` -- the merchant name is intentionally collapsed for
    display/identity (e.g. "BJ's Wholesale Club" for every BJ's charge), so it
    is the wrong place to look for a subtype signal like "FUEL" that the
    original description still carries.
    """
    contextual_rules = MERCHANT_CONTEXTUAL_RULES.get(merchant)
    if contextual_rules is not None:
        description_haystack = description_normalized.upper()
        for keyword, category in contextual_rules:
            if keyword in description_haystack:
                return Prediction(category, CONFIDENCE_MERCHANT, "RULE")

    exact = MERCHANT_CATEGORY.get(merchant)
    if exact is not None:
        return Prediction(exact, CONFIDENCE_MERCHANT, "RULE")

    haystack = f"{merchant} {description_normalized}".upper()
    for keyword, category in KEYWORD_CATEGORY:
        if keyword in haystack:
            return Prediction(category, CONFIDENCE_KEYWORD, "RULE")

    if direction == "CREDIT":
        # A credit with no merchant or keyword signal is almost always income
        # (payroll under an employer name, a deposit). Transfers-in are caught
        # above by the Venmo/Zelle merchant mapping.
        return Prediction("Income", CONFIDENCE_DIRECTION, "RULE")

    return NO_PREDICTION


def resolve_category(txn: Transaction, *, merchant_rule_category: str | None) -> None:
    """Set `txn.category` / `txn.category_source` from the hierarchy. Pure — the
    caller supplies the merchant rule (or None) and persists."""
    if txn.user_category is not None:
        txn.category = txn.user_category
        txn.category_source = "USER"
        return
    if merchant_rule_category is not None:
        txn.category = merchant_rule_category
        txn.category_source = "MERCHANT_RULE"
        return
    if (
        txn.predicted_category is not None
        and (txn.predicted_confidence or 0.0) >= AUTO_ASSIGN_THRESHOLD
    ):
        txn.category = txn.predicted_category
        txn.category_source = txn.predicted_source
        return
    txn.category = "Uncategorized"
    txn.category_source = "NONE"


def _rule_lookup(session: Session) -> dict[str, str]:
    return {r.merchant: r.category for r in session.exec(select(CategoryRule)).all()}


def _llm_fill(txns: list[Transaction]) -> None:
    """For transactions the deterministic rules left unplaced, ask the LLM once
    per unique merchant (through the gateway, which sanitizes first). A usable
    suggestion becomes the `LLM` prediction -- still gated at 0.75 in
    `resolve_category`. With no provider configured, `suggest_category` returns
    ``None`` for every call and nothing changes."""
    groups: dict[tuple[str, str], list[Transaction]] = defaultdict(list)
    for txn in txns:
        if (
            txn.user_category is None
            and txn.predicted_source == "NONE"
            and txn.merchant_normalized
        ):
            groups[(txn.merchant_normalized, txn.direction)].append(txn)

    for (merchant, direction), group in groups.items():
        sample = group[0]
        suggestion = suggest_category(
            merchant_normalized=merchant,
            description_normalized=sample.description_normalized,
            amount_cents=sample.amount_cents,
            direction=direction,
        )
        if suggestion is None:
            continue
        for txn in group:
            txn.predicted_category = suggestion.category
            txn.predicted_confidence = suggestion.confidence
            txn.predicted_source = "LLM"


def _predict_and_resolve(
    session: Session, txns: list[Transaction], rules: dict[str, str]
) -> None:
    """The shared per-transaction-set pipeline body: normalize, predict (rules
    then LLM), then resolve. Used both for a freshly-ingested statement and for
    an arbitrary later re-run (`recategorize_pending`) -- one prediction
    pipeline, not two. Leaves a `USER`-set transaction's prediction untouched;
    does not commit (the caller owns the transaction boundary)."""
    for txn in txns:
        txn.merchant_normalized = normalize_merchant(txn.description_normalized)
        if txn.user_category is None:
            prediction = predict_category(
                txn.merchant_normalized, txn.description_normalized, txn.direction
            )
            txn.predicted_category = prediction.category
            txn.predicted_confidence = prediction.confidence
            txn.predicted_source = prediction.source

    _llm_fill(txns)

    for txn in txns:
        resolve_category(txn, merchant_rule_category=rules.get(txn.merchant_normalized))
        session.add(txn)


def categorize_statement(session: Session, statement: Statement) -> None:
    """The pipeline pass: normalize the merchant, predict (rules then LLM), and
    resolve for every transaction on the statement. Idempotent; leaves a
    `USER`-set transaction's prediction untouched."""
    rules = _rule_lookup(session)
    txns = list(
        session.exec(
            select(Transaction).where(col(Transaction.statement_id) == statement.id)
        )
    )
    _predict_and_resolve(session, txns, rules)
    session.commit()


def recategorize_pending(session: Session) -> int:
    """Re-run normalization and prediction (deterministic rules, then LLM) for
    every transaction not fixed by a user override -- the backfill path for
    transactions imported before a rule existed, before merchant normalization
    was fixed, or before an LLM key was ever configured (none of which
    `recategorize_transaction` covers, since it only re-resolves from the
    already-stored prediction).

    Never touches a `USER`-set transaction (REQ-CAT-004); an active merchant
    rule still wins in `resolve_category` regardless of what the fresh
    prediction says. Idempotent -- re-running with no config/rule change
    reproduces the same result. Returns the number of transactions considered.
    """
    rules = _rule_lookup(session)
    txns = list(
        session.exec(
            select(Transaction).where(col(Transaction.user_category).is_(None))
        )
    )
    _predict_and_resolve(session, txns, rules)
    session.commit()
    return len(txns)


def recategorize_transaction(session: Session, txn: Transaction) -> None:
    """Re-resolve one transaction's effective category (after a user edit or a
    merchant-rule change). Does not re-run prediction."""
    rule = None
    if txn.merchant_normalized:
        rule = session.exec(
            select(CategoryRule).where(
                col(CategoryRule.merchant) == txn.merchant_normalized
            )
        ).first()
    resolve_category(txn, merchant_rule_category=rule.category if rule else None)
    session.add(txn)
