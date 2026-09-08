"""REQ-PROC-103: flip a batch to a terminal status once every job is done.

Not a separate process, just a function the processor calls after each job
transition. Idempotent and safe to call from concurrent workers -- it only sets
the batch to a terminal status once all jobs are terminal, recomputing the same
counts each time.
"""

from sqlmodel import Session, col, func, select

from app.models import TERMINAL_JOB_STATUSES, Batch, StatementJob


def refresh_batch(session: Session, batch_id: str) -> None:
    batch = session.get(Batch, batch_id)
    if batch is None:
        return

    rows = session.exec(
        select(StatementJob.status, func.count())
        .where(col(StatementJob.batch_id) == batch_id)
        .group_by(col(StatementJob.status))
    ).all()
    counts = dict(rows)

    total = sum(counts.values())
    terminal = sum(counts.get(s, 0) for s in TERMINAL_JOB_STATUSES)
    if total == 0 or terminal < total:
        return  # still work to do -- leave the batch PROCESSING

    failed = counts.get("FAILED", 0) + counts.get("UNSUPPORTED", 0)
    batch.processed = counts.get("COMPLETED", 0)
    batch.processing_failed = failed

    # REQ-RPT-002: any exclusion at all -- a failed job, or a file rejected at
    # intake -- means the analysis is not complete and must say so.
    excluded = failed + batch.validation_failed + batch.upload_failed
    batch.status = "COMPLETED" if excluded == 0 else "COMPLETED_WITH_WARNINGS"
    session.add(batch)
    session.commit()
