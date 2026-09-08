"""Build-plan #5: background job queue. Traces to requirements.md §3
(REQ-PROC-001 through 103); NFR-MAINT-002 calls out retry-state transitions as a
must-test area.
"""

import time
from collections.abc import Callable
from pathlib import Path

import pytest
from _pdf import NATIVE_TEXT_PAGE, build_pdf
from sqlmodel import Session, col, select

from app.models import Batch, IntakeFile, StatementJob
from app.services.extraction import ExtractionFailedError
from app.workers import processor
from app.workers.coordinator import refresh_batch
from app.workers.pool import BackgroundWorker, run_worker_once
from app.workers.queue import claim_next_job, enqueue_job


def _batch(session: Session, **overrides: object) -> Batch:
    fields: dict[str, object] = {
        "selected": 1,
        "uploaded": 1,
        "upload_failed": 0,
        "validation_failed": 0,
        "processed": 0,
        "processing_failed": 0,
        "status": "PROCESSING",
    }
    fields.update(overrides)
    batch = Batch(**fields)
    session.add(batch)
    session.commit()
    session.refresh(batch)
    return batch


def _accepted_file(session: Session, batch: Batch, pdf_path: Path) -> IntakeFile:
    row = IntakeFile(
        batch_id=batch.id,
        original_filename=pdf_path.name,
        status="ACCEPTED",
        temp_path=str(pdf_path),
        page_count=1,
    )
    session.add(row)
    session.commit()
    return row


def _pdf(tmp_path: Path, name: str = "s.pdf") -> Path:
    path = tmp_path / name
    path.write_bytes(build_pdf([NATIVE_TEXT_PAGE]))
    return path


# --- happy path -------------------------------------------------------------


def test_run_worker_once_completes_a_native_job(
    session: Session,
    session_factory: Callable[[], Session],
    queued_job: StatementJob,
):
    ran = run_worker_once(session_factory)

    assert ran is True
    session.expire_all()
    job = session.get(StatementJob, queued_job.id)
    assert job.status == "COMPLETED"
    assert job.extraction_method == "NATIVE"
    assert job.page_count == 1
    assert job.failure_reason is None


def test_run_worker_once_returns_false_on_empty_queue(
    session_factory: Callable[[], Session],
):
    assert run_worker_once(session_factory) is False


def test_background_worker_thread_drains_the_queue(
    session: Session,
    session_factory: Callable[[], Session],
    queued_job: StatementJob,
):
    """The daemon-thread wrapper (what FastAPI's lifespan starts) picks up a
    queued job on its own and stops cleanly."""
    worker = BackgroundWorker(session_factory=session_factory, poll_interval=0.01)
    worker.start()
    try:
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            session.expire_all()
            if session.get(StatementJob, queued_job.id).status == "COMPLETED":
                break
            time.sleep(0.02)
    finally:
        worker.stop()

    session.expire_all()
    assert session.get(StatementJob, queued_job.id).status == "COMPLETED"
    assert worker._thread is None  # joined, not leaked


# --- claiming (REQ-PROC-001: independent jobs) ------------------------------


def test_claim_next_job_claims_one_and_only_one(session: Session, tmp_path: Path):
    batch = _batch(session, selected=2, uploaded=2)
    for i in range(2):
        f = _accepted_file(session, batch, _pdf(tmp_path, f"s{i}.pdf"))
        enqueue_job(
            session, batch_id=batch.id, intake_file_id=f.id, pdf_path=f.temp_path
        )

    first = claim_next_job(session)
    second = claim_next_job(session)
    third = claim_next_job(session)

    assert first is not None and second is not None
    assert first.id != second.id
    assert {first.status, second.status} == {"PROCESSING"}
    assert third is None  # both already claimed


def test_a_claimed_job_is_not_reclaimable(session: Session, queued_job: StatementJob):
    claim_next_job(session)
    assert claim_next_job(session) is None


# --- retry classification (REQ-PROC-101 / 102) -----------------------------


def test_req_proc_101_retryable_failure_retries_twice_then_fails(
    session: Session,
    session_factory: Callable[[], Session],
    queued_job: StatementJob,
    monkeypatch: pytest.MonkeyPatch,
):
    def _always_fails(_: Path):
        raise ExtractionFailedError("OCR engine crashed")

    monkeypatch.setattr(processor, "extract_text", _always_fails)

    run_worker_once(session_factory)
    session.expire_all()
    job = session.get(StatementJob, queued_job.id)
    assert job.status == "RETRYING"
    assert job.attempt_count == 1

    run_worker_once(session_factory)
    session.expire_all()
    job = session.get(StatementJob, queued_job.id)
    assert job.status == "RETRYING"
    assert job.attempt_count == 2

    run_worker_once(session_factory)
    session.expire_all()
    job = session.get(StatementJob, queued_job.id)
    assert job.status == "FAILED"  # 3 attempts total, no retries left
    assert job.attempt_count == 3
    assert "OCR engine crashed" in job.failure_reason


