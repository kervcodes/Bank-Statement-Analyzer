"""Create, claim, and transition statement_job rows. Pure DB, no FastAPI/OCR imports."""

from datetime import UTC, datetime

from sqlalchemy import update
from sqlmodel import Session, col, select

from app.models import CLAIMABLE_JOB_STATUSES, StatementJob


def _utcnow() -> datetime:
    return datetime.now(UTC)


def enqueue_job(
    session: Session, *, batch_id: str, intake_file_id: str, pdf_path: str
) -> StatementJob:
    """Create a QUEUED job for one accepted file (REQ-PROC-002/003)."""
    job = StatementJob(
        batch_id=batch_id,
        intake_file_id=intake_file_id,
        pdf_path=pdf_path,
    )
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


def claim_next_job(session: Session) -> StatementJob | None:
    """Atomically claim the oldest claimable job, moving it to PROCESSING.

    The conditional UPDATE ... WHERE status IN (claimable) means two workers
    racing for the same row: only one gets rowcount 1, the other gets None and
    tries again.
    """
    job = session.exec(
        select(StatementJob)
        .where(col(StatementJob.status).in_(CLAIMABLE_JOB_STATUSES))
        .order_by(col(StatementJob.created_at))
        .limit(1)
    ).first()
    if job is None:
        return None

    result = session.execute(
        update(StatementJob)
        .where(col(StatementJob.id) == job.id)
        .where(col(StatementJob.status).in_(CLAIMABLE_JOB_STATUSES))
        .values(status="PROCESSING", updated_at=_utcnow())
    )
    session.commit()
    if result.rowcount != 1:
        return None

    session.refresh(job)
    return job


def mark_completed(
    session: Session, job: StatementJob, *, method: str, page_count: int
) -> None:
    job.status = "COMPLETED"
    job.extraction_method = method
    job.page_count = page_count
    job.failure_reason = None
    job.updated_at = _utcnow()
    session.add(job)
    session.commit()


def mark_failed(session: Session, job: StatementJob, reason: str) -> None:
    """Terminal failure, no further retries (REQ-PROC-102).

    Counts the attempt that just failed, so `attempt_count` always reflects how
    many times the job actually ran regardless of which path ended it.
    """
    job.attempt_count += 1
    job.status = "FAILED"
    job.failure_reason = reason
    job.updated_at = _utcnow()
    session.add(job)
    session.commit()


def record_retryable_failure(session: Session, job: StatementJob, reason: str) -> None:
    """Count one failed attempt; re-queue if attempts remain, else FAIL (REQ-PROC-101)."""
    job.attempt_count += 1
    job.failure_reason = reason
    job.updated_at = _utcnow()
    job.status = "RETRYING" if job.attempt_count < job.max_attempts else "FAILED"
    session.add(job)
    session.commit()
