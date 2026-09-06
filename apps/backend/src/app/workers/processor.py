"""Run one claimed job through the extraction pipeline and classify the outcome."""

import logging
from pathlib import Path

from sqlmodel import Session

from app.models import StatementJob
from app.services.extraction import ExtractionFailedError, extract_text
from app.workers.coordinator import refresh_batch
from app.workers.queue import mark_completed, mark_failed, record_retryable_failure

logger = logging.getLogger(__name__)


class RetryableJobError(Exception):
    """A failure worth retrying (REQ-PROC-101).

    Build-plan #5 only ever raises this indirectly via ExtractionFailedError.
    It exists now so build-plan #6's parser code has one clear way to say
    "transient, try again" versus letting a deterministic failure fall through
    to a non-retried FAILED (REQ-PROC-102).
    """


def process_job(session: Session, job: StatementJob) -> None:
    """Process a job already in PROCESSING. Never raises -- every outcome is a
    recorded job state, so one bad statement never stops the worker (NFR-REL-001).
    """
    try:
        result = extract_text(Path(job.pdf_path))
    except (ExtractionFailedError, RetryableJobError) as exc:
        record_retryable_failure(session, job, str(exc))
    except Exception as exc:
        # An unexpected failure is still a job state, not a crash. REQ-PROC-102:
        # deterministic failures are not retried. Logged with a stack trace; the
        # reason is stored on the row.
        logger.exception("job %s failed with a non-retryable error", job.id)
        mark_failed(session, job, f"{type(exc).__name__}: {exc}")
    else:
        mark_completed(session, job, method=result.method, page_count=len(result.pages))

    refresh_batch(session, job.batch_id)
