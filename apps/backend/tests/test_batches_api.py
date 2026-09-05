from io import BytesIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfWriter
from sqlmodel import Session, select

import app.api.batches as batches_module
from app.db import get_db_session
from app.main import app
from app.models import IntakeFile


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
