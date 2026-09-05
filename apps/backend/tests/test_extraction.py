from pathlib import Path

import pytest
from PIL import Image, ImageDraw, ImageFont

from app.services import extraction
from app.services.extraction import ExtractionFailedError, extract_text


def _build_pdf(
    page_texts: list[str | None], page_size: tuple[int, int] = (400, 200)
) -> bytes:
    """Hand-build a minimal, valid multi-page PDF with real extractable text.

    No PDF-writing library is a dependency here (build-plan #3 already added
    `pypdf`, but it has no text-drawing API), so this writes the object graph
    and xref table directly -- a `None` entry produces a page with an empty
    content stream (no text at all), for testing the mixed-document case.
    """
    n_pages = len(page_texts)
    font_obj_num = 3
    page_obj_nums = [4 + 2 * i for i in range(n_pages)]
    content_obj_nums = [n + 1 for n in page_obj_nums]

    kids = " ".join(f"{n} 0 R" for n in page_obj_nums)
    objects: dict[int, bytes] = {
        1: b"<< /Type /Catalog /Pages 2 0 R >>",
        2: f"<< /Type /Pages /Kids [{kids}] /Count {n_pages} >>".encode(),
        font_obj_num: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    }
    for i, text in enumerate(page_texts):
        page_num = page_obj_nums[i]
        content_num = content_obj_nums[i]
        content = f"BT /F1 12 Tf 20 100 Td ({text}) Tj ET".encode() if text else b""
        objects[page_num] = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {page_size[0]} {page_size[1]}] "
            f"/Resources << /Font << /F1 {font_obj_num} 0 R >> >> "
            f"/Contents {content_num} 0 R >>"
        ).encode()
        objects[content_num] = (
            f"<< /Length {len(content)} >>\nstream\n".encode()
            + content
            + b"\nendstream"
        )

    max_obj = max(objects)
    buf = bytearray(b"%PDF-1.4\n")
    offsets: dict[int, int] = {}
    for i in range(1, max_obj + 1):
        offsets[i] = len(buf)
        buf += f"{i} 0 obj\n".encode() + objects[i] + b"\nendobj\n"

    xref_offset = len(buf)
    buf += f"xref\n0 {max_obj + 1}\n".encode()
    buf += b"0000000000 65535 f \n"
    for i in range(1, max_obj + 1):
        buf += f"{offsets[i]:010d} 00000 n \n".encode()
    buf += b"trailer\n"
    buf += f"<< /Size {max_obj + 1} /Root 1 0 R >>\n".encode()
    buf += f"startxref\n{xref_offset}\n%%EOF".encode()
    return bytes(buf)


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
