from datetime import UTC, datetime
from uuid import uuid4

from sqlmodel import CheckConstraint, Field, Relationship, SQLModel

from app.models.canonical import Batch

INTAKE_FILE_STATUSES = ("ACCEPTED", "UPLOAD_FAILED", "VALIDATION_FAILED")


def _uuid() -> str:
    return str(uuid4())


def _utcnow() -> datetime:
    return datetime.now(UTC)


class IntakeFile(SQLModel, table=True):
    """One file submitted to a batch, tracked from the moment it's received.

    Exists so REQ-INT-002's upload-failure/validation-failure distinction is a
    persisted, testable state per file, not just an HTTP response shape. This
    is not the job queue (`statement_jobs`, build-plan #5) -- that table only
    covers files that made it past intake. `temp_path` is the handoff point:
    step 5's worker pool reads ACCEPTED rows to build jobs from.
    """

    __tablename__ = "intake_file"
    __table_args__ = (
        CheckConstraint(
            "status IN ('ACCEPTED', 'UPLOAD_FAILED', 'VALIDATION_FAILED')",
            name="ck_intake_file_status",
        ),
    )

    id: str = Field(default_factory=_uuid, primary_key=True)
    batch_id: str = Field(foreign_key="batch.id", index=True)
    created_at: datetime = Field(default_factory=_utcnow)
    original_filename: str
    status: str
    # The specific, actionable reason from REQ-INT-004 (e.g. "password-protected").
    # Null only when status is ACCEPTED.
    failure_reason: str | None = None
    # Populated only when status is ACCEPTED; never written for a rejected file.
    temp_path: str | None = None
    page_count: int | None = None

    batch: Batch = Relationship(back_populates="intake_files")
