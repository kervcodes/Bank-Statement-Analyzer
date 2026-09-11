"""REQ-INT-001/005/006: accept one or more PDFs, validate each independently.

Builds the Batch and per-file intake records (REQ-INT-006), then enqueues a
processing job for every accepted file (REQ-PROC-002/004). The background worker
(app/workers/) picks the jobs up; GET /batches/{id} reports progress.
"""

from datetime import date, datetime

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel
from sqlmodel import Session, col, func, select

from app.db import DATA_DIR, get_db_session
from app.models import Batch, IntakeFile, Statement, StatementJob, Transaction
from app.services.intake_validation import validate_pdf
from app.workers.coordinator import refresh_batch
from app.workers.queue import enqueue_job, reclaim_processing_jobs

router = APIRouter(prefix="/batches", tags=["batches"])

TEMP_DIR = DATA_DIR / "tmp"

# A job younger than this may genuinely still be in flight -- only startup
# recovery (no worker running yet) skips this check.
STALE_PROCESSING_SECONDS = 60


class IntakeFileResult(BaseModel):
    filename: str
    status: str
    failure_reason: str | None = None


class BatchIntakeResponse(BaseModel):
    batch_id: str
    status: str
    selected: int
    uploaded: int
    upload_failed: int
    validation_failed: int
    files: list[IntakeFileResult]


class JobStatus(BaseModel):
    id: str
    status: str
    attempt_count: int
    failure_reason: str | None = None
    extraction_method: str | None = None


class StatementSummary(BaseModel):
    id: str
    bank: str
    account_type: str
    account_identifier_masked: str
    extraction_status: str
    validation_result: str | None = None
    dedup_status: str


class BatchStatusResponse(BaseModel):
    batch_id: str
    status: str
    selected: int
    uploaded: int
    upload_failed: int
    validation_failed: int
    processed: int
    processing_failed: int
    possible_duplicate_count: int
    uncategorized_count: int
    jobs: list[JobStatus]
    statements: list[StatementSummary]


class BatchListItem(BaseModel):
    id: str
    created_at: datetime
    status: str
    selected: int
    uploaded: int
    upload_failed: int
    validation_failed: int
    processed: int
    processing_failed: int
    statement_count: int
    # min/max of the produced statements' periods -- the "Jan–Dec 2026" label in
    # History. Null while a batch has produced no statements yet.
    period_start: date | None = None
    period_end: date | None = None


class BatchListResponse(BaseModel):
    items: list[BatchListItem]
    page: int
    page_size: int
    total: int


class BatchRetryResponse(BaseModel):
    batch_id: str
    status: str
    reclaimed: int


@router.post("", response_model=BatchIntakeResponse)
async def create_batch(
    files: list[UploadFile] = File(...),  # noqa: B008 -- FastAPI's own idiom
    session: Session = Depends(get_db_session),  # noqa: B008 -- ditto
) -> BatchIntakeResponse:
    batch = Batch(
        selected=len(files),
        uploaded=0,
        upload_failed=0,
        validation_failed=0,
        processed=0,
        processing_failed=0,
        status="PROCESSING",
    )
    session.add(batch)
    session.commit()
    session.refresh(batch)

    batch_temp_dir = TEMP_DIR / batch.id
    results: list[IntakeFileResult] = []
    accepted_files: list[IntakeFile] = []

    for upload in files:
        filename = upload.filename or "unnamed file"

        try:
            content = await upload.read()
        except OSError:
            # REQ-INT-002: the file never made it to validation. REQ-INT-005:
            # keep going, one bad file must never block the rest of the batch.
            batch.upload_failed += 1
            session.add(
                IntakeFile(
                    batch_id=batch.id,
                    original_filename=filename,
                    status="UPLOAD_FAILED",
                    failure_reason="upload failed",
                )
            )
            results.append(
                IntakeFileResult(
                    filename=filename,
                    status="UPLOAD_FAILED",
                    failure_reason="upload failed",
                )
            )
            continue

        batch.uploaded += 1
        validation = validate_pdf(filename, content)

        if not validation.accepted:
            batch.validation_failed += 1
            session.add(
                IntakeFile(
                    batch_id=batch.id,
                    original_filename=filename,
                    status="VALIDATION_FAILED",
                    failure_reason=validation.failure_reason,
                )
            )
            results.append(
                IntakeFileResult(
                    filename=filename,
                    status="VALIDATION_FAILED",
                    failure_reason=validation.failure_reason,
                )
            )
            continue

        intake_file = IntakeFile(
            batch_id=batch.id,
            original_filename=filename,
            status="ACCEPTED",
            page_count=validation.page_count,
        )
        batch_temp_dir.mkdir(parents=True, exist_ok=True)
        temp_path = batch_temp_dir / f"{intake_file.id}.pdf"
        temp_path.write_bytes(content)
        intake_file.temp_path = str(temp_path)
        session.add(intake_file)
        accepted_files.append(intake_file)
        results.append(IntakeFileResult(filename=filename, status="ACCEPTED"))

    ready_count = batch.uploaded - batch.validation_failed
    batch.status = "PROCESSING" if ready_count > 0 else "FAILED"
    session.add(batch)
    session.commit()

    # REQ-PROC-004: only accepted files get a job; rejected files never enter
    # the queue.
    for intake_file in accepted_files:
        enqueue_job(
            session,
            batch_id=batch.id,
            intake_file_id=intake_file.id,
            pdf_path=intake_file.temp_path,
        )

    return BatchIntakeResponse(
        batch_id=batch.id,
        status=batch.status,
        selected=batch.selected,
        uploaded=batch.uploaded,
        upload_failed=batch.upload_failed,
        validation_failed=batch.validation_failed,
        files=results,
    )


