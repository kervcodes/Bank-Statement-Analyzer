"""REQ-CAT-001: an explicit backfill trigger.

`categorize_statement` only ever runs once, at ingestion. A transaction
imported before a rule existed, before merchant normalization was fixed, or
before an LLM key was ever configured stays exactly as it was until something
re-runs prediction for it. This is that something -- a deliberate, user-
triggered action (a real LLM backfill has real latency/cost), not something
that fires automatically on every settings save or app restart.
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlmodel import Session, col, func, select

from app.db import get_db_session
from app.models import UNCATEGORIZED, Transaction
from app.services.categorization import recategorize_pending

router = APIRouter(prefix="/categorization", tags=["categorization"])


class RecategorizeResponse(BaseModel):
    transactions_considered: int
    uncategorized_before: int
    uncategorized_after: int


def _uncategorized_count(session: Session) -> int:
    return session.exec(
        select(func.count())
        .select_from(Transaction)
        .where(col(Transaction.category) == UNCATEGORIZED)
    ).one()


@router.post("/recategorize", response_model=RecategorizeResponse)
def recategorize(
    session: Session = Depends(get_db_session),  # noqa: B008
) -> RecategorizeResponse:
    uncategorized_before = _uncategorized_count(session)
    considered = recategorize_pending(session)
    uncategorized_after = _uncategorized_count(session)
    return RecategorizeResponse(
        transactions_considered=considered,
        uncategorized_before=uncategorized_before,
        uncategorized_after=uncategorized_after,
    )
