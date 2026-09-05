from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.models import Account, Statement, Transaction, to_cents, to_decimal


def _transaction(statement_id: str, **overrides) -> Transaction:
    defaults = {
        "statement_id": statement_id,
        "transaction_date": date(2026, 1, 5),
        "posted_date": date(2026, 1, 6),
        "description_raw": "NETFLIX.COM",
        "description_normalized": "Netflix",
        "amount_cents": to_cents(Decimal("15.99")),
        "direction": "DEBIT",
        "source_bank": "Chase",
        "source_page": 1,
    }
    defaults.update(overrides)
    return Transaction(**defaults)


# ── Round trips ───────────────────────────────────────────────────────────────


def test_statement_round_trip(session: Session, statement: Statement):
    fetched = session.exec(select(Statement).where(Statement.id == statement.id)).one()

    assert fetched.bank == "Chase"
    assert fetched.opening_balance_cents == 100_000
    assert to_decimal(fetched.opening_balance_cents) == Decimal("1000.00")
    assert fetched.validation_result is None


def test_statement_with_transactions_round_trip(session: Session, statement: Statement):
    session.add_all(
        [
            _transaction(statement.id),
            _transaction(
                statement.id,
                description_raw="PAYROLL DEPOSIT",
                description_normalized="Payroll deposit",
                amount_cents=to_cents(Decimal("2000.00")),
                direction="CREDIT",
            ),
        ]
    )
    session.commit()

    fetched = session.exec(select(Statement).where(Statement.id == statement.id)).one()

    assert len(fetched.transactions) == 2
    assert {t.direction for t in fetched.transactions} == {"DEBIT", "CREDIT"}
    assert fetched.account_id is None


# ── Precision: the defect the original suite missed ───────────────────────────


def test_large_amount_survives_the_database_exactly(
    session: Session, statement: Statement
):
    """Stored as NUMERIC this came back as Decimal('12345678.9100000001').

    The failure was magnitude-dependent, so a test using 15.99 passed while the
    representation was already broken.
    """
    original = Decimal("12345678.91")
    session.add(_transaction(statement.id, amount_cents=to_cents(original)))
    session.commit()
    session.expire_all()

    fetched = session.exec(select(Transaction)).one()

    assert fetched.amount_cents == 1_234_567_891
    assert to_decimal(fetched.amount_cents) == original


def test_reconciliation_arithmetic_is_exact(session: Session, statement: Statement):
    """opening + credits - debits == closing, with no tolerance at all.

    REQ-VAL-001 allows a rounding tolerance for real statement quirks. This
    asserts the tolerance never has to absorb storage error -- which is what
    would have masked the float bug.
    """
    debits = [Decimal("0.10"), Decimal("0.20"), Decimal("49.75")]
    credits = [Decimal("0.05")]

    for i, amount in enumerate(debits):
        session.add(
            _transaction(
                statement.id,
                description_raw=f"DEBIT {i}",
                amount_cents=to_cents(amount),
                direction="DEBIT",
            )
        )
    for i, amount in enumerate(credits):
        session.add(
            _transaction(
                statement.id,
                description_raw=f"CREDIT {i}",
                amount_cents=to_cents(amount),
                direction="CREDIT",
            )
        )
    session.commit()
    session.expire_all()

    fetched = session.exec(select(Statement).where(Statement.id == statement.id)).one()
    credited = sum(
        t.amount_cents for t in fetched.transactions if t.direction == "CREDIT"
    )
    debited = sum(
        t.amount_cents for t in fetched.transactions if t.direction == "DEBIT"
    )

    assert fetched.opening_balance_cents + credited - debited == 95_000
    assert to_decimal(95_000) == Decimal("950.00")


# ── Foreign keys are actually enforced ────────────────────────────────────────


def test_orphan_transaction_is_rejected(session: Session):
    """SQLite leaves PRAGMA foreign_keys OFF by default; this insert used to commit."""
    session.add(_transaction("does-not-exist-anywhere"))
    with pytest.raises(IntegrityError):
        session.commit()


def test_orphan_statement_is_rejected(session: Session):
    session.rollback()
    statement = Statement(
        batch_id="no-such-batch",
        bank="Chase",
        account_type="checking",
        account_identifier_masked="1234",
        statement_start_date=date(2026, 1, 1),
        statement_end_date=date(2026, 1, 31),
        opening_balance_cents=0,
        closing_balance_cents=0,
        parser_version="v1",
        extraction_status="SUCCESS",
    )
    session.add(statement)
    with pytest.raises(IntegrityError):
        session.commit()


# ── State columns are constrained ─────────────────────────────────────────────


def test_invalid_direction_is_rejected(session: Session, statement: Statement):
    session.add(_transaction(statement.id, direction="SIDEWAYS"))
    with pytest.raises(IntegrityError):
        session.commit()


def test_negative_amount_is_rejected(session: Session, statement: Statement):
    """REQ-NORM-003: amount is always positive, direction carries the sign."""
    session.add(_transaction(statement.id, amount_cents=-1))
    with pytest.raises(IntegrityError):
        session.commit()


def test_invalid_extraction_status_is_rejected(session: Session, batch):
    statement = Statement(
        batch_id=batch.id,
        bank="Chase",
        account_type="checking",
        account_identifier_masked="1234",
        statement_start_date=date(2026, 1, 1),
        statement_end_date=date(2026, 1, 31),
        opening_balance_cents=0,
        closing_balance_cents=0,
        parser_version="v1",
        extraction_status="COMPLETED",  # a job status, not an extraction outcome
    )
    session.add(statement)
    with pytest.raises(IntegrityError):
        session.commit()


def test_invalid_batch_status_is_rejected(session: Session):
    from app.models import Batch

    session.rollback()
    session.add(
        Batch(
            selected=1,
            uploaded=1,
            upload_failed=0,
            processed=1,
            processing_failed=0,
            status="DONE",
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()


# ── REQ-VAL-004: the two signals are independent ──────────────────────────────


def test_extraction_and_validation_are_independent_signals(
    session: Session, statement: Statement
):
    """A cleanly read statement whose numbers do not reconcile is a legal state.

    If these two columns are ever collapsed into one confidence score, this is
    the case that stops being representable.
    """
    statement.validation_result = "FAILED"
    session.add(statement)
    session.commit()
    session.expire_all()

    fetched = session.exec(select(Statement).where(Statement.id == statement.id)).one()
    assert fetched.extraction_status == "SUCCESS"
    assert fetched.validation_result == "FAILED"


def test_invalid_validation_result_is_rejected(session: Session, statement: Statement):
    statement.validation_result = "OK"
    session.add(statement)
    with pytest.raises(IntegrityError):
        session.commit()


# ── Account relationship still resolves ───────────────────────────────────────


def test_statement_links_to_account(session: Session, statement: Statement):
    account = Account(
        bank="Chase", account_type="checking", account_identifier_masked="1234"
    )
    session.add(account)
    session.commit()

    statement.account_id = account.id
    session.add(statement)
    session.commit()
    session.expire_all()

    fetched = session.exec(select(Statement).where(Statement.id == statement.id)).one()
    assert fetched.account is not None
    assert fetched.account.bank == "Chase"
