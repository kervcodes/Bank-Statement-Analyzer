from io import BytesIO

import pytest
from pypdf import PdfWriter

from app.services import intake_validation
from app.services.intake_validation import validate_pdf


def _pdf_bytes(pages: int = 1, user_password: str | None = None) -> bytes:
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=200, height=200)
    if user_password is not None:
        writer.encrypt(user_password=user_password, owner_password="owner-secret")
    buf = BytesIO()
    writer.write(buf)
    return buf.getvalue()


def test_valid_pdf_is_accepted():
    result = validate_pdf("statement.pdf", _pdf_bytes())

    assert result.accepted is True
    assert result.failure_reason is None
    assert result.page_count == 1


def test_non_pdf_extension_is_rejected():
    result = validate_pdf("statement.txt", _pdf_bytes())

    assert result.accepted is False
    assert result.failure_reason == "not a PDF file"


def test_corrupted_pdf_is_rejected():
    result = validate_pdf("statement.pdf", b"this is not a real pdf")

    assert result.accepted is False
    assert result.failure_reason == "corrupted PDF"


def test_password_protected_pdf_is_rejected():
    encrypted = _pdf_bytes(user_password="secret")

    result = validate_pdf("statement.pdf", encrypted)

    assert result.accepted is False
    assert result.failure_reason == "password-protected"


def test_owner_only_encryption_is_accepted():
    """A PDF encrypted only to restrict printing/copying, with an empty user
    password, opens without a password prompt and isn't what REQ-INT-003
    means by "password-protected"."""
    owner_locked = _pdf_bytes(user_password="")

    result = validate_pdf("statement.pdf", owner_locked)

    assert result.accepted is True
    assert result.failure_reason is None


def test_oversized_file_is_rejected(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(intake_validation, "MAX_FILE_SIZE_BYTES", 10)

    result = validate_pdf("statement.pdf", _pdf_bytes())

    assert result.accepted is False
    assert "size limit" in result.failure_reason


def test_too_many_pages_is_rejected(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(intake_validation, "MAX_PAGE_COUNT", 1)

    result = validate_pdf("statement.pdf", _pdf_bytes(pages=2))

    assert result.accepted is False
    assert "page limit" in result.failure_reason
