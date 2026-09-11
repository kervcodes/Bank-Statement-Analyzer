"""design-notes.md §3.5: GET /accounts, the resolved account list."""

from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.db import get_db_session
from app.main import app
from app.models import Account, Batch, Statement


@pytest.fixture()
def client(session: Session):
    app.dependency_overrides[get_db_session] = lambda: session
    yield TestClient(app)
    app.dependency_overrides.clear()


def _batch(session: Session) -> Batch:
    b = Batch(
        selected=1,
        uploaded=1,
        upload_failed=0,
        validation_failed=0,
        processed=1,
        processing_failed=0,
        status="COMPLETED",
    )
    session.add(b)
    session.commit()
    return b


def _statement(
    session: Session, *, batch: Batch, account_id: str, start: date, end: date
) -> Statement:
    s = Statement(
        batch_id=batch.id,
        account_id=account_id,
        bank="Santander",
        account_type="checking",
        account_identifier_masked="0520",
        statement_start_date=start,
        statement_end_date=end,
        opening_balance_cents=0,
        closing_balance_cents=0,
        parser_version="santander_checking_v1",
        extraction_status="SUCCESS",
        validation_result="VALID",
    )
    session.add(s)
    session.commit()
    return s


def test_empty_when_no_accounts(client: TestClient):
    body = client.get("/accounts").json()
    assert body == {"items": [], "page": 1, "page_size": 20, "total": 0}


def test_lists_accounts_with_a_statement_rollup(client: TestClient, session: Session):
    account = Account(
        bank="Santander", account_type="checking", account_identifier_masked="0520"
    )
    session.add(account)
    session.commit()
    batch = _batch(session)
    _statement(
        session,
        batch=batch,
        account_id=account.id,
        start=date(2026, 1, 1),
        end=date(2026, 1, 31),
    )
    _statement(
        session,
        batch=batch,
        account_id=account.id,
        start=date(2026, 2, 1),
        end=date(2026, 2, 28),
    )

    body = client.get("/accounts").json()

    assert body["total"] == 1
    (item,) = body["items"]
    assert item["bank"] == "Santander"
    assert item["account_type"] == "checking"
    assert item["account_identifier_masked"] == "0520"
    assert item["statement_count"] == 2
    assert item["period_start"] == "2026-01-01"
    assert item["period_end"] == "2026-02-28"


def test_an_account_with_no_statements_yet_shows_a_zero_rollup(
    client: TestClient, session: Session
):
    session.add(
        Account(bank="Chase", account_type="checking", account_identifier_masked="1234")
    )
    session.commit()

    (item,) = client.get("/accounts").json()["items"]

    assert item["statement_count"] == 0
    assert item["period_start"] is None
    assert item["period_end"] is None


def test_pagination(client: TestClient, session: Session):
    for i in range(3):
        session.add(
            Account(
                bank="Bank",
                account_type="checking",
                account_identifier_masked=f"{i:04d}",
            )
        )
    session.commit()

    page1 = client.get("/accounts", params={"page": 1, "page_size": 2}).json()
    assert page1["total"] == 3
    assert len(page1["items"]) == 2

    page2 = client.get("/accounts", params={"page": 2, "page_size": 2}).json()
    assert len(page2["items"]) == 1
