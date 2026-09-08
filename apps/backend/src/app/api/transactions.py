"""REQ-CAT-004: a per-transaction category override.

This sets `user_category` on **one** transaction and nothing else. Making a
correction apply to a whole merchant is a separate, explicit action
(`PUT /category-rules`) — a single "Amazon → Groceries" edit should not silently
recategorize every Amazon purchase.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session

from app.db import get_db_session
from app.models import CATEGORIES, Transaction
from app.services.categorization import recategorize_transaction

router = APIRouter(prefix="/transactions", tags=["transactions"])


class CategoryUpdate(BaseModel):
    category: str


class TransactionCategoryResponse(BaseModel):
    id: str
    merchant_normalized: str | None
    category: str
    category_source: str
    predicted_category: str | None
    user_category: str | None


@router.put("/{transaction_id}/category", response_model=TransactionCategoryResponse)
def set_transaction_category(
    transaction_id: str,
    body: CategoryUpdate,
    session: Session = Depends(get_db_session),  # noqa: B008
) -> TransactionCategoryResponse:
    if body.category not in CATEGORIES:
        raise HTTPException(
            status_code=422, detail=f"unknown category {body.category!r}"
        )

    txn = session.get(Transaction, transaction_id)
    if txn is None:
        raise HTTPException(status_code=404, detail="transaction not found")

    txn.user_category = body.category
    recategorize_transaction(session, txn)
    session.commit()
    session.refresh(txn)

    return TransactionCategoryResponse(
        id=txn.id,
        merchant_normalized=txn.merchant_normalized,
        category=txn.category,
        category_source=txn.category_source,
        predicted_category=txn.predicted_category,
        user_category=txn.user_category,
    )
