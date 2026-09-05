from datetime import date

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

# Importing app.db for its side effect: it registers the Engine-level "connect"
# listener that turns on PRAGMA foreign_keys. Tests must go through the same
# path as the application, otherwise they pass against unenforced constraints.
import app.db  # noqa: F401
from app.models import Batch, Statement, to_cents


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


@pytest.fixture()
def batch(session: Session) -> Batch:
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
    return batch


@pytest.fixture()
def statement(session: Session, batch: Batch) -> Statement:
    from decimal import Decimal

    statement = Statement(
        batch_id=batch.id,
        bank="Chase",
        account_type="checking",
        account_identifier_masked="1234",
        statement_start_date=date(2026, 1, 1),
        statement_end_date=date(2026, 1, 31),
        opening_balance_cents=to_cents(Decimal("1000.00")),
        closing_balance_cents=to_cents(Decimal("950.00")),
        parser_version="chase_checking_v1",
        extraction_status="SUCCESS",
    )
    session.add(statement)
    session.commit()
    return statement
