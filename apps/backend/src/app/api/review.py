"""The data behind the Review inbox (design-notes.md §3.4).

At build-plan #7 this exposes only the possible-duplicate transactions -- pairs
the dedup pass could not confidently collapse. The keep-both / this-is-a-dup
actions come with the Review UI (build-plan #9); this endpoint is read-only.
"""

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
