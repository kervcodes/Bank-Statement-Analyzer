from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import uuid4

from sqlmodel import Field, Relationship, SQLModel


def _uuid() -> str:
    return str(uuid4())


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Batch(SQLModel, table=True):
    """A group of statements uploaded together. status: PROCESSING / COMPLETED /
    COMPLETED_WITH_WARNINGS / FAILED."""

    id: str = Field(default_factory=_uuid, primary_key=True)
    created_at: datetime = Field(default_factory=_utcnow)
    selected: int
    uploaded: int
    upload_failed: int
    processed: int
    processing_failed: int
    status: str

    statements: list["Statement"] = Relationship(back_populates="batch")


class Account(SQLModel, table=True):
    """A resolved internal account identity. Never stores the full account number."""

    id: str = Field(default_factory=_uuid, primary_key=True)
    bank: str
    account_type: str
    account_identifier_masked: str

    statements: list["Statement"] = Relationship(back_populates="account")
    transactions: list["Transaction"] = Relationship(back_populates="account")


class Statement(SQLModel, table=True):
    """One parsed statement. account_id is nullable: a Statement row can exist
    before account resolution runs during extraction/normalization."""

    id: str = Field(default_factory=_uuid, primary_key=True)
    batch_id: str = Field(foreign_key="batch.id")
    account_id: str | None = Field(default=None, foreign_key="account.id")
    bank: str
    account_type: str
    account_identifier_masked: str
    statement_start_date: date
    statement_end_date: date
    opening_balance: Decimal
    closing_balance: Decimal
    parser_version: str
    extraction_status: str

    batch: Batch = Relationship(back_populates="statements")
    account: Account | None = Relationship(back_populates="statements")
    transactions: list["Transaction"] = Relationship(back_populates="statement")


class Transaction(SQLModel, table=True):
    """A single canonical transaction. amount is always positive; direction
    (DEBIT/CREDIT) carries the sign. extraction_confidence is nullable because
    native text extraction has no confidence source — only OCR produces one."""

    id: str = Field(default_factory=_uuid, primary_key=True)
    statement_id: str = Field(foreign_key="statement.id")
    account_id: str | None = Field(default=None, foreign_key="account.id")
    transaction_date: date
    posted_date: date
    description_raw: str
    description_normalized: str
    amount: Decimal
    direction: str
    balance_after: Decimal | None = None
    category: str | None = None
    source_bank: str
    extraction_confidence: float | None = None
    source_page: int

    statement: Statement = Relationship(back_populates="transactions")
    account: Account | None = Relationship(back_populates="transactions")
