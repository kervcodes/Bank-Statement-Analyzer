"""Build-plan #8 Part 1: PUT /transactions/{id}/category (REQ-CAT-004)."""

from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.db import get_db_session
from app.main import app
from app.models import Account, Batch, CategoryRule, Statement, Transaction


@pytest.fixture()
def client(session: Session):
    app.dependency_overrides[get_db_session] = lambda: session
    yield TestClient(app)
    app.dependency_overrides.clear()


def _txn(session: Session, *, desc: str, merchant: str) -> Transaction:
    batch = Batch(
        selected=1,
        uploaded=1,
        upload_failed=0,
        validation_failed=0,
        processed=1,
        processing_failed=0,
        status="COMPLETED",
    )
    session.add(batch)
    session.commit()
    stmt = Statement(
        batch_id=batch.id,
        bank="Santander",
        account_type="checking",
        account_identifier_masked="0520",
        statement_start_date=date(2026, 1, 1),
        statement_end_date=date(2026, 1, 31),
        opening_balance_cents=0,
        closing_balance_cents=0,
        parser_version="santander_checking_v1",
        extraction_status="SUCCESS",
        validation_result="VALID",
    )
    session.add(stmt)
    session.commit()
    t = Transaction(
        statement_id=stmt.id,
        transaction_date=date(2026, 1, 10),
        posted_date=date(2026, 1, 10),
        description_raw=desc,
        description_normalized=desc,
        amount_cents=1000,
        direction="DEBIT",
        source_bank="Santander",
        source_page=1,
        merchant_normalized=merchant,
        predicted_category="Shopping",
        predicted_confidence=0.97,
        predicted_source="RULE",
        category="Shopping",
        category_source="RULE",
    )
    session.add(t)
    session.commit()
    return t


