"""REQ-CAT-004: a user's merchant -> category decision, remembered.

One row per merchant the user has explicitly mapped ("always categorize
[merchant] as X"). This is deliberately *not* written by a plain single-
transaction category edit -- that stays on the transaction (`user_category`).
A `CategoryRule` beats the automated prediction but loses to a per-transaction
`user_category`; deleting the rule restores every affected transaction to its
prediction (non-destructive).
"""

from datetime import UTC, datetime
from uuid import uuid4

from sqlmodel import CheckConstraint, Field, SQLModel

from app.models.taxonomy import category_in_sql


def _uuid() -> str:
    return str(uuid4())


def _utcnow() -> datetime:
    return datetime.now(UTC)


class CategoryRule(SQLModel, table=True):
    __tablename__ = "category_rule"
    __table_args__ = (
        CheckConstraint(category_in_sql("category"), name="ck_category_rule_category"),
    )

    id: str = Field(default_factory=_uuid, primary_key=True)
    # The normalized merchant name (matches Transaction.merchant_normalized).
    merchant: str = Field(unique=True, index=True)
    category: str
    created_at: datetime = Field(default_factory=_utcnow)
