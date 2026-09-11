"""design-notes.md §3.5: the resolved account list.

Read-only. `Account` identity is `(bank, account_type, masked_digits)` under a
DB UNIQUE constraint (app/models/canonical.py) -- the current architecture
cannot produce two provisional accounts that are actually the same one, so
there is no merge action here.
"""

from datetime import date

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlmodel import Session, col, func, select

from app.db import get_db_session
from app.models import Account, Statement

router = APIRouter(prefix="/accounts", tags=["accounts"])


class AccountListItem(BaseModel):
    id: str
    bank: str
    account_type: str
    account_identifier_masked: str
    statement_count: int
    period_start: date | None = None
    period_end: date | None = None


class AccountListResponse(BaseModel):
    items: list[AccountListItem]
    page: int
    page_size: int
    total: int


@router.get("", response_model=AccountListResponse)
def list_accounts(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    session: Session = Depends(get_db_session),  # noqa: B008
) -> AccountListResponse:
    total = session.exec(select(func.count()).select_from(Account)).one()

    accounts = session.exec(
        select(Account)
        .order_by(col(Account.bank), col(Account.account_type))
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()

    ids = [a.id for a in accounts]
    rollup: dict[str, tuple[int, date | None, date | None]] = {}
    if ids:
        rows = session.exec(
            select(
                col(Statement.account_id),
                func.count(),
                func.min(col(Statement.statement_start_date)),
                func.max(col(Statement.statement_end_date)),
            )
            .where(col(Statement.account_id).in_(ids))
            .group_by(col(Statement.account_id))
        ).all()
        rollup = {r[0]: (r[1], r[2], r[3]) for r in rows}

    items = [
        AccountListItem(
            id=a.id,
            bank=a.bank,
            account_type=a.account_type,
            account_identifier_masked=a.account_identifier_masked,
            statement_count=rollup.get(a.id, (0, None, None))[0],
            period_start=rollup.get(a.id, (0, None, None))[1],
            period_end=rollup.get(a.id, (0, None, None))[2],
        )
        for a in accounts
    ]
    return AccountListResponse(items=items, page=page, page_size=page_size, total=total)
