"""Build-plan #7 Part B: the deterministic analytics engine (REQ-ANLY-001..004).

The aggregation functions are pure -- they take a list of Transaction rows and
return numbers -- so most of this builds transactions in memory and asserts exact
cents. The endpoint tests go through the database and TestClient.
"""

from datetime import UTC, date, datetime

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.db import get_db_session
from app.main import app
from app.models import Account, Batch, Statement, Transaction
from app.services.analytics import (
    build_analytics,
    cash_flow,
    merchant_totals,
    recurring_charges,
    spending_by_category,
    trends,
)
from app.services.deduplication import run_dedup_for_batch


def _t(
    day: date,
    amount_cents: int,
    direction: str,
    desc: str = "SOMETHING",
    category: str | None = None,
) -> Transaction:
    return Transaction(
        statement_id="stmt-1",
        transaction_date=day,
        posted_date=day,
        description_raw=desc,
        description_normalized=desc,
        amount_cents=amount_cents,
        direction=direction,
        category=category,
        source_bank="Santander",
        source_page=1,
    )


# --- a hand-built ledger reused across the pure-function tests -----------------

LEDGER = [
    _t(date(2026, 1, 10), 200_000, "CREDIT", "PAYROLL"),
    _t(date(2026, 1, 12), 5_000, "DEBIT", "STORE A"),
    _t(date(2026, 1, 20), 3_000, "DEBIT", "STORE B"),
    _t(date(2026, 2, 5), 200_000, "CREDIT", "PAYROLL"),
    _t(date(2026, 2, 10), 10_000, "DEBIT", "STORE A", category="Groceries"),
]


def test_cash_flow_monthly_exact_cents():
    flow = cash_flow(LEDGER)
    assert [(f.period, f.credits_cents, f.debits_cents, f.net_cents) for f in flow] == [
        ("2026-01", 200_000, 8_000, 192_000),
        ("2026-02", 200_000, 10_000, 190_000),
    ]


def test_cash_flow_rejects_unimplemented_period():
    with pytest.raises(ValueError, match="only 'month'"):
        cash_flow(LEDGER, period="week")


def test_spending_by_category_groups_and_orders():
    cats = spending_by_category(LEDGER)
    assert [(c.category, c.total_cents, c.transaction_count) for c in cats] == [
        ("Groceries", 10_000, 1),
        ("Uncategorized", 8_000, 2),
    ]


def test_merchant_totals_debits_only_ranked():
    merchants = merchant_totals(LEDGER)
    assert [(m.merchant, m.total_cents, m.transaction_count) for m in merchants] == [
        ("STORE A", 15_000, 2),
        ("STORE B", 3_000, 1),
    ]


def test_merchant_totals_respects_limit():
    assert len(merchant_totals(LEDGER, limit=1)) == 1


def test_recurring_detects_monthly_with_drifting_amount():
    # build-plan #7 explicitly asks for the slightly-varying-amount case.
    txns = [
        _t(date(2026, 1, 15), 1_599, "DEBIT", "NETFLIX"),
        _t(date(2026, 2, 15), 1_599, "DEBIT", "NETFLIX"),
        _t(date(2026, 3, 15), 1_649, "DEBIT", "NETFLIX"),
        _t(date(2026, 4, 15), 1_649, "DEBIT", "NETFLIX"),
    ]
    (charge,) = recurring_charges(txns)
    assert charge.merchant == "NETFLIX"
    assert charge.cadence == "monthly"
    assert charge.occurrences == 4
    assert 1_599 <= charge.typical_amount_cents <= 1_649
    assert charge.first_seen == date(2026, 1, 15)
    assert charge.last_seen == date(2026, 4, 15)


def test_recurring_ignores_irregular_intervals():
    txns = [
        _t(date(2026, 1, 1), 2_000, "DEBIT", "RANDOM STORE"),
        _t(date(2026, 1, 5), 2_000, "DEBIT", "RANDOM STORE"),
        _t(date(2026, 3, 20), 2_000, "DEBIT", "RANDOM STORE"),
    ]
    assert recurring_charges(txns) == []


def test_recurring_ignores_unstable_amount():
    txns = [
        _t(date(2026, 1, 15), 1_000, "DEBIT", "VARIABLE UTILITY"),
        _t(date(2026, 2, 15), 5_000, "DEBIT", "VARIABLE UTILITY"),
        _t(date(2026, 3, 15), 12_000, "DEBIT", "VARIABLE UTILITY"),
    ]
    assert recurring_charges(txns) == []


def test_trends_two_periods_deltas_as_strings():
    t = trends(LEDGER)
    assert t.current_period == "2026-02"
    assert t.previous_period == "2026-01"
    assert t.spending_delta_cents == 2_000
    assert t.spending_delta_ratio == "0.2500"
    assert t.net_delta_cents == -2_000


def test_trends_single_period_is_zero():
    t = trends([_t(date(2026, 1, 10), 5_000, "DEBIT")])
    assert t.current_period == "2026-01"
    assert t.previous_period is None
    assert t.spending_delta_cents == 0
    assert t.spending_delta_ratio is None


def test_trends_empty_ledger():
    t = trends([])
    assert t.current_period is None
    assert t.spending_delta_cents == 0


def test_trends_ratio_is_none_when_previous_period_had_no_spending():
    txns = [
        _t(date(2026, 1, 10), 200_000, "CREDIT", "PAYROLL"),  # Jan: no debits
        _t(date(2026, 2, 10), 4_000, "DEBIT", "STORE A"),
    ]
    t = trends(txns)
    assert t.spending_delta_cents == 4_000
    assert t.spending_delta_ratio is None


