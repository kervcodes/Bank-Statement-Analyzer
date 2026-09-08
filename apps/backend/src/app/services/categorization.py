"""REQ-CAT-001/003: assign each transaction a category through a fixed hierarchy.

```
USER OVERRIDE  →  MERCHANT RULE  →  DETERMINISTIC RULES  →  LLM (build-plan #8 pt 2)
      →  confidence ≥ AUTO_ASSIGN_THRESHOLD ?  assign  :  Uncategorized (Review)
```

The prediction (`predicted_*`) is stored separately from the effective `category`
and is never discarded, so removing a user override or a merchant rule restores
it with no bulk row rewrite (REQ-CAT-004).

Deterministic only here; the LLM fallback slots in at `_llm_prediction` in
build-plan #8 part 2.
"""

from dataclasses import dataclass

from sqlmodel import Session, col, select

from app.models import CategoryRule, Statement, Transaction
from app.services.categorization_rules import (
    CONFIDENCE_DIRECTION,
    CONFIDENCE_KEYWORD,
    CONFIDENCE_MERCHANT,
    KEYWORD_CATEGORY,
    MERCHANT_CATEGORY,
)
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


def _llm_prediction(
    merchant: str, description_normalized: str, direction: str
) -> Prediction | None:
    """LLM-assisted classification. Wired in build-plan #8 part 2 (behind the
    Privacy Gateway); until then there is no provider and this is skipped."""
    return None


def predict_category(
    merchant: str, description_normalized: str, direction: str
) -> Prediction:
    """The automated guess for one transaction — deterministic rules first, then
    (part 2) the LLM, then a direction-based default for credits."""
    exact = MERCHANT_CATEGORY.get(merchant)
    if exact is not None:
        return Prediction(exact, CONFIDENCE_MERCHANT, "RULE")

    haystack = f"{merchant} {description_normalized}".upper()
    for keyword, category in KEYWORD_CATEGORY:
        if keyword in haystack:
            return Prediction(category, CONFIDENCE_KEYWORD, "RULE")

    llm = _llm_prediction(merchant, description_normalized, direction)
    if llm is not None:
        return llm

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


def categorize_statement(session: Session, statement: Statement) -> None:
    """The pipeline pass: normalize the merchant, predict, and resolve for every
    transaction on the statement. Idempotent; leaves a `USER`-set transaction's
    prediction untouched."""
    rules = _rule_lookup(session)
    txns = session.exec(
        select(Transaction).where(col(Transaction.statement_id) == statement.id)
    ).all()
    for txn in txns:
        txn.merchant_normalized = normalize_merchant(txn.description_normalized)
        if txn.user_category is None:
            prediction = predict_category(
                txn.merchant_normalized, txn.description_normalized, txn.direction
            )
            txn.predicted_category = prediction.category
            txn.predicted_confidence = prediction.confidence
            txn.predicted_source = prediction.source
        resolve_category(txn, merchant_rule_category=rules.get(txn.merchant_normalized))
        session.add(txn)
    session.commit()


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
