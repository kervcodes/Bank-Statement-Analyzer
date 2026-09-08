"""REQ-CAT-004: a user's "always categorize [merchant] as X" mapping.

Upserting a rule re-resolves every transaction of that merchant that has no
per-transaction override; deleting it re-resolves them back to their stored
prediction (non-destructive — the prediction was never discarded).
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, col, select

from app.db import get_db_session
from app.models import CATEGORIES, CategoryRule, Transaction
from app.services.categorization import recategorize_transaction

router = APIRouter(prefix="/category-rules", tags=["category-rules"])


class CategoryRuleBody(BaseModel):
    merchant: str
    category: str


class CategoryRuleOut(BaseModel):
    merchant: str
    category: str


class RuleWriteResponse(BaseModel):
    merchant: str
    category: str | None
    transactions_recategorized: int


def _reresolve_merchant(session: Session, merchant: str) -> int:
    txns = session.exec(
        select(Transaction)
        .where(col(Transaction.merchant_normalized) == merchant)
        .where(col(Transaction.user_category).is_(None))
    ).all()
    for txn in txns:
        recategorize_transaction(session, txn)
    return len(txns)


@router.get("", response_model=list[CategoryRuleOut])
def list_category_rules(
    session: Session = Depends(get_db_session),  # noqa: B008
) -> list[CategoryRuleOut]:
    rules = session.exec(
        select(CategoryRule).order_by(col(CategoryRule.merchant))
    ).all()
    return [CategoryRuleOut(merchant=r.merchant, category=r.category) for r in rules]


@router.put("", response_model=RuleWriteResponse)
def upsert_category_rule(
    body: CategoryRuleBody,
    session: Session = Depends(get_db_session),  # noqa: B008
) -> RuleWriteResponse:
    if body.category not in CATEGORIES:
        raise HTTPException(
            status_code=422, detail=f"unknown category {body.category!r}"
        )
    merchant = body.merchant.strip()
    if not merchant:
        raise HTTPException(status_code=422, detail="merchant is required")

    rule = session.exec(
        select(CategoryRule).where(col(CategoryRule.merchant) == merchant)
    ).first()
    if rule is None:
        rule = CategoryRule(merchant=merchant, category=body.category)
    else:
        rule.category = body.category
    session.add(rule)
    session.commit()

    count = _reresolve_merchant(session, merchant)
    session.commit()
    return RuleWriteResponse(
        merchant=merchant, category=body.category, transactions_recategorized=count
    )


@router.delete("/{merchant}", response_model=RuleWriteResponse)
def delete_category_rule(
    merchant: str,
    session: Session = Depends(get_db_session),  # noqa: B008
) -> RuleWriteResponse:
    rule = session.exec(
        select(CategoryRule).where(col(CategoryRule.merchant) == merchant)
    ).first()
    if rule is None:
        raise HTTPException(status_code=404, detail="rule not found")
    session.delete(rule)
    session.commit()

    count = _reresolve_merchant(session, merchant)
    session.commit()
    return RuleWriteResponse(
        merchant=merchant, category=None, transactions_recategorized=count
    )
