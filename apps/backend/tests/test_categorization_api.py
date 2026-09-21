"""The explicit backfill endpoint: POST /categorization/recategorize.

A deliberate, user-triggered re-run of prediction over every transaction not
fixed by a user override -- the fix for a transaction imported before a rule
existed, before merchant normalization was fixed, or before an LLM key was
configured.
"""

from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.db import get_db_session
from app.main import app
from app.models import Batch, CategoryRule, Statement, Transaction


@pytest.fixture()
def client(session: Session):
    app.dependency_overrides[get_db_session] = lambda: session
    yield TestClient(app)
    app.dependency_overrides.clear()


def _statement(session: Session) -> Statement:
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
    s = Statement(
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
    session.add(s)
    session.commit()
    return s


def _txn(session: Session, statement: Statement, *, desc: str) -> Transaction:
    t = Transaction(
        statement_id=statement.id,
        transaction_date=date(2026, 1, 10),
        posted_date=date(2026, 1, 10),
        description_raw=desc,
        description_normalized=desc,
        amount_cents=1_000,
        direction="DEBIT",
        source_bank="Santander",
        source_page=1,
    )
    session.add(t)
    session.commit()
    return t


def test_recategorize_reports_before_and_after_counts(
    client: TestClient, session: Session
):
    s = _statement(session)
    _txn(session, s, desc="ALDI 123 CAMBRIDGE")  # will resolve via a new rule
    _txn(session, s, desc="ZZQ MYSTERY VENDOR 99")  # stays Uncategorized

    body = client.post("/categorization/recategorize").json()

    assert body["transactions_considered"] == 2
    assert body["uncategorized_before"] == 2
    assert body["uncategorized_after"] == 1


def test_recategorize_never_overwrites_a_user_override(
    client: TestClient, session: Session
):
    s = _statement(session)
    t = _txn(session, s, desc="ALDI 123 CAMBRIDGE")
    t.user_category = "Personal Care"
    t.category = "Personal Care"
    t.category_source = "USER"
    session.add(t)
    session.commit()

    client.post("/categorization/recategorize")

    session.refresh(t)
    assert t.category == "Personal Care"
    assert t.category_source == "USER"


def test_recategorize_respects_an_active_merchant_rule(
    client: TestClient, session: Session
):
    s = _statement(session)
    t = _txn(session, s, desc="ALDI 123 CAMBRIDGE")
    session.add(CategoryRule(merchant="Aldi", category="Personal Care"))
    session.commit()

    client.post("/categorization/recategorize")

    session.refresh(t)
    assert t.category == "Personal Care"
    assert t.category_source == "MERCHANT_RULE"


def test_recategorize_is_idempotent(client: TestClient, session: Session):
    s = _statement(session)
    _txn(session, s, desc="ALDI 123 CAMBRIDGE")

    first = client.post("/categorization/recategorize").json()
    second = client.post("/categorization/recategorize").json()

    assert first["uncategorized_after"] == second["uncategorized_after"] == 0
