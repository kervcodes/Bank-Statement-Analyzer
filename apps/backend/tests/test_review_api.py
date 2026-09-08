"""Build-plan #7: GET /review/duplicates — the data behind the Review inbox."""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.db import get_db_session
from app.main import app
from app.models import Account, Batch, Statement, Transaction, to_cents


def _at(year: int, month: int, day: int) -> datetime:
    return datetime(year, month, day, tzinfo=UTC)


@pytest.fixture()
def client(session: Session):
    app.dependency_overrides[get_db_session] = lambda: session
    yield TestClient(app)
    app.dependency_overrides.clear()


def _seed_possible_duplicate(session: Session) -> None:
    session.add(
        Account(
            id="a1",
            bank="Santander",
            account_type="checking",
            account_identifier_masked="0520",
        )
    )
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

    def _stmt(start: date, end: date, created: datetime) -> Statement:
        s = Statement(
            batch_id=batch.id,
            account_id="a1",
            created_at=created,
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

    older = _stmt(date(2026, 1, 1), date(2026, 1, 31), _at(2026, 2, 1))
    newer = _stmt(date(2026, 1, 15), date(2026, 2, 15), _at(2026, 3, 1))

    canonical = Transaction(
        statement_id=older.id,
        account_id="a1",
        transaction_date=date(2026, 1, 20),
        posted_date=date(2026, 1, 20),
        description_raw="STARBUCKS",
        description_normalized="STARBUCKS",
        amount_cents=to_cents(Decimal("7.82")),
        direction="DEBIT",
        source_bank="Santander",
        source_page=1,
    )
    session.add(canonical)
    session.commit()
    flagged = Transaction(
        statement_id=newer.id,
        account_id="a1",
        transaction_date=date(2026, 1, 20),
        posted_date=date(2026, 1, 20),
        description_raw="STARBUCKS",
        description_normalized="STARBUCKS",
        amount_cents=to_cents(Decimal("7.82")),
        direction="DEBIT",
        source_bank="Santander",
        source_page=1,
        dedup_status="POSSIBLE_DUPLICATE",
        duplicate_of_id=canonical.id,
    )
    session.add(flagged)
    session.commit()


def test_no_possible_duplicates_returns_empty(client: TestClient):
    body = client.get("/review/duplicates").json()
    assert body == {"possible_duplicates": []}


def test_lists_a_possible_duplicate_with_its_match(
    client: TestClient, session: Session
):
    _seed_possible_duplicate(session)

    body = client.get("/review/duplicates").json()

    assert len(body["possible_duplicates"]) == 1
    pair = body["possible_duplicates"][0]
    assert pair["transaction"]["description_normalized"] == "STARBUCKS"
    assert pair["transaction"]["amount_cents"] == 782
    assert pair["matches"]["amount_cents"] == 782
    assert pair["transaction"]["statement_id"] != pair["matches"]["statement_id"]


def _stmt_for(session: Session) -> Statement:
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


def test_uncategorized_lane_groups_by_merchant(client: TestClient, session: Session):
    s = _stmt_for(session)
    for desc, merchant, cents, src in [
        ("ZZQ VENDOR 1", "Zzq Vendor", 4_000, "NONE"),
        ("ZZQ VENDOR 2", "Zzq Vendor", 2_000, "NONE"),
        ("NETFLIX.COM", "Netflix", 1_599, "RULE"),  # confidently categorized
    ]:
        session.add(
            Transaction(
                statement_id=s.id,
                transaction_date=date(2026, 1, 10),
                posted_date=date(2026, 1, 10),
                description_raw=desc,
                description_normalized=desc,
                amount_cents=cents,
                direction="DEBIT",
                source_bank="Santander",
                source_page=1,
                merchant_normalized=merchant,
                category="Uncategorized" if src == "NONE" else "Subscriptions",
                category_source=src,
            )
        )
    session.commit()

    body = client.get("/review/categorizations").json()
    assert len(body["groups"]) == 1
    group = body["groups"][0]
    assert group["merchant"] == "Zzq Vendor"
    assert group["transaction_count"] == 2
    assert group["total_cents"] == 6_000
