"""Build-plan #6: bank detection. Traces to REQ-DET-001 / REQ-DET-002."""

from _pdf import build_positioned_pdf
from _santander_sample import build_santander_sample

from app.services.detection import CONFIDENCE_THRESHOLD, detect
from app.services.extraction import PageText, extract_text


def _pages(*texts: str) -> list[PageText]:
    return [PageText(page_number=i, text=t) for i, t in enumerate(texts, start=1)]


def test_req_det_001_recognizes_a_santander_checking_statement(tmp_path):
    path = tmp_path / "s.pdf"
    path.write_bytes(build_santander_sample())

    result = detect(extract_text(path).pages)

    assert (result.bank, result.account_type, result.layout_version) == (
        "Santander",
        "checking",
        "v1",
    )
    assert result.confidence >= CONFIDENCE_THRESHOLD
    assert result.is_supported


def test_req_det_002_a_non_santander_statement_is_below_threshold():
    result = detect(
        _pages(
            "CHASE  Statement of account\n"
            "Beginning balance / Ending balance\n"
            "Deposits and additions ... Electronic withdrawals"
        )
    )

    assert result.confidence < CONFIDENCE_THRESHOLD
    assert not result.is_supported


def test_detection_ignores_the_filename(tmp_path):
    """A Santander statement in a file named like a Chase one still detects as
    Santander -- detection reads content, never the name (REQ-DET-001)."""
    path = tmp_path / "chase_2026_january.pdf"
    path.write_bytes(build_santander_sample())

    assert detect(extract_text(path).pages).bank == "Santander"


def test_empty_text_is_unsupported_not_a_crash():
    result = detect(_pages("", "   "))

    assert result.confidence == 0.0
    assert not result.is_supported


def test_an_unrelated_pdf_detects_as_unsupported(tmp_path):
    path = tmp_path / "receipt.pdf"
    path.write_bytes(
        build_positioned_pdf(
            [[(72.0, 720.0, "Grocery receipt total 42.10 thank you for shopping")]]
        )
    )

    assert not detect(extract_text(path).pages).is_supported
