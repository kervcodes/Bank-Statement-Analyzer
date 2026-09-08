"""The contract every parser implements and the canonical shape it produces.

`ParsedStatement` / `ParsedTransaction` are plain Pydantic models with `Decimal`
amounts -- the institution-neutral shape from techstack.md section 9. A parser
never touches the database; `app.services.normalization` is the only thing that
turns a `ParsedStatement` into `Statement` / `Transaction` / `Account` rows, and
the only place `Decimal` amounts become integer cents (so `SubCentPrecisionError`
is caught in exactly one place).
"""

from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Protocol, runtime_checkable

from pydantic import BaseModel

from app.services.extraction import ExtractionResult, PageText


class ParserError(Exception):
    """A deterministic parse failure (REQ-PROC-102).

    The layout was recognized but a field or a transaction row could not be read,
    or an internal consistency check failed (a running balance that doesn't
    follow, a transaction total that doesn't match the statement's own summary).
    Raising this rather than guessing keeps a half-read statement from becoming a
    `Statement` row (REQ-VAL-005). Not retried.
    """


class ParsedTransaction(BaseModel):
    transaction_date: date
    posted_date: date
    description_raw: str
    description_normalized: str
    amount: Decimal  # always positive; `direction` carries the sign (REQ-NORM-003)
    direction: str  # "DEBIT" | "CREDIT"
    balance_after: Decimal | None
    source_page: int  # 1-indexed (REQ-NORM-004)


class ParsedStatement(BaseModel):
    bank: str
    account_type: str
    account_identifier_masked: str  # last 4 digits only -- REQ-ACC-001
    statement_start_date: date
    statement_end_date: date
    opening_balance: Decimal
    closing_balance: Decimal
    parser_version: str
    transactions: list[ParsedTransaction]
    # Pages the parser could not read. Non-empty => Statement.extraction_status
    # becomes PARTIAL instead of SUCCESS (REQ-VAL-004).
    unreadable_pages: list[int] = []


@runtime_checkable
class Parser(Protocol):
    """What `registry` and `detection` expect from every parser module.

    `bank` / `account_type` / `layout_version` are the registry key.
    `parser_version` is what gets stored on the `Statement` row (REQ-DET-003) --
    conventionally `"{bank}_{account_type}_{layout_version}"` lowercased.
    """

    bank: str
    account_type: str
    layout_version: str
    parser_version: str

    def detect(self, pages: list[PageText]) -> float:
        """Confidence in [0.0, 1.0] that this parser owns these pages.

        Runs on extracted text only, never the filename (REQ-DET-001).
        """
        ...

    def parse(self, pdf_path: Path, extraction: ExtractionResult) -> ParsedStatement:
        """Turn a recognized statement into the canonical shape.

        Gets both the extracted text (`extraction`) and the PDF path, so a parser
        that needs column positions can re-open the file with pdfplumber.
        """
        ...
