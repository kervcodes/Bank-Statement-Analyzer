"""REQ-EXT-001/002/003: get page text out of a PDF, native or OCR, one contract.

Standalone service: takes a path to an already-validated PDF (build-plan #3)
and returns page text. Nothing here touches the job queue (build-plan #5) or
bank detection (build-plan #6).
"""

from dataclasses import dataclass
from pathlib import Path

import pdfplumber
import pytesseract
from pdf2image import convert_from_path

MIN_USABLE_TEXT_CHARS = 40


@dataclass(frozen=True)
class PageText:
    page_number: int  # 1-indexed
    text: str


@dataclass(frozen=True)
class ExtractionResult:
    pages: list[PageText]
    method: str  # "NATIVE" or "OCR"


class ExtractionFailedError(Exception):
    """REQ-EXT-004: an OCR failure is a hard failure, never partial/garbled text."""


def _has_usable_text(text: str) -> bool:
    return len(text.strip()) >= MIN_USABLE_TEXT_CHARS


def _extract_native(pdf_path: Path) -> list[PageText] | None:
    """Return per-page native text, or None if any page lacks usable text.

    REQ-EXT-002/decision: real bank statements are essentially never a mix of
    native and scanned pages. Rather than silently keep native text for some
    pages and drop the rest, one page failing sends the whole document to OCR.
    """
    pages: list[PageText] = []
    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            if not _has_usable_text(text):
                return None
            pages.append(PageText(page_number=i, text=text))
    return pages


def _extract_ocr(pdf_path: Path) -> list[PageText]:
    try:
        images = convert_from_path(str(pdf_path))
        return [
            PageText(page_number=i, text=pytesseract.image_to_string(image))
            for i, image in enumerate(images, start=1)
        ]
    except Exception as exc:
        # Any failure here (missing Tesseract binary, a corrupt render, an
        # OCR engine crash) means the same thing: this document cannot be
        # read. REQ-EXT-004 requires that surface as a clear failure, never
        # partial or garbled text.
        raise ExtractionFailedError(f"OCR failed for {pdf_path.name}: {exc}") from exc


def extract_text(pdf_path: Path) -> ExtractionResult:
    native_pages = _extract_native(pdf_path)
    if native_pages is not None:
        return ExtractionResult(pages=native_pages, method="NATIVE")

    ocr_pages = _extract_ocr(pdf_path)
    return ExtractionResult(pages=ocr_pages, method="OCR")
