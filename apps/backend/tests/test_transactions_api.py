"""Build-plan #8 Part 1: PUT /transactions/{id}/category (REQ-CAT-004)."""

from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.db import get_db_session
from app.main import app
from app.models import Batch, CategoryRule, Statement, Transaction


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