def test_recurring_ignores_group_with_a_repeated_date():
    txns = [
        _t(date(2026, 1, 15), 1_000, "DEBIT", "DOUBLE POST"),
        _t(date(2026, 1, 15), 1_000, "DEBIT", "DOUBLE POST"),
        _t(date(2026, 2, 15), 1_000, "DEBIT", "DOUBLE POST"),
    ]
    assert recurring_charges(txns) == []


# --- endpoint / build_analytics over the database -----------------------------


@pytest.fixture()
def client(session: Session):
    app.dependency_overrides[get_db_session] = lambda: session
    yield TestClient(app)
    app.dependency_overrides.clear()


def _seed_small_ledger(session: Session) -> None:
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

    stmt = Statement(
        batch_id=batch.id,
        account_id="a1",
        bank="Santander",
        account_type="checking",
        account_identifier_masked="0520",
        statement_start_date=date(2026, 1, 1),
        statement_end_date=date(2026, 2, 28),
        opening_balance_cents=0,
        closing_balance_cents=0,
        parser_version="santander_checking_v1",
        extraction_status="SUCCESS",
        validation_result="VALID",
    )
    session.add(stmt)
    session.commit()

    for txn in [
        _t(date(2026, 1, 10), 200_000, "CREDIT", "PAYROLL"),
        _t(date(2026, 1, 12), 5_000, "DEBIT", "STORE A"),
        _t(date(2026, 2, 10), 8_000, "DEBIT", "STORE A"),
    ]:
        txn.statement_id = stmt.id
        txn.account_id = "a1"
        session.add(txn)
    session.commit()


def test_build_analytics_over_db(session: Session):
    _seed_small_ledger(session)
    result = build_analytics(session)
    assert result.coverage.transaction_count == 3
    assert [f.period for f in result.cash_flow] == ["2026-01", "2026-02"]
    assert result.merchant_totals[0].merchant == "STORE A"
    assert result.merchant_totals[0].total_cents == 13_000


def test_get_analytics_endpoint(client: TestClient, session: Session):
    _seed_small_ledger(session)
    resp = client.get("/analytics")
    assert resp.status_code == 200
    body = resp.json()
    assert body["coverage"]["transaction_count"] == 3
    assert body["trends"]["current_period"] == "2026-02"
    assert body["cash_flow"][0] == {
        "period": "2026-01",
        "credits_cents": 200_000,
        "debits_cents": 5_000,
        "net_cents": 195_000,
    }


def test_get_analytics_empty_ledger_is_not_an_error(client: TestClient):
    resp = client.get("/analytics")
    assert resp.status_code == 200
    body = resp.json()
    assert body["cash_flow"] == []
    assert body["spending_by_category"] == []
    assert body["merchant_totals"] == []
    assert body["recurring_charges"] == []
    assert body["trends"]["spending_delta_cents"] == 0
    assert body["trends"]["current_period"] is None
    assert body["coverage"]["transaction_count"] == 0
    assert body["coverage"]["excluded"] == []


def test_get_analytics_rejects_a_bad_date(client: TestClient):
    assert client.get("/analytics?start=not-a-date").status_code == 422


def _seed_statement(session: Session, *, batch_id: str, created: datetime) -> Statement:
    if session.get(Account, "a1") is None:
        session.add(
            Account(
                id="a1",
                bank="Santander",
                account_type="checking",
                account_identifier_masked="0520",
            )
        )
        session.commit()
    stmt = Statement(
        batch_id=batch_id,
        account_id="a1",
        created_at=created,
        bank="Santander",
        account_type="checking",
        account_identifier_masked="0520",
        statement_start_date=date(2026, 1, 1),
        statement_end_date=date(2026, 1, 31),
        opening_balance_cents=0,
        closing_balance_cents=-8_000,
        parser_version="santander_checking_v1",
        extraction_status="SUCCESS",
        validation_result="VALID",
    )
    session.add(stmt)
    session.commit()
    for txn in [
        _t(date(2026, 1, 12), 5_000, "DEBIT", "STORE A"),
        _t(date(2026, 1, 20), 3_000, "DEBIT", "STORE B"),
    ]:
        txn.statement_id = stmt.id
        txn.account_id = "a1"
        session.add(txn)
    session.commit()
    return stmt


def test_reuploaded_statement_does_not_double_analytics(session: Session):
    """The manual check from the plan, as a test: process the same statement in
    two batches; dedup collapses the re-upload; analytics totals are unchanged."""
    b1 = Batch(
        selected=1,
        uploaded=1,
        upload_failed=0,
        validation_failed=0,
        processed=1,
        processing_failed=0,
        status="COMPLETED",
    )
    b2 = Batch(
        selected=1,
        uploaded=1,
        upload_failed=0,
        validation_failed=0,
        processed=1,
        processing_failed=0,
        status="COMPLETED",
    )
    session.add(b1)
    session.add(b2)
    session.commit()

    _seed_statement(session, batch_id=b1.id, created=datetime(2026, 2, 1, tzinfo=UTC))
    before = build_analytics(session)
    assert before.cash_flow[0].debits_cents == 8_000

    _seed_statement(session, batch_id=b2.id, created=datetime(2026, 3, 1, tzinfo=UTC))
    run_dedup_for_batch(session, b2.id)

    after = build_analytics(session)
    assert after.cash_flow == before.cash_flow
    assert after.coverage.transaction_count == 2
    assert after.coverage.statements_excluded == 1