def test_set_category_is_transaction_scoped(client: TestClient, session: Session):
    t1 = _txn(session, desc="AMAZON A", merchant="Amazon")
    t2 = _txn(session, desc="AMAZON B", merchant="Amazon")

    resp = client.put(f"/transactions/{t1.id}/category", json={"category": "Groceries"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["category"] == "Groceries"
    assert body["category_source"] == "USER"
    assert body["predicted_category"] == "Shopping"  # prediction preserved

    # the sibling Amazon transaction is untouched — no rule was created
    session.refresh(t2)
    assert t2.category == "Shopping"
    assert session.exec(select(CategoryRule)).all() == []


def test_unknown_category_is_rejected(client: TestClient, session: Session):
    t = _txn(session, desc="AMAZON", merchant="Amazon")
    resp = client.put(f"/transactions/{t.id}/category", json={"category": "Nope"})
    assert resp.status_code == 422


def test_missing_transaction_is_404(client: TestClient):
    resp = client.put(
        "/transactions/does-not-exist/category", json={"category": "Dining"}
    )
    assert resp.status_code == 404


# --- GET /transactions/{id} (the drawer) ---------------------------------


def test_transaction_detail_carries_the_source_block(
    client: TestClient, session: Session
):
    t = _txn(session, desc="NETFLIX.COM", merchant="Netflix")

    body = client.get(f"/transactions/{t.id}").json()

    assert body["description_raw"] == "NETFLIX.COM"
    assert body["merchant_normalized"] == "Netflix"
    src = body["source"]
    assert src["bank"] == "Santander"
    assert src["account_type"] == "checking"
    assert src["source_page"] == 1
    assert src["parser_version"] == "santander_checking_v1"
    assert src["period_start"] == "2026-01-01"


def test_transaction_detail_404(client: TestClient):
    assert client.get("/transactions/nope").status_code == 404


# --- GET /transactions (filtered, paginated list) ----------------------


def _stmt(session: Session, *, batch: Batch, validation: str = "VALID") -> Statement:
    s = Statement(
        batch_id=batch.id,
        bank="Santander",
        account_type="checking",
        account_identifier_masked="0520",
        statement_start_date=date(2026, 1, 1),
        statement_end_date=date(2026, 3, 31),
        opening_balance_cents=0,
        closing_balance_cents=0,
        parser_version="santander_checking_v1",
        extraction_status="SUCCESS",
        validation_result=validation,
    )
    session.add(s)
    session.commit()
    return s


def _row(
    session: Session,
    stmt: Statement,
    *,
    day: date,
    amount: int,
    category: str = "Groceries",
    merchant: str = "Corner Store",
    dedup: str = "UNIQUE",
    duplicate_of_id: str | None = None,
    account_id: str | None = None,
    direction: str = "DEBIT",
) -> Transaction:
    t = Transaction(
        statement_id=stmt.id,
        account_id=account_id,
        transaction_date=day,
        posted_date=day,
        description_raw=merchant,
        description_normalized=merchant,
        amount_cents=amount,
        direction=direction,
        source_bank="Santander",
        source_page=1,
        merchant_normalized=merchant,
        category=category,
        category_source="RULE",
        dedup_status=dedup,
        duplicate_of_id=duplicate_of_id,
    )
    session.add(t)
    session.commit()
    return t


@pytest.fixture()
def ledger(session: Session):
    batch = Batch(
        selected=1,
        uploaded=1,
        upload_failed=0,
        validation_failed=0,
        processed=1,
        processing_failed=0,
        status="COMPLETED",
    )
    session.add(batch)
    session.commit()
    session.add(
        Account(
            id="acct-x",
            bank="Santander",
            account_type="checking",
            account_identifier_masked="0520",
        )
    )
    session.commit()
    s = _stmt(session, batch=batch)
    canonical = _row(
        session,
        s,
        day=date(2026, 1, 5),
        amount=1000,
        merchant="Amazon",
        account_id="acct-x",
    )
    _row(
        session,
        s,
        day=date(2026, 2, 5),
        amount=3000,
        category="Dining",
        merchant="Cafe",
    )
    _row(session, s, day=date(2026, 3, 5), amount=2000, merchant="Amazon")
    _row(
        session,
        s,
        day=date(2026, 3, 6),
        amount=1000,
        merchant="Amazon",
        dedup="DUPLICATE",
        duplicate_of_id=canonical.id,
    )
    return {"batch_id": batch.id}


def test_list_defaults_exclude_duplicates_newest_first(client: TestClient, ledger):
    body = client.get("/transactions").json()
    assert body["total"] == 3  # the DUPLICATE row is out
    dates = [i["transaction_date"] for i in body["items"]]
    assert dates == sorted(dates, reverse=True)


def test_list_include_duplicates(client: TestClient, ledger):
    body = client.get("/transactions", params={"include_duplicates": "true"}).json()
    assert body["total"] == 4
    assert any(i["dedup_status"] == "DUPLICATE" for i in body["items"])


def test_list_filters(client: TestClient, ledger):
    assert (
        client.get("/transactions", params={"category": "Dining"}).json()["total"] == 1
    )
    assert (
        client.get("/transactions", params={"merchant": "Amazon"}).json()["total"] == 2
    )
    windowed = client.get(
        "/transactions", params={"date_from": "2026-02-01", "date_to": "2026-02-28"}
    ).json()
    assert windowed["total"] == 1
    assert (
        client.get("/transactions", params={"batch_id": ledger["batch_id"]}).json()[
            "total"
        ]
        == 3
    )
    assert (
        client.get("/transactions", params={"account_id": "acct-x"}).json()["total"]
        == 1
    )


def test_spending_only_excludes_transfers_and_credits(
    client: TestClient, session: Session, ledger
):
    """REQ-RPT-101: a Dashboard drill-through must show exactly the rows behind
    the spending number -- transfers and income never count as spending."""
    batch = session.get(Batch, ledger["batch_id"])
    s = _stmt(session, batch=batch)
    _row(session, s, day=date(2026, 4, 1), amount=50000, category="Transfers")
    _row(
        session,
        s,
        day=date(2026, 4, 2),
        amount=200000,
        category="Income",
        direction="CREDIT",
    )

    body = client.get("/transactions", params={"spending_only": "true"}).json()

    assert body["total"] == 3  # the 3 original spending rows, none of the new ones
    assert all(i["category"] not in ("Transfers", "Income") for i in body["items"])


def test_list_sort_and_pagination(client: TestClient, ledger):
    asc = client.get("/transactions", params={"sort": "amount_asc"}).json()
    assert [i["amount_cents"] for i in asc["items"]] == [1000, 2000, 3000]

    p1 = client.get("/transactions", params={"page_size": 2, "page": 1}).json()
    p2 = client.get("/transactions", params={"page_size": 2, "page": 2}).json()
    assert len(p1["items"]) == 2
    assert len(p2["items"]) == 1
    assert {i["id"] for i in p1["items"]}.isdisjoint({i["id"] for i in p2["items"]})

    assert client.get("/transactions", params={"sort": "bogus"}).status_code == 422
