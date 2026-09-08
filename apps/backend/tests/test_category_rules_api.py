"""Build-plan #8 Part 1: the merchant-rule endpoints (REQ-CAT-004).

A rule is retroactive + future for its merchant, but never touches a transaction
the user has overridden by hand, and deleting it restores the prediction.
"""

from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.db import get_db_session
from app.main import app
from app.models import Batch, Statement, Transaction


@pytest.fixture()
def client(session: Session):
    app.dependency_overrides[get_db_session] = lambda: session
    yield TestClient(app)
    app.dependency_overrides.clear()


def _amazon_txn(session: Session, *, user_category: str | None = None) -> Transaction:
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
        description_raw="AMAZON.COM",
        description_normalized="AMAZON.COM",
        amount_cents=1000,
        direction="DEBIT",
        source_bank="Santander",
        source_page=1,
        merchant_normalized="Amazon",
        predicted_category="Shopping",
        predicted_confidence=0.97,
        predicted_source="RULE",
        user_category=user_category,
        category=user_category or "Shopping",
        category_source="USER" if user_category else "RULE",
    )
    session.add(t)
    session.commit()
    return t


def test_upsert_rule_recategorizes_matching_transactions(
    client: TestClient, session: Session
):
    plain = _amazon_txn(session)
    overridden = _amazon_txn(session, user_category="Entertainment")

    resp = client.put(
        "/category-rules", json={"merchant": "Amazon", "category": "Groceries"}
    )
    assert resp.status_code == 200
    assert resp.json()["transactions_recategorized"] == 1

    session.refresh(plain)
    session.refresh(overridden)
    assert plain.category == "Groceries"
    assert plain.category_source == "MERCHANT_RULE"
    assert overridden.category == "Entertainment"  # user override wins, untouched

    assert client.get("/category-rules").json() == [
        {"merchant": "Amazon", "category": "Groceries"}
    ]


def test_delete_rule_restores_the_prediction(client: TestClient, session: Session):
    plain = _amazon_txn(session)
    client.put("/category-rules", json={"merchant": "Amazon", "category": "Groceries"})
    session.refresh(plain)
    assert plain.category == "Groceries"

    resp = client.delete("/category-rules/Amazon")
    assert resp.status_code == 200
    assert resp.json()["transactions_recategorized"] == 1

    session.refresh(plain)
    assert plain.category == "Shopping"
    assert plain.category_source == "RULE"


def test_rule_rejects_unknown_category(client: TestClient):
    resp = client.put("/category-rules", json={"merchant": "Amazon", "category": "Xyz"})
    assert resp.status_code == 422


def test_delete_missing_rule_is_404(client: TestClient):
    assert client.delete("/category-rules/Nobody").status_code == 404
