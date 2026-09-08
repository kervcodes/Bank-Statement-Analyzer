from collections.abc import Callable
from datetime import date
from pathlib import Path

import pytest
from _pdf import NATIVE_TEXT_PAGE, build_pdf
from sqlalchemy import Engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

# Importing app.db for its side effect: it registers the Engine-level "connect"
# listener that turns on PRAGMA foreign_keys. Tests must go through the same
# path as the application, otherwise they pass against unenforced constraints.
import app.db  # noqa: F401
from app.models import Batch, IntakeFile, Statement, StatementJob, to_cents


@pytest.fixture()
def db_engine() -> Engine:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    return engine


@pytest.fixture()
def session(db_engine: Engine):
    with Session(db_engine) as session:
        yield session


@pytest.fixture()
def session_factory(db_engine: Engine) -> Callable[[], Session]:
    """A factory the worker can call to open its own short-lived session on the
    same in-memory database the test's `session` fixture uses (StaticPool means
    one shared connection). The worker owns the session's lifecycle, so this
    hands out fresh ones rather than the test's."""

    def _make() -> Session:
        return Session(db_engine)

    return _make


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


@pytest.fixture()
def native_pdf_path(tmp_path: Path) -> Path:
    """A real on-disk PDF with usable embedded text -- extraction takes the
    NATIVE path against it, no OCR binary involved."""
    path = tmp_path / "statement.pdf"
    path.write_bytes(build_pdf([NATIVE_TEXT_PAGE]))
    return path


@pytest.fixture()
def intake_file(session: Session, batch: Batch, native_pdf_path: Path) -> IntakeFile:
    row = IntakeFile(
        batch_id=batch.id,
        original_filename="statement.pdf",
        status="ACCEPTED",
        temp_path=str(native_pdf_path),
        page_count=1,
    )
    session.add(row)
    session.commit()
    return row


@pytest.fixture()
def queued_job(session: Session, batch: Batch, intake_file: IntakeFile) -> StatementJob:
    job = StatementJob(
        batch_id=batch.id,
        intake_file_id=intake_file.id,
        pdf_path=intake_file.temp_path,
    )
    session.add(job)
    session.commit()
    return job
