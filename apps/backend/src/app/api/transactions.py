"""Transaction reads for the frontend (drill-through + the detail drawer) and the
per-transaction category override (REQ-CAT-004).

A plain category edit here sets `user_category` on **one** transaction. Making a
correction apply to a whole merchant is a separate, explicit action
(`PUT /category-rules`).
"""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlmodel import Session, col, func, select

from app.db import get_db_session
from app.models import CATEGORIES, Statement, Transaction, is_spending_category
from app.services.categorization import recategorize_transaction
from app.services.ledger import ledger_query

router = APIRouter(prefix="/transactions", tags=["transactions"])

# Same rule the analytics engine uses for its spending totals
# (app/services/analytics.py: is_spending_category + DEBIT). Precomputed once
# so the filter is a plain SQL IN rather than a per-row Python check.
_SPENDING_CATEGORIES = [c for c in CATEGORIES if is_spending_category(c)]

_SORTS = {
    "date_desc": (col(Transaction.transaction_date).desc(), col(Transaction.id).desc()),
    "date_asc": (col(Transaction.transaction_date), col(Transaction.id)),
    "amount_desc": (col(Transaction.amount_cents).desc(), col(Transaction.id)),
    "amount_asc": (col(Transaction.amount_cents), col(Transaction.id)),
}


class CategoryUpdate(BaseModel):
    category: str


class TransactionCategoryResponse(BaseModel):
    id: str
    merchant_normalized: str | None
    category: str
    category_source: str
    predicted_category: str | None
    user_category: str | None


class TransactionListItem(BaseModel):
    id: str
    transaction_date: date
    merchant: str
    description_normalized: str
    amount_cents: int
    direction: str
    category: str
    category_source: str
    bank: str
    account_identifier_masked: str
    dedup_status: str


class TransactionListResponse(BaseModel):
    items: list[TransactionListItem]
    page: int
    page_size: int
    total: int


class TransactionSource(BaseModel):
    statement_id: str
    bank: str
    account_type: str
    account_identifier_masked: str
    period_start: date
    period_end: date
    source_page: int
    parser_version: str


class TransactionDetail(BaseModel):
    id: str
    transaction_date: date
    posted_date: date
    amount_cents: int
    direction: str
    category: str
    category_source: str
    predicted_category: str | None
    user_category: str | None
    merchant_normalized: str | None
    description_normalized: str
    description_raw: str
    dedup_status: str
    source: TransactionSource


@router.get("", response_model=TransactionListResponse)
def list_transactions(
    category: str | None = None,
    merchant: str | None = None,
    account_id: str | None = None,
    batch_id: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    include_duplicates: bool = False,
    spending_only: bool = False,
    sort: str = Query(default="date_desc"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
    session: Session = Depends(get_db_session),  # noqa: B008
) -> TransactionListResponse:
    """The deduplicated, validated ledger (REQ-ANLY-003), filtered and paginated
    -- the rows behind a Dashboard number (REQ-RPT-101)."""
    if sort not in _SORTS:
        raise HTTPException(status_code=422, detail=f"unknown sort {sort!r}")

    filters = []
    if date_from is not None:
        filters.append(col(Transaction.transaction_date) >= date_from)
    if date_to is not None:
        filters.append(col(Transaction.transaction_date) <= date_to)
    if category is not None:
        filters.append(col(Transaction.category) == category)
    if merchant is not None:
        filters.append(col(Transaction.merchant_normalized) == merchant)
    if account_id is not None:
        filters.append(col(Transaction.account_id) == account_id)
    if batch_id is not None:
        filters.append(
            col(Transaction.statement_id).in_(
                select(Statement.id).where(col(Statement.batch_id) == batch_id)
            )
        )
    if spending_only:
        # Mirrors the analytics engine's spending total exactly (REQ-RPT-101):
        # a Dashboard drill-through must show precisely the rows behind the
        # number, not every debit in the range.
        filters.append(col(Transaction.direction) == "DEBIT")
        filters.append(col(Transaction.category).in_(_SPENDING_CATEGORIES))

    base = ledger_query(include_duplicates=include_duplicates).where(*filters)

    total = session.exec(select(func.count()).select_from(base.subquery())).one()

    rows = session.exec(
        base.order_by(*_SORTS[sort]).offset((page - 1) * page_size).limit(page_size)
    ).all()

    statements = {
        s.id: s
        for s in session.exec(
            select(Statement).where(
                col(Statement.id).in_([r.statement_id for r in rows])
            )
        )
    }

    items = [
        TransactionListItem(
            id=t.id,
            transaction_date=t.transaction_date,
            merchant=t.merchant_normalized or t.description_normalized.strip(),
            description_normalized=t.description_normalized,
            amount_cents=t.amount_cents,
            direction=t.direction,
            category=t.category,
            category_source=t.category_source,
            bank=statements[t.statement_id].bank,
            account_identifier_masked=statements[
                t.statement_id
            ].account_identifier_masked,
            dedup_status=t.dedup_status,
        )
        for t in rows
    ]
    return TransactionListResponse(
        items=items, page=page, page_size=page_size, total=total
    )


@router.get("/{transaction_id}", response_model=TransactionDetail)
def get_transaction(
    transaction_id: str,
    session: Session = Depends(get_db_session),  # noqa: B008
) -> TransactionDetail:
    txn = session.get(Transaction, transaction_id)
    if txn is None:
        raise HTTPException(status_code=404, detail="transaction not found")
    statement = session.get(Statement, txn.statement_id)
    if statement is None:  # pragma: no cover -- FK guarantees it
        raise HTTPException(status_code=404, detail="source statement missing")

    return TransactionDetail(
        id=txn.id,
        transaction_date=txn.transaction_date,
        posted_date=txn.posted_date,
        amount_cents=txn.amount_cents,
        direction=txn.direction,
        category=txn.category,
        category_source=txn.category_source,
        predicted_category=txn.predicted_category,
        user_category=txn.user_category,
        merchant_normalized=txn.merchant_normalized,
        description_normalized=txn.description_normalized,
        description_raw=txn.description_raw,
        dedup_status=txn.dedup_status,
        source=TransactionSource(
            statement_id=statement.id,
            bank=statement.bank,
            account_type=statement.account_type,
            account_identifier_masked=statement.account_identifier_masked,
            period_start=statement.statement_start_date,
            period_end=statement.statement_end_date,
            source_page=txn.source_page,
            parser_version=statement.parser_version,
        ),
    )


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
