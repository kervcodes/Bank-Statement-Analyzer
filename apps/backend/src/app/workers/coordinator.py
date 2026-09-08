"""REQ-PROC-103: flip a batch to a terminal status once every job is done.

Not a separate process, just a function the processor calls after each job
transition. Idempotent and safe to call from concurrent workers -- it only sets
the batch to a terminal status once all jobs are terminal, recomputing the same
counts each time.
"""

from sqlmodel import Session, col, func, select

from app.models import TERMINAL_JOB_STATUSES, Batch, Statement, StatementJob
from app.services.deduplication import run_dedup_for_batch


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

    # A job can COMPLETE (the PDF parsed) while the statement it produced fails or
    # warns on financial validation -- REQ-VAL-003 excludes those from trusted
    # analytics, so the batch is not a clean "COMPLETED" either.
    flagged_statements = session.exec(
        select(func.count())
        .select_from(Statement)
        .where(col(Statement.batch_id) == batch_id)
        .where(col(Statement.validation_result).in_(("WARNING", "FAILED")))
    ).one()

    # REQ-RPT-002: any exclusion at all -- a failed job, a file rejected at
    # intake, or a statement that doesn't reconcile -- means the analysis is not
    # complete and must say so.
    excluded = (
        failed + batch.validation_failed + batch.upload_failed + flagged_statements
    )
    first_completion = batch.status == "PROCESSING"
    batch.status = "COMPLETED" if excluded == 0 else "COMPLETED_WITH_WARNINGS"
    session.add(batch)
    session.commit()

    # Dedup runs once, the first time the batch reaches a terminal state: it
    # checks this batch's new statements against the existing ledger (build-plan
    # #7). It does not change the batch status -- a re-uploaded duplicate is
    # expected, not a warning; possible duplicates surface in Review instead.
    if first_completion:
        run_dedup_for_batch(session, batch_id)
