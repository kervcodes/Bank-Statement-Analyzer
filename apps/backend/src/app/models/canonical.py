from datetime import UTC, date, datetime
from uuid import uuid4

from sqlmodel import CheckConstraint, Field, Relationship, SQLModel

# Allowed values for the constrained state columns. Kept next to the models so
# the CHECK constraints and any Python-side validation read from one list.
BATCH_STATUSES = ("PROCESSING", "COMPLETED", "COMPLETED_WITH_WARNINGS", "FAILED")
EXTRACTION_STATUSES = ("SUCCESS", "PARTIAL")
VALIDATION_RESULTS = ("VALID", "WARNING", "FAILED")
DIRECTIONS = ("DEBIT", "CREDIT")


def _in_list(column: str, values: tuple[str, ...]) -> str:
    rendered = ", ".join(f"'{v}'" for v in values)
    return f"{column} IN ({rendered})"


def _uuid() -> str:
    return str(uuid4())


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Batch(SQLModel, table=True):
    """A group of statements uploaded together."""

    __table_args__ = (
        CheckConstraint(_in_list("status", BATCH_STATUSES), name="ck_batch_status"),
    )

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
    """One parsed statement.

    A row here only ever describes a statement that parsed. Files that failed
    extraction, or that fell below the bank-detection confidence threshold
    (REQ-DET-002), have no bank, dates, balances, or parser version, and are
    tracked on the statement_jobs table instead (REQ-PROC-002, build-plan #5).
    The invariant this buys: if a Statement row exists, its numbers are real.

    account_id is nullable because a Statement row can exist before account
    resolution runs during normalization.

    extraction_status and validation_result are deliberately two columns, per
    REQ-VAL-004: the first answers "could we read the document", the second
    answers "do the numbers reconcile". They are independent -- a cleanly read
    statement that fails reconciliation is SUCCESS + FAILED -- and must never be
    collapsed into a single confidence score.

    Balances are stored as integer cents; see models/money.py.
    """

    __table_args__ = (
        CheckConstraint(
            _in_list("extraction_status", EXTRACTION_STATUSES),
            name="ck_statement_extraction_status",
        ),
        CheckConstraint(
            "validation_result IS NULL OR "
            + _in_list("validation_result", VALIDATION_RESULTS),
            name="ck_statement_validation_result",
        ),
    )

    id: str = Field(default_factory=_uuid, primary_key=True)
    batch_id: str = Field(foreign_key="batch.id", index=True)
    account_id: str | None = Field(default=None, foreign_key="account.id", index=True)
    bank: str
    account_type: str
    account_identifier_masked: str
    statement_start_date: date
    statement_end_date: date
    opening_balance_cents: int
    closing_balance_cents: int
    parser_version: str
    extraction_status: str
    # Null until financial validation has run (build-plan #6).
    validation_result: str | None = None

    batch: Batch = Relationship(back_populates="statements")
    account: Account | None = Relationship(back_populates="statements")
    transactions: list["Transaction"] = Relationship(back_populates="statement")


class Transaction(SQLModel, table=True):
    """A single canonical transaction.

    amount_cents is a non-negative integer count of cents and direction
    (DEBIT/CREDIT) carries the sign, per REQ-NORM-003. Storing money as integer
    minor units keeps addition, subtraction, and equality exact, which
    reconciliation (REQ-VAL-001) and exact-match dedup (REQ-DEDUP-002) both
    depend on. Conversion to and from Decimal happens only in models/money.py.

    extraction_confidence is nullable because native text extraction has no
    confidence source -- only OCR produces one.
    """

    __table_args__ = (
        CheckConstraint(
            _in_list("direction", DIRECTIONS), name="ck_transaction_direction"
        ),
        CheckConstraint("amount_cents >= 0", name="ck_transaction_amount_non_negative"),
    )

    id: str = Field(default_factory=_uuid, primary_key=True)
    statement_id: str = Field(foreign_key="statement.id", index=True)
    account_id: str | None = Field(default=None, foreign_key="account.id", index=True)
    transaction_date: date
    posted_date: date
    description_raw: str
    description_normalized: str
    amount_cents: int
    direction: str
    balance_after_cents: int | None = None
    category: str | None = None
    source_bank: str
    extraction_confidence: float | None = None
    source_page: int

    statement: Statement = Relationship(back_populates="transactions")
    account: Account | None = Relationship(back_populates="transactions")
