"""The data behind the Review inbox (design-notes.md §3.4).

Two lanes so far: possible-duplicate transactions the dedup pass could not
confidently collapse (build-plan #7), and transactions the categorizer routed to
Review because nothing cleared the confidence gate (build-plan #8). The
confirm / keep-both actions come with the Review UI (build-plan #9); the write
paths for categories are `PUT /transactions/{id}/category` and
`PUT /category-rules`.
"""

from collections import defaultdict

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlmodel import Session, col, select

from app.db import get_db_session
from app.models import Statement, Transaction

router = APIRouter(prefix="/review", tags=["review"])


class ReviewTransaction(BaseModel):
    id: str
    statement_id: str
    account_identifier_masked: str
    bank: str
    transaction_date: str
    description_normalized: str
    amount_cents: int
    direction: str


class PossibleDuplicate(BaseModel):
    transaction: ReviewTransaction
    matches: ReviewTransaction  # the transaction it may duplicate


class DuplicatesResponse(BaseModel):
    possible_duplicates: list[PossibleDuplicate]


def _to_review(txn: Transaction, statement: Statement) -> ReviewTransaction:
    return ReviewTransaction(
        id=txn.id,
        statement_id=txn.statement_id,
        account_identifier_masked=statement.account_identifier_masked,
        bank=statement.bank,
        transaction_date=txn.transaction_date.isoformat(),
        description_normalized=txn.description_normalized,
        amount_cents=txn.amount_cents,
        direction=txn.direction,
    )


@router.get("/duplicates", response_model=DuplicatesResponse)
def get_possible_duplicates(
    session: Session = Depends(get_db_session),  # noqa: B008
) -> DuplicatesResponse:
    flagged = session.exec(
        select(Transaction)
        .where(col(Transaction.dedup_status) == "POSSIBLE_DUPLICATE")
        .order_by(col(Transaction.transaction_date), col(Transaction.id))
    ).all()

    out: list[PossibleDuplicate] = []
    for txn in flagged:
        statement = session.get(Statement, txn.statement_id)
        match = (
            session.get(Transaction, txn.duplicate_of_id)
            if txn.duplicate_of_id
            else None
        )
        if statement is None or match is None:
            continue
        match_statement = session.get(Statement, match.statement_id)
        if match_statement is None:
            continue
        out.append(
            PossibleDuplicate(
                transaction=_to_review(txn, statement),
                matches=_to_review(match, match_statement),
            )
        )

    return DuplicatesResponse(possible_duplicates=out)


class UncategorizedGroup(BaseModel):
    merchant: str
    transaction_count: int
    total_cents: int
    # the sub-threshold guess, if there was one — shown as "Suggested: X"
    suggested_category: str | None
    sample_description: str


class UncategorizedResponse(BaseModel):
    groups: list[UncategorizedGroup]


@router.get("/categorizations", response_model=UncategorizedResponse)
def get_uncategorized(
    session: Session = Depends(get_db_session),  # noqa: B008
) -> UncategorizedResponse:
    """Transactions the categorizer could not confidently place, grouped by
    merchant so the user confirms one category per merchant, not per row."""
    rows = session.exec(
        select(Transaction)
        .where(col(Transaction.category_source) == "NONE")
        .order_by(col(Transaction.merchant_normalized), col(Transaction.id))
    ).all()

    grouped: dict[str, list[Transaction]] = defaultdict(list)
    for txn in rows:
        grouped[txn.merchant_normalized or txn.description_normalized].append(txn)

    groups = [
        UncategorizedGroup(
            merchant=merchant,
            transaction_count=len(txns),
            total_cents=sum(t.amount_cents for t in txns),
            suggested_category=next(
                (t.predicted_category for t in txns if t.predicted_category), None
            ),
            sample_description=txns[0].description_normalized,
        )
        for merchant, txns in grouped.items()
    ]
    groups.sort(key=lambda g: (-g.total_cents, g.merchant))
    return UncategorizedResponse(groups=groups)
