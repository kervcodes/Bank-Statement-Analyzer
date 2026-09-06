from pathlib import Path

import pytest
from _pdf import build_pdf as _build_pdf
from PIL import Image, ImageDraw, ImageFont

from app.services import extraction
from app.services.extraction import ExtractionFailedError, extract_text


def _scanned_pdf_bytes(text: str) -> bytes:
    """An image-only PDF page (no text layer at all) -- forces the OCR path."""
    from io import BytesIO

    image = Image.new("L", (800, 200), color=255)
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=40)
    draw.text((20, 60), text, fill=0, font=font)
    buf = BytesIO()
    image.save(buf, "PDF")
    return buf.getvalue()


def test_native_text_pdf_uses_native_path(tmp_path: Path):
    pdf_path = tmp_path / "native.pdf"
    pdf_path.write_bytes(
        _build_pdf(["REQ EXT NATIVE PATH SAMPLE STATEMENT TEXT FORTY CHARS MIN"])
    )

    result = extract_text(pdf_path)

    assert result.method == "NATIVE"
    assert len(result.pages) == 1
    assert result.pages[0].page_number == 1
    assert "NATIVE PATH SAMPLE STATEMENT" in result.pages[0].text


def test_scanned_pdf_falls_back_to_ocr(tmp_path: Path):
    pdf_path = tmp_path / "scanned.pdf"
    pdf_path.write_bytes(_scanned_pdf_bytes("HELLO SCANNED STATEMENT"))

    result = extract_text(pdf_path)

    assert result.method == "OCR"
    assert len(result.pages) == 1
    assert "HELLO SCANNED STATEMENT" in result.pages[0].text


def test_one_unreadable_page_sends_whole_document_to_ocr(tmp_path: Path):
    """Decision: a document is never split between native and OCR per page."""
    pdf_path = tmp_path / "mixed.pdf"
    pdf_path.write_bytes(
        _build_pdf(
            ["PAGE ONE HAS PLENTY OF REAL EXTRACTABLE NATIVE TEXT CONTENT", None]
        )
    )

    result = extract_text(pdf_path)

    assert result.method == "OCR"
    assert len(result.pages) == 2


def test_ocr_failure_raises_instead_of_returning_partial_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """REQ-EXT-004: an OCR failure is a hard failure, never partial/garbled text."""
    pdf_path = tmp_path / "scanned.pdf"
    pdf_path.write_bytes(_scanned_pdf_bytes("ANY TEXT"))

    def _broken_ocr(*args, **kwargs):
        raise RuntimeError("tesseract crashed")

    monkeypatch.setattr(extraction.pytesseract, "image_to_string", _broken_ocr)

    with pytest.raises(ExtractionFailedError):
        extract_text(pdf_path)