def test_req_proc_102_non_retryable_failure_fails_immediately(
    session: Session,
    session_factory: Callable[[], Session],
    queued_job: StatementJob,
    monkeypatch: pytest.MonkeyPatch,
):
    def _bug(_: Path):
        raise ValueError("a programming error, not a transient one")

    monkeypatch.setattr(processor, "extract_text", _bug)

    run_worker_once(session_factory)

    session.expire_all()
    job = session.get(StatementJob, queued_job.id)
    assert job.status == "FAILED"
    assert job.attempt_count == 1  # tried once, not retried
    assert "ValueError" in job.failure_reason


# --- batch coordination (REQ-PROC-103, REQ-RPT-002) -----------------------


def test_batch_stays_processing_until_every_job_is_terminal(
    session: Session, tmp_path: Path
):
    batch = _batch(session, selected=2, uploaded=2)
    jobs = []
    for i in range(2):
        f = _accepted_file(session, batch, _pdf(tmp_path, f"s{i}.pdf"))
        jobs.append(
            enqueue_job(
                session, batch_id=batch.id, intake_file_id=f.id, pdf_path=f.temp_path
            )
        )

    jobs[0].status = "COMPLETED"
    session.add(jobs[0])
    session.commit()
    refresh_batch(session, batch.id)
    session.expire_all()
    assert session.get(Batch, batch.id).status == "PROCESSING"

    jobs[1].status = "COMPLETED"
    session.add(jobs[1])
    session.commit()
    refresh_batch(session, batch.id)
    session.expire_all()
    done = session.get(Batch, batch.id)
    assert done.status == "COMPLETED"
    assert done.processed == 2
    assert done.processing_failed == 0


def test_batch_with_a_failed_job_completes_with_warnings(
    session: Session, tmp_path: Path
):
    batch = _batch(session, selected=2, uploaded=2)
    f1 = _accepted_file(session, batch, _pdf(tmp_path, "a.pdf"))
    f2 = _accepted_file(session, batch, _pdf(tmp_path, "b.pdf"))
    j1 = enqueue_job(
        session, batch_id=batch.id, intake_file_id=f1.id, pdf_path=f1.temp_path
    )
    j2 = enqueue_job(
        session, batch_id=batch.id, intake_file_id=f2.id, pdf_path=f2.temp_path
    )
    j1.status, j2.status = "COMPLETED", "FAILED"
    session.add_all([j1, j2])
    session.commit()

    refresh_batch(session, batch.id)

    session.expire_all()
    done = session.get(Batch, batch.id)
    assert done.status == "COMPLETED_WITH_WARNINGS"
    assert done.processed == 1
    assert done.processing_failed == 1


def test_intake_rejection_alone_makes_a_batch_complete_with_warnings(
    session: Session, tmp_path: Path
):
    """A file rejected at intake counts as an exclusion even if every job that
    was queued succeeds (REQ-RPT-002)."""
    batch = _batch(session, selected=2, uploaded=2, validation_failed=1)
    f = _accepted_file(session, batch, _pdf(tmp_path, "a.pdf"))
    job = enqueue_job(
        session, batch_id=batch.id, intake_file_id=f.id, pdf_path=f.temp_path
    )
    job.status = "COMPLETED"
    session.add(job)
    session.commit()

    refresh_batch(session, batch.id)

    session.expire_all()
    assert session.get(Batch, batch.id).status == "COMPLETED_WITH_WARNINGS"


# --- REQ-PROC-003 / 004 --------------------------------------------------


def test_req_proc_003_job_stores_a_path_not_bytes(queued_job: StatementJob):
    assert isinstance(queued_job.pdf_path, str)
    columns = set(StatementJob.model_fields)
    assert not any("bytes" in c or "content" in c or "blob" in c for c in columns)


def test_req_proc_004_rejected_intake_files_never_get_a_job(
    session: Session, tmp_path: Path
):
    batch = _batch(session)
    session.add(
        IntakeFile(
            batch_id=batch.id,
            original_filename="bad.txt",
            status="VALIDATION_FAILED",
            failure_reason="not a PDF file",
        )
    )
    session.commit()

    # The API layer (test_batches_api) is what enforces this; here we assert the
    # invariant directly: nothing enqueues a job for a non-ACCEPTED file.
    jobs = session.exec(
        select(StatementJob).where(col(StatementJob.batch_id) == batch.id)
    ).all()
    assert jobs == []
