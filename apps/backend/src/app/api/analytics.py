"""REQ-ANLY-004: the deterministic analytics payload as one structured response.
REQ-LLM-201: an optional plain-English explanation, clearly labelled with its
provider and never the source of a number.

Computed on demand from the deduplicated ledger each call (decision 2 in
`tasks/todo.md`) -- for a single-user local app over a few thousand rows this is
fast enough and sidesteps cache invalidation. Revisit if a real batch makes it
slow.
"""

from datetime import date

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlmodel import Session

from app.db import get_db_session
from app.services.analytics import Analytics, build_analytics
from app.services.llm_gateway import explain_analytics

router = APIRouter(prefix="/analytics", tags=["analytics"])


class ExplanationResponse(BaseModel):
    # All null when no LLM key is configured -- the frontend shows an empty state
    # and the rest of the dashboard works identically (REQ-LLM-102).
    provider: str | None
    model: str | None
    text: str | None


@router.get("", response_model=Analytics)
def get_analytics(
    start: date | None = None,
    end: date | None = None,
    session: Session = Depends(get_db_session),  # noqa: B008 -- FastAPI idiom
) -> Analytics:
    return build_analytics(session, start=start, end=end)


@router.get("/explanation", response_model=ExplanationResponse)
def get_analytics_explanation(
    start: date | None = None,
    end: date | None = None,
    session: Session = Depends(get_db_session),  # noqa: B008
) -> ExplanationResponse:
    result = explain_analytics(build_analytics(session, start=start, end=end))
    return ExplanationResponse(
        provider=result.provider, model=result.model, text=result.text
    )
