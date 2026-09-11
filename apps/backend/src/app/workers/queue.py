"""Create, claim, and transition statement_job rows. Pure DB, no FastAPI/OCR imports."""

from datetime import UTC, datetime, timedelta

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
    session: Session,
    job: StatementJob,
    *,
    method: str,
    page_count: int,
    statement_id: str | None = None,
) -> None:
    job.status = "COMPLETED"
    job.extraction_method = method
    job.page_count = page_count
    job.statement_id = statement_id
    job.failure_reason = None
    job.updated_at = _utcnow()
    session.add(job)
    session.commit()


def mark_unsupported(session: Session, job: StatementJob, reason: str) -> None:
    """Detection confidence was below threshold (REQ-DET-002). Terminal, and not
    a failed attempt -- the file was read fine, we just don't have a parser for
    it, so `attempt_count` is left alone."""
    job.status = "UNSUPPORTED"
    job.failure_reason = reason
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


def reclaim_processing_jobs(
    session: Session,
    *,
    batch_id: str | None = None,
    min_age_seconds: float | None = None,
) -> list[str]:
    """Requeue PROCESSING jobs orphaned by a crash or restart.

    PROCESSING is deliberately excluded from CLAIMABLE_JOB_STATUSES, so a job
    that never reaches a terminal status because the process died mid-job would
    otherwise sit there forever and keep its batch stuck at "Processing".

    No worker is running before app startup, so every PROCESSING row is
    guaranteed orphaned then -- call with no filters. At runtime the worker may
    legitimately still be on a job, so `min_age_seconds` guards against
    reclaiming one that is actually in flight.

    Counts as one more attempt, same as any other failed attempt, so a job
    that keeps getting orphaned still stops at `max_attempts` instead of
    retrying forever. Returns the batch_id of each job reclaimed (one entry
    per job, batches may repeat) so the caller knows which batches to
    re-evaluate.
    """
    query = select(StatementJob).where(col(StatementJob.status) == "PROCESSING")
    if batch_id is not None:
        query = query.where(col(StatementJob.batch_id) == batch_id)
    if min_age_seconds is not None:
        cutoff = _utcnow() - timedelta(seconds=min_age_seconds)
        query = query.where(col(StatementJob.updated_at) < cutoff)

    jobs = session.exec(query).all()
    reclaimed_batch_ids = []
    for job in jobs:
        job.attempt_count += 1
        job.status = "RETRYING" if job.attempt_count < job.max_attempts else "FAILED"
        job.failure_reason = (
            "interrupted before finishing (process restarted or job stalled)"
        )
        job.updated_at = _utcnow()
        session.add(job)
        reclaimed_batch_ids.append(job.batch_id)

    if reclaimed_batch_ids:
        session.commit()

    return reclaimed_batch_ids
