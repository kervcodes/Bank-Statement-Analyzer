"""REQ-ANLY-004: the deterministic analytics payload as one structured response.

Computed on demand from the deduplicated ledger each call (decision 2 in
`tasks/todo.md`) -- for a single-user local app over a few thousand rows this is
fast enough and sidesteps cache invalidation. Revisit if a real batch makes it
slow.
"""

from datetime import date

from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.db import get_db_session
from app.services.analytics import Analytics, build_analytics

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("", response_model=Analytics)
def get_analytics(
    start: date | None = None,
    end: date | None = None,
    session: Session = Depends(get_db_session),  # noqa: B008 -- FastAPI idiom
) -> Analytics:
    return build_analytics(session, start=start, end=end)
