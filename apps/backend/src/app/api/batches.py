"""REQ-INT-001/005/006: accept one or more PDFs, validate each independently.

Only builds the Batch and per-file intake records (REQ-INT-006: tracked from
the moment files are selected). Nothing here queues a job -- that table and
worker pool don't exist until build-plan #5, which will read ACCEPTED
IntakeFile rows to build jobs from.
"""

from fastapi import APIRouter, Depends, File, UploadFile
from pydantic import BaseModel
from sqlmodel import Session

from app.db import DATA_DIR, get_db_session
from app.models import Batch, IntakeFile
from app.services.intake_validation import validate_pdf

router = APIRouter(prefix="/batches", tags=["batches"])

TEMP_DIR = DATA_DIR / "tmp"


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
        results.append(IntakeFileResult(filename=filename, status="ACCEPTED"))

    ready_count = batch.uploaded - batch.validation_failed
    batch.status = "PROCESSING" if ready_count > 0 else "FAILED"
    session.add(batch)
    session.commit()

    return BatchIntakeResponse(
        batch_id=batch.id,
        status=batch.status,
        selected=batch.selected,
        uploaded=batch.uploaded,
        upload_failed=batch.upload_failed,
        validation_failed=batch.validation_failed,
        files=results,
    )