@router.get("", response_model=BatchListResponse)
def list_batches(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    session: Session = Depends(get_db_session),  # noqa: B008
) -> BatchListResponse:
    """Past import batches, newest first (REQ-RPT: the History screen). Paginated;
    sort is deterministic (`created_at` then `id`, both descending)."""
    total = session.exec(select(func.count()).select_from(Batch)).one()

    batches = session.exec(
        select(Batch)
        .order_by(col(Batch.created_at).desc(), col(Batch.id).desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()

    ids = [b.id for b in batches]
    # one grouped query for the per-batch statement count + period span
    rollup: dict[str, tuple[int, date | None, date | None]] = {}
    if ids:
        rows = session.exec(
            select(
                col(Statement.batch_id),
                func.count(),
                func.min(col(Statement.statement_start_date)),
                func.max(col(Statement.statement_end_date)),
            )
            .where(col(Statement.batch_id).in_(ids))
            .group_by(col(Statement.batch_id))
        ).all()
        rollup = {r[0]: (r[1], r[2], r[3]) for r in rows}

    items = []
    for b in batches:
        count, start, end = rollup.get(b.id, (0, None, None))
        items.append(
            BatchListItem(
                id=b.id,
                created_at=b.created_at,
                status=b.status,
                selected=b.selected,
                uploaded=b.uploaded,
                upload_failed=b.upload_failed,
                validation_failed=b.validation_failed,
                processed=b.processed,
                processing_failed=b.processing_failed,
                statement_count=count,
                period_start=start,
                period_end=end,
            )
        )

    return BatchListResponse(items=items, page=page, page_size=page_size, total=total)


@router.get("/{batch_id}", response_model=BatchStatusResponse)
def get_batch(
    batch_id: str,
    session: Session = Depends(get_db_session),  # noqa: B008
) -> BatchStatusResponse:
    batch = session.get(Batch, batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail="batch not found")

    jobs = session.exec(
        select(StatementJob)
        .where(col(StatementJob.batch_id) == batch_id)
        .order_by(col(StatementJob.created_at))
    ).all()

    statements = session.exec(
        select(Statement)
        .where(col(Statement.batch_id) == batch_id)
        .order_by(col(Statement.statement_start_date))
    ).all()

    possible_duplicate_count = session.exec(
        select(func.count())
        .select_from(Transaction)
        .join(Statement, col(Transaction.statement_id) == col(Statement.id))
        .where(col(Statement.batch_id) == batch_id)
        .where(col(Transaction.dedup_status) == "POSSIBLE_DUPLICATE")
    ).one()

    uncategorized = session.exec(
        select(func.count())
        .select_from(Transaction)
        .join(Statement, col(Transaction.statement_id) == col(Statement.id))
        .where(col(Statement.batch_id) == batch_id)
        .where(col(Transaction.category_source) == "NONE")
    ).one()

    return BatchStatusResponse(
        batch_id=batch.id,
        status=batch.status,
        selected=batch.selected,
        uploaded=batch.uploaded,
        upload_failed=batch.upload_failed,
        validation_failed=batch.validation_failed,
        processed=batch.processed,
        processing_failed=batch.processing_failed,
        possible_duplicate_count=possible_duplicate_count,
        uncategorized_count=uncategorized,
        jobs=[
            JobStatus(
                id=j.id,
                status=j.status,
                attempt_count=j.attempt_count,
                failure_reason=j.failure_reason,
                extraction_method=j.extraction_method,
            )
            for j in jobs
        ],
        statements=[
            StatementSummary(
                id=s.id,
                bank=s.bank,
                account_type=s.account_type,
                account_identifier_masked=s.account_identifier_masked,
                extraction_status=s.extraction_status,
                validation_result=s.validation_result,
                dedup_status=s.dedup_status,
            )
            for s in statements
        ],
    )


@router.post("/{batch_id}/retry", response_model=BatchRetryResponse)
def retry_batch(
    batch_id: str,
    session: Session = Depends(get_db_session),  # noqa: B008
) -> BatchRetryResponse:
    """Reclaim jobs orphaned by a crash or restart -- the manual escape hatch
    for a batch stuck at "Processing" with no other way to act on it.

    Only reclaims jobs stale for STALE_PROCESSING_SECONDS: the worker may
    legitimately still be on one, and stealing it out from under an in-flight
    run would race the worker's own commit.
    """
    batch = session.get(Batch, batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail="batch not found")
    if batch.status != "PROCESSING":
        raise HTTPException(
            status_code=409, detail=f"batch is {batch.status}, nothing to retry"
        )

    reclaimed = reclaim_processing_jobs(
        session, batch_id=batch_id, min_age_seconds=STALE_PROCESSING_SECONDS
    )
    if not reclaimed:
        raise HTTPException(
            status_code=409,
            detail="no stalled jobs to retry -- batch is still actively processing",
        )

    refresh_batch(session, batch_id)
    session.refresh(batch)
    return BatchRetryResponse(
        batch_id=batch.id, status=batch.status, reclaimed=len(reclaimed)
    )
