"""REQ-PROC-002/003: one processing job per accepted file, tracked by status.

A statement_job is created for every IntakeFile that passed intake validation
(build-plan #3). It carries a path to the temp-stored PDF, never the bytes
(REQ-PROC-003). The worker pool (app/workers/) claims QUEUED/RETRYING rows and
runs them through the extraction pipeline (build-plan #4).

At this build step a COMPLETED job means the PDF's text was extracted. Bank
detection, parsing, and Statement rows arrive in build-plan #6; UNSUPPORTED is
in the status list now (REQ-PROC-002) so the schema does not change again then,
but nothing produces it yet.
"""

from datetime import UTC, datetime
from uuid import uuid4

from sqlmodel import CheckConstraint, Field, Relationship, SQLModel

from app.models.canonical import Batch
from app.models.intake import IntakeFile

JOB_STATUSES = (
    "QUEUED",
    "PROCESSING",
    "RETRYING",
    "COMPLETED",
    "FAILED",
    "UNSUPPORTED",
)
TERMINAL_JOB_STATUSES = ("COMPLETED", "FAILED", "UNSUPPORTED")
CLAIMABLE_JOB_STATUSES = ("QUEUED", "RETRYING")

DEFAULT_MAX_ATTEMPTS = 3


def _uuid() -> str:
    return str(uuid4())


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _in_list(column: str, values: tuple[str, ...]) -> str:
    rendered = ", ".join(f"'{v}'" for v in values)
    return f"{column} IN ({rendered})"


class StatementJob(SQLModel, table=True):
    """One unit of background processing for one accepted file."""

    __tablename__ = "statement_job"
    __table_args__ = (
        CheckConstraint(
            _in_list("status", JOB_STATUSES), name="ck_statement_job_status"
        ),
        CheckConstraint(
            "attempt_count >= 0", name="ck_statement_job_attempt_count_non_negative"
        ),
    )

    id: str = Field(default_factory=_uuid, primary_key=True)
    batch_id: str = Field(foreign_key="batch.id", index=True)
    intake_file_id: str = Field(foreign_key="intake_file.id", index=True)
    # REQ-PROC-003: a reference to the temp-stored PDF, never the bytes.
    pdf_path: str
    status: str = "QUEUED"
    attempt_count: int = 0
    max_attempts: int = DEFAULT_MAX_ATTEMPTS
    failure_reason: str | None = None
    # Filled on success, for observability only (NATIVE / OCR).
    extraction_method: str | None = None
    page_count: int | None = None
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)

    batch: Batch = Relationship()
    intake_file: IntakeFile = Relationship()
