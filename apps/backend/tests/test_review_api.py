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


# --- POST /review/duplicates/{id} (build-plan #9 PR 2) --------------------


def _flagged_pair(session: Session) -> tuple[str, str]:
    """A canonical transaction and a POSSIBLE_DUPLICATE pointing at it. Returns
    (flagged_id, canonical_id)."""
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

    def _stmt(start: date, end: date) -> Statement:
        s = Statement(
            batch_id=batch.id,
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

    older = _stmt(date(2026, 1, 1), date(2026, 1, 31))
    newer = _stmt(date(2026, 1, 15), date(2026, 2, 15))

    def _t(stmt: Statement, dedup: str, dup_of: str | None) -> Transaction:
        t = Transaction(
            statement_id=stmt.id,
            transaction_date=date(2026, 1, 20),
            posted_date=date(2026, 1, 20),
            description_raw="STARBUCKS",
            description_normalized="STARBUCKS",
            amount_cents=782,
            direction="DEBIT",
            source_bank="Santander",
            source_page=1,
            merchant_normalized="Starbucks",
            category="Dining",
            category_source="RULE",
            dedup_status=dedup,
            duplicate_of_id=dup_of,
        )
        session.add(t)
        session.commit()
        return t

    canonical = _t(older, "UNIQUE", None)
    flagged = _t(newer, "POSSIBLE_DUPLICATE", canonical.id)
    return flagged.id, canonical.id


def test_keep_both_marks_unique(client: TestClient, session: Session):
    flagged, _ = _flagged_pair(session)
    body = client.post(
        f"/review/duplicates/{flagged}", json={"action": "keep_both"}
    ).json()
    assert body["dedup_status"] == "UNIQUE"
    session.expire_all()
    assert session.get(Transaction, flagged).duplicate_of_id is None
    # re-running is a no-op 200
    assert (
        client.post(
            f"/review/duplicates/{flagged}", json={"action": "keep_both"}
        ).status_code
        == 200
    )


def test_confirm_marks_duplicate_and_keeps_the_link(
    client: TestClient, session: Session
):
    flagged, canonical = _flagged_pair(session)
    body = client.post(
        f"/review/duplicates/{flagged}", json={"action": "confirm"}
    ).json()
    assert body["dedup_status"] == "DUPLICATE"
    session.expire_all()
    assert session.get(Transaction, flagged).duplicate_of_id == canonical
    # excluded from the default ledger, visible with include_duplicates
    assert client.get("/transactions").json()["total"] == 1
    assert (
        client.get("/transactions", params={"include_duplicates": "true"}).json()[
            "total"
        ]
        == 2
    )


def test_confirm_without_a_match_is_409(client: TestClient, session: Session):
    flagged, _ = _flagged_pair(session)
    t = session.get(Transaction, flagged)
    t.duplicate_of_id = None
    session.add(t)
    session.commit()
    assert (
        client.post(
            f"/review/duplicates/{flagged}", json={"action": "confirm"}
        ).status_code
        == 409
    )


def test_action_on_a_non_flagged_txn_is_409(client: TestClient, session: Session):
    _, canonical = _flagged_pair(session)  # canonical is UNIQUE, never flagged
    assert (
        client.post(
            f"/review/duplicates/{canonical}", json={"action": "confirm"}
        ).status_code
        == 409
    )


def test_action_on_unknown_txn_is_404(client: TestClient):
    assert (
        client.post("/review/duplicates/nope", json={"action": "keep_both"}).status_code
        == 404
    )
