"""Build-plan #6: the santander_checking_v1 parser against a synthetic statement
built to mirror the real layout. Traces to REQ-DET-003, REQ-NORM-002/003, and
NFR-MAINT-001 (a parser regression test per layout)."""

from decimal import Decimal

import pytest
from _santander_sample import (
    EXPECTED_ACCOUNT_MASKED,
    EXPECTED_CLOSING,
    EXPECTED_FIRST_DESCRIPTION_RAW,
    EXPECTED_MULTILINE_DESCRIPTION_RAW,
    EXPECTED_OPENING,
    EXPECTED_TOTAL_CREDITS,
    EXPECTED_TOTAL_DEBITS,
    EXPECTED_TRANSACTION_COUNT,
    build_santander_sample,
)

from app.parsers import get_parser
from app.parsers.base import ParserError
from app.services.extraction import extract_text


def _parse(pdf_bytes: bytes, tmp_path):
    path = tmp_path / "s.pdf"
    path.write_bytes(pdf_bytes)
    extraction = extract_text(path)
    parser = get_parser("Santander", "checking", "v1")
    return parser.parse(path, extraction)


def test_parses_statement_metadata(tmp_path):
    parsed = _parse(build_santander_sample(), tmp_path)

    assert parsed.bank == "Santander"
    assert parsed.account_type == "checking"
    assert parsed.parser_version == "santander_checking_v1"
    assert parsed.account_identifier_masked == EXPECTED_ACCOUNT_MASKED
    assert parsed.statement_start_date.isoformat() == "2026-03-01"
    assert parsed.statement_end_date.isoformat() == "2026-03-31"
    assert parsed.opening_balance == EXPECTED_OPENING
    assert parsed.closing_balance == EXPECTED_CLOSING


def test_parses_every_transaction_with_the_right_direction(tmp_path):
    parsed = _parse(build_santander_sample(), tmp_path)

    assert len(parsed.transactions) == EXPECTED_TRANSACTION_COUNT

    credits = sum(
        (t.amount for t in parsed.transactions if t.direction == "CREDIT"), Decimal(0)
    )
    debits = sum(
        (t.amount for t in parsed.transactions if t.direction == "DEBIT"), Decimal(0)
    )
    assert credits == EXPECTED_TOTAL_CREDITS
    assert debits == EXPECTED_TOTAL_DEBITS
    # every amount is stored positive; direction carries the sign (REQ-NORM-003)
    assert all(t.amount > 0 for t in parsed.transactions)


def test_running_balance_is_continuous_including_an_overdraft(tmp_path):
    parsed = _parse(build_santander_sample(), tmp_path)

    running = parsed.opening_balance
    for txn in parsed.transactions:
        running += txn.amount if txn.direction == "CREDIT" else -txn.amount
        assert txn.balance_after == running

    # the Zelle transfer overdraws the account
    overdrawn = [
        t for t in parsed.transactions if t.balance_after and t.balance_after < 0
    ]
    assert overdrawn and overdrawn[0].balance_after == Decimal("-145.99")


def test_multi_line_description_is_joined_and_raw_is_preserved(tmp_path):
    parsed = _parse(build_santander_sample(), tmp_path)

    assert parsed.transactions[0].description_raw == EXPECTED_FIRST_DESCRIPTION_RAW

    wrapped = next(
        t for t in parsed.transactions if t.description_raw.startswith("Zelle")
    )
    assert wrapped.description_raw == EXPECTED_MULTILINE_DESCRIPTION_RAW


def test_transactions_carry_a_source_page(tmp_path):
    parsed = _parse(build_santander_sample(), tmp_path)

    assert {t.source_page for t in parsed.transactions} == {1, 2}


def test_savings_section_is_not_parsed_into_the_checking_statement(tmp_path):
    """The synthetic statement has a SANTANDER SAVINGS section with a $999.00
    interest credit. If it leaked in, the parsed totals would not match the
    checking summary and the parser would raise."""
    parsed = _parse(build_santander_sample(), tmp_path)

    assert all("INTEREST PAYMENT" not in t.description_raw for t in parsed.transactions)


def test_an_ocr_result_is_rejected(tmp_path):
    from app.services.extraction import ExtractionResult, PageText

    parser = get_parser("Santander", "checking", "v1")
    ocr = ExtractionResult(
        pages=[PageText(page_number=1, text="whatever")], method="OCR"
    )

    with pytest.raises(ParserError, match="native text"):
        parser.parse(tmp_path / "unused.pdf", ocr)


def test_a_missing_summary_block_raises_parser_error(tmp_path):
    from _pdf import build_positioned_pdf

    path = tmp_path / "broken.pdf"
    path.write_bytes(
        build_positioned_pdf(
            [
                [
                    (
                        54.0,
                        720.0,
                        "SIMPLY RIGHT CHECKING Statement Period 03/01/26 - 03/31/26",
                    )
                ]
            ]
        )
    )

    parser = get_parser("Santander", "checking", "v1")
    with pytest.raises(ParserError):
        parser.parse(path, extract_text(path))
