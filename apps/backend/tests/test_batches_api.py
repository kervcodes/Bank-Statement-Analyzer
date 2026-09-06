from collections.abc import Callable
from io import BytesIO
from pathlib import Path

import pytest
from _pdf import NATIVE_TEXT_PAGE, build_pdf
from fastapi.testclient import TestClient
from pypdf import PdfWriter
from sqlmodel import Session, select

import app.api.batches as batches_module
from app.db import get_db_session
from app.main import app
from app.models import IntakeFile, StatementJob
from app.workers.pool import run_worker_once


def _pdf_bytes(pages: int = 1, user_password: str | None = None) -> bytes:
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=200, height=200)
    if user_password is not None:
        writer.encrypt(user_password=user_password, owner_password="owner-secret")
    buf = BytesIO()
    writer.write(buf)
    return buf.getvalue()


@pytest.fixture()
def client(session: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(batches_module, "TEMP_DIR", tmp_path)
    app.dependency_overrides[get_db_session] = lambda: session
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_mixed_batch_reports_distinct_per_file_statuses(
    client: TestClient, session: Session
):
    files = [
        ("files", ("chase_march.pdf", _pdf_bytes(), "application/pdf")),
        ("files", ("corrupted.pdf", b"not a real pdf", "application/pdf")),
        (
            "files",
            ("locked.pdf", _pdf_bytes(user_password="secret"), "application/pdf"),
        ),
        ("files", ("notes.txt", b"hello", "text/plain")),
    ]

    response = client.post("/batches", files=files)

    assert response.status_code == 200
    body = response.json()

    assert body["selected"] == 4
    assert body["uploaded"] == 4  # all four were received; validation runs after
    assert body["upload_failed"] == 0
    assert body["validation_failed"] == 3
    assert body["status"] == "PROCESSING"  # one file is ready for the queue

    by_filename = {f["filename"]: f for f in body["files"]}
    assert by_filename["chase_march.pdf"] == {
        "filename": "chase_march.pdf",
        "status": "ACCEPTED",
        "failure_reason": None,
    }
    assert by_filename["corrupted.pdf"]["status"] == "VALIDATION_FAILED"
    assert by_filename["corrupted.pdf"]["failure_reason"] == "corrupted PDF"
    assert by_filename["locked.pdf"]["status"] == "VALIDATION_FAILED"
    assert by_filename["locked.pdf"]["failure_reason"] == "password-protected"
    assert by_filename["notes.txt"]["status"] == "VALIDATION_FAILED"
    assert by_filename["notes.txt"]["failure_reason"] == "not a PDF file"

    stored = session.exec(
        select(IntakeFile).where(IntakeFile.batch_id == body["batch_id"])
    ).all()
    assert len(stored) == 4
    accepted = next(f for f in stored if f.status == "ACCEPTED")
    assert accepted.temp_path is not None
    assert Path(accepted.temp_path).read_bytes() == _pdf_bytes()
    rejected = [f for f in stored if f.status == "VALIDATION_FAILED"]
    assert all(f.temp_path is None for f in rejected)


def test_all_files_rejected_marks_batch_failed(client: TestClient):
    files = [("files", ("notes.txt", b"hello", "text/plain"))]

    response = client.post("/batches", files=files)

    body = response.json()
    assert body["status"] == "FAILED"
    assert body["validation_failed"] == 1
    assert body["uploaded"] == 1


def test_accepted_file_is_queued_and_processed_end_to_end(
    client: TestClient,
    session: Session,
    session_factory: Callable[[], Session],
):
    files = [
        (
            "files",
            ("chase_march.pdf", build_pdf([NATIVE_TEXT_PAGE]), "application/pdf"),
        ),
        ("files", ("notes.txt", b"hello", "text/plain")),
    ]
    post = client.post("/batches", files=files).json()
    batch_id = post["batch_id"]
    assert post["status"] == "PROCESSING"

    # REQ-PROC-004: exactly one job, for the accepted file only.
    jobs = session.exec(
        select(StatementJob).where(StatementJob.batch_id == batch_id)
    ).all()
    assert len(jobs) == 1

    assert run_worker_once(session_factory) is True
    session.expire_all()

    status = client.get(f"/batches/{batch_id}").json()
    assert status["status"] == "COMPLETED_WITH_WARNINGS"  # the .txt was rejected
    assert status["processed"] == 1
    assert len(status["jobs"]) == 1
    assert status["jobs"][0]["status"] == "COMPLETED"
    assert status["jobs"][0]["extraction_method"] == "NATIVE"


def test_get_batch_404_for_unknown_id(client: TestClient):
    assert client.get("/batches/does-not-exist").status_code == 404
