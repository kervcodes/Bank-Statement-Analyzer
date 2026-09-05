from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.models import Account, Batch, Statement, Transaction


@pytest.fixture()
def session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def test_statement_round_trip(session: Session):
    batch = Batch(
        selected=1,
        uploaded=1,
        upload_failed=0,
        processed=1,
        processing_failed=0,
        status="COMPLETED",
    )
    account = Account(
        bank="Chase",
        account_type="checking",
        account_identifier_masked="1234",
    )
    session.add(batch)
    session.add(account)
    session.commit()

    statement = Statement(
        batch_id=batch.id,
        account_id=account.id,
        bank="Chase",
        account_type="checking",
        account_identifier_masked="1234",
        statement_start_date=date(2026, 1, 1),
        statement_end_date=date(2026, 1, 31),
        opening_balance=Decimal("1000.00"),
        closing_balance=Decimal("950.00"),
        parser_version="chase_checking_v1",
        extraction_status="COMPLETED",
    )
    session.add(statement)
    session.commit()

    fetched = session.exec(select(Statement).where(Statement.id == statement.id)).one()

    assert fetched.bank == "Chase"
    assert fetched.opening_balance == Decimal("1000.00")
    assert fetched.account_id == account.id


def test_statement_with_transactions_round_trip(session: Session):
    batch = Batch(
        selected=1,
        uploaded=1,
        upload_failed=0,
        processed=1,
        processing_failed=0,
        status="COMPLETED",
    )
    session.add(batch)
    session.commit()

    statement = Statement(
        batch_id=batch.id,
        bank="Chase",
        account_type="checking",
        account_identifier_masked="1234",
        statement_start_date=date(2026, 1, 1),
        statement_end_date=date(2026, 1, 31),
        opening_balance=Decimal("1000.00"),
        closing_balance=Decimal("950.00"),
        parser_version="chase_checking_v1",
        extraction_status="COMPLETED",
    )
    session.add(statement)
    session.commit()

    transactions = [
        Transaction(
            statement_id=statement.id,
            transaction_date=date(2026, 1, 5),
            posted_date=date(2026, 1, 6),
            description_raw="NETFLIX.COM",
            description_normalized="Netflix",
            amount=Decimal("15.99"),
            direction="DEBIT",
            source_bank="Chase",
            source_page=1,
        ),
        Transaction(
            statement_id=statement.id,
            transaction_date=date(2026, 1, 10),
            posted_date=date(2026, 1, 11),
            description_raw="PAYROLL DEPOSIT",
            description_normalized="Payroll deposit",
            amount=Decimal("2000.00"),
            direction="CREDIT",
            source_bank="Chase",
            source_page=1,
        ),
    ]
    session.add_all(transactions)
    session.commit()

    fetched = session.exec(
        select(Statement).where(Statement.id == statement.id)
    ).one()

    assert len(fetched.transactions) == 2
    assert {t.direction for t in fetched.transactions} == {"DEBIT", "CREDIT"}
    assert fetched.account_id is None
