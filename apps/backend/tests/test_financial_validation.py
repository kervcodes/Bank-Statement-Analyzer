"""Build-plan #6: the three-level financial validation. Traces to REQ-VAL-001/002.
NFR-MAINT-002 names financial reconciliation as a must-test area."""

from datetime import date
from decimal import Decimal

from sqlmodel import Session

from app.models import Statement, Transaction, to_cents
from app.services.financial_validation import validate_statement


def _statement(
    session: Session, batch, *, opening="100.00", closing="130.00"
) -> Statement:
    st = Statement(
        batch_id=batch.id,
        bank="Santander",
        account_type="checking",
        account_identifier_masked="6789",
        statement_start_date=date(2026, 3, 1),
        statement_end_date=date(2026, 3, 31),
        opening_balance_cents=to_cents(Decimal(opening)),
        closing_balance_cents=to_cents(Decimal(closing)),
        parser_version="santander_checking_v1",
        extraction_status="SUCCESS",
    )
    session.add(st)
    session.commit()
    session.refresh(st)
    return st


def _txn(session: Session, st: Statement, *, day: int, amount: str, direction: str):
    session.add(
        Transaction(
            statement_id=st.id,
            transaction_date=date(2026, 3, day),
            posted_date=date(2026, 3, day),
            description_raw="X",
            description_normalized="X",
            amount_cents=to_cents(Decimal(amount)),
            direction=direction,
            source_bank="Santander",
            source_page=1,
        )
    )
    session.commit()


def test_req_val_001_a_reconciling_statement_is_valid(session: Session, batch):
    st = _statement(session, batch, opening="100.00", closing="130.00")
    _txn(session, st, day=2, amount="50.00", direction="CREDIT")
    _txn(session, st, day=5, amount="20.00", direction="DEBIT")

    assert validate_statement(session, st) == "VALID"


def test_req_val_001_a_missed_debit_fails_reconciliation(session: Session, batch):
    # opening 100 + 50 credit - 20 debit = 130, but the statement claims 80:
    # a transaction is missing.
    st = _statement(session, batch, opening="100.00", closing="80.00")
    _txn(session, st, day=2, amount="50.00", direction="CREDIT")
    _txn(session, st, day=5, amount="20.00", direction="DEBIT")

    assert validate_statement(session, st) == "FAILED"


def test_a_transaction_outside_the_period_is_a_warning(session: Session, batch):
    st = _statement(session, batch, opening="100.00", closing="130.00")
    _txn(session, st, day=2, amount="50.00", direction="CREDIT")
    _txn(session, st, day=5, amount="20.00", direction="DEBIT")
    # reconciles, but one transaction is dated in April
    session.add(
        Transaction(
            statement_id=st.id,
            transaction_date=date(2026, 4, 3),
            posted_date=date(2026, 4, 3),
            description_raw="late",
            description_normalized="late",
            amount_cents=0,
            direction="DEBIT",
            source_bank="Santander",
            source_page=2,
        )
    )
    session.commit()

    assert validate_statement(session, st) == "WARNING"


def test_start_after_end_is_structurally_failed(session: Session, batch):
    st = _statement(session, batch)
    st.statement_end_date = date(2026, 2, 1)
    session.add(st)
    session.commit()

    assert validate_statement(session, st) == "FAILED"
