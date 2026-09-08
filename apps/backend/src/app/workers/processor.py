"""Run one claimed job end to end: extract -> detect -> parse -> normalize -> validate.

Never raises -- every outcome is a recorded job state, so one bad statement never
stops the worker (NFR-REL-001).

Outcomes:
- extraction/OCR failure or an explicit `RetryableJobError` -> retryable
  (`RETRYING`, then `FAILED` after 2 retries)
- detection confidence below threshold -> `UNSUPPORTED`, no Statement (REQ-VAL-005)
- `ParserError` / `SubCentPrecisionError` -> `FAILED`, non-retryable (deterministic)
- clean parse -> `COMPLETED` with a Statement row; `validation_result` carries
  whether the numbers reconcile
- any other exception -> `FAILED`, logged with a stack trace
"""

import logging
from pathlib import Path

from sqlmodel import Session

from app.models import StatementJob, SubCentPrecisionError
from app.parsers.base import ParserError
from app.services.categorization import categorize_statement
from app.services.detection import CONFIDENCE_THRESHOLD, detect
from app.services.extraction import ExtractionFailedError, extract_text
from app.services.financial_validation import validate_statement
from app.services.normalization import normalize
from app.workers.coordinator import refresh_batch
from app.workers.queue import (
    mark_completed,
    mark_failed,
    mark_unsupported,
    record_retryable_failure,
)

logger = logging.getLogger(__name__)


class RetryableJobError(Exception):
    """A failure worth retrying (REQ-PROC-101) that a parser wants to signal
    explicitly, as opposed to a deterministic `ParserError`."""


def process_job(session: Session, job: StatementJob) -> None:
    try:
        extraction = extract_text(Path(job.pdf_path))
        detection = detect(extraction.pages)

        if not detection.is_supported:
            mark_unsupported(
                session,
                job,
                f"bank detection confidence {detection.confidence:.2f} is below "
                f"the {CONFIDENCE_THRESHOLD:.2f} threshold",
            )
        elif detection.parser is not None:  # is_supported already guarantees this
            parsed = detection.parser.parse(Path(job.pdf_path), extraction)
            statement = normalize(session, parsed, batch_id=job.batch_id)
            statement.validation_result = validate_statement(session, statement)
            session.add(statement)
            session.commit()
            # Deterministic categorization (build-plan #8): merchant + category
            # for every transaction. Runs regardless of validation_result.
            categorize_statement(session, statement)
            mark_completed(
                session,
                job,
                method=extraction.method,
                page_count=len(extraction.pages),
                statement_id=statement.id,
            )
    except (ExtractionFailedError, RetryableJobError) as exc:
        record_retryable_failure(session, job, str(exc))
    except (ParserError, SubCentPrecisionError) as exc:
        # Deterministic: re-running would fail the same way (REQ-PROC-102).
        logger.warning("job %s: deterministic parse failure: %s", job.id, exc)
        mark_failed(session, job, f"{type(exc).__name__}: {exc}")
    except Exception as exc:
        logger.exception("job %s failed with a non-retryable error", job.id)
        mark_failed(session, job, f"{type(exc).__name__}: {exc}")

    refresh_batch(session, job.batch_id)
