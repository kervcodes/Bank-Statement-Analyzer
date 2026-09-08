"""Parser for Santander (formerly Sovereign) personal checking statements.

Layout notes (v1, statements dated 2025-2026):

- The PDF is a *combined* statement: a "SIMPLY RIGHT CHECKING" section followed by
  a "SANTANDER SAVINGS" section. This parser reads the **checking** section only;
  the savings section is out of scope for v1 (it carries near-zero activity in
  practice, and one job maps to one `Statement`).
- Native embedded text always -- these are e-statements, never scanned. `parse`
  rejects an OCR result rather than guessing at column positions.
- The transaction table has fixed columns: Date | Description | Additions
  (credits) | Subtractions (debits) | Balance. Column membership is read from the
  x-position of each amount token (the columns are far apart), and every row is
  cross-checked against the running balance -- a row whose printed balance
  doesn't follow from the previous balance +/- the amount is a `ParserError`,
  not a silent guess.
- A negative (overdraft) balance is printed as ``-$92.38``.
"""

import re
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

import pdfplumber

from app.parsers.base import (
    ParsedStatement,
    ParsedTransaction,
    ParserError,
)
from app.parsers.registry import register
from app.services.extraction import ExtractionResult, PageText

bank = "Santander"
account_type = "checking"
layout_version = "v1"
parser_version = "santander_checking_v1"

# --- detection -------------------------------------------------------------

_DETECT_MARKERS: list[tuple[re.Pattern[str], float]] = [
    (re.compile(r"santanderbank\.com|Santander Bank, ?N\.A\.", re.IGNORECASE), 0.35),
    (re.compile(r"SIMPLY RIGHT CHECKING", re.IGNORECASE), 0.35),
    (re.compile(r"Deposits/Credits.*Withdrawals/Debits", re.DOTALL), 0.20),
    (re.compile(r"Date\s+Description\s+Additions\s+Subtractions\s+Balance"), 0.10),
]


def detect(pages: list[PageText]) -> float:
    text = "\n".join(p.text for p in pages)
    score = sum(weight for pattern, weight in _DETECT_MARKERS if pattern.search(text))
    return min(score, 1.0)


# --- parsing -------------------------------------------------------------

_DATE_TOKEN = re.compile(r"^\d\d-\d\d$")
_MONEY_TOKEN = re.compile(r"^-?\$[\d,]+\.\d\d$")

# x-position bands for the amount columns (points from the left edge). The gaps
# between the real columns are wide (~380 / ~460 / ~520), so the exact cutoffs
# are not delicate.
_CREDIT_MAX_X = 425.0
_DEBIT_MAX_X = 505.0

_PERIOD = re.compile(r"Statement Period (\d\d)/(\d\d)/(\d\d) TO (\d\d)/(\d\d)/(\d\d)")
_CHECKING_SUMMARY = re.compile(
    r"SIMPLY RIGHT CHECKING Statement Period.*?"
    r"Account # (?P<acct>\d+)\s*\n\s*Balances\s*\n\s*"
    r"Beginning Balance \$(?P<open>[\d,]+\.\d\d) "
    r"Current Balance (?P<close>-?\$[\d,]+\.\d\d)\s*\n\s*"
    r"Deposits/Credits \+\$(?P<credits>[\d,]+\.\d\d).*?\n\s*"
    r"Withdrawals/Debits -\$(?P<debits>[\d,]+\.\d\d)",
    re.DOTALL,
)


def _money(token: str) -> Decimal:
    negative = token.lstrip().startswith("-")
    value = Decimal(re.sub(r"[^\d.]", "", token))
    return -value if negative else value


def _resolve_date(mm: int, dd: int, start: date, end: date) -> date:
    """Attach a year to an MM-DD activity date. Statements are single-period; the
    year is the period's year, disambiguated only if the period straddles a year
    boundary."""
    for year in {start.year, end.year}:
        try:
            candidate = date(year, mm, dd)
        except ValueError:
            continue
        if start <= candidate <= end:
            return candidate
    # Nothing landed in the period -- keep the period's start year and let
    # transaction-level validation flag the out-of-range date.
    return date(start.year, mm, dd)


def _normalize_description(raw: str) -> str:
    text = re.sub(r"\s+", " ", raw).strip()
    text = re.sub(r"\s+REF\*[\w\\*]+\\?$", "", text)
    text = re.sub(r"\s+\d{6}$", "", text)  # trailing posting date, e.g. "250903"
    return text.strip()


def _cluster_rows(words: list[dict], tol: float = 3.0) -> list[list[dict]]:
    rows: list[tuple[float, list[dict]]] = []
    for w in sorted(words, key=lambda w: (w["top"], w["x0"])):
        if rows and abs(w["top"] - rows[-1][0]) <= tol:
            rows[-1][1].append(w)
        else:
            rows.append((w["top"], [w]))
    return [sorted(chunk, key=lambda w: w["x0"]) for _, chunk in rows]


class _RawRow:
    __slots__ = ("balance", "credit", "date_token", "debit", "description", "page")

    def __init__(self, date_token: str, page: int) -> None:
        self.date_token = date_token
        self.description: list[str] = []
        self.credit: Decimal | None = None
        self.debit: Decimal | None = None
        self.balance: Decimal | None = None
        self.page = page


def _collect_checking_rows(pdf: pdfplumber.PDF, account_number: str) -> list[_RawRow]:
    """Walk the pages and pull the checking-section activity rows in order.

    State machine: `pre` -> (see the checking summary header) -> `in` (inside the
    checking Account Activity table) -> stop at the savings section or a
    continuation header for a different account.
    """
    rows: list[_RawRow] = []
    state = "pre"
    current: _RawRow | None = None

    for page_number, page in enumerate(pdf.pages, start=1):
        for line in _cluster_rows(page.extract_words()):
            text = " ".join(w["text"] for w in line)

            if state == "pre":
                if "SIMPLY RIGHT CHECKING Statement Period" in text:
                    state = "saw_summary"
                continue
            if state == "saw_summary":
                # The checking activity table opens with an "Account Activity"
                # heading and/or the column header row.
                if re.match(r"Account Activity", text) or text.startswith(
                    "Date Description Additions"
                ):
                    state = "in"
                continue

            # state == "in"
            if text.startswith("SANTANDER SAVINGS") or (
                "Cont. for Acct#" in text and account_number not in text
            ):
                return rows
            if re.match(r"Account Activity", text):
                continue  # a "(Cont. for Acct# <checking>)" header -- stay in
            if text.startswith(("Date Description", "Page ")):
                continue

            first = line[0]
            is_new_row = bool(_DATE_TOKEN.match(first["text"])) and first["x0"] < 80

            if is_new_row:
                current = _RawRow(first["text"], page_number)
                for w in line[1:]:
                    if _MONEY_TOKEN.match(w["text"]):
                        value = _money(w["text"])
                        if w["x0"] < _CREDIT_MAX_X:
                            current.credit = value
                        elif w["x0"] < _DEBIT_MAX_X:
                            current.debit = value
                        else:
                            current.balance = value
                    else:
                        current.description.append(w["text"])
                joined = " ".join(current.description)
                if joined.startswith(("Beginning Balance", "Ending Balance")):
                    current = None  # bracket rows, not transactions
                    continue
                rows.append(current)
            elif current is not None and not any(
                _MONEY_TOKEN.match(w["text"]) and w["x0"] > _CREDIT_MAX_X for w in line
            ):
                # a wrapped description continuation line
                current.description.extend(w["text"] for w in line)

    return rows


def _build_transactions(
    raw_rows: list[_RawRow], *, opening: Decimal, start: date, end: date
) -> list[ParsedTransaction]:
    transactions: list[ParsedTransaction] = []
    running = opening

    for index, row in enumerate(raw_rows):
        if (row.credit is None) == (row.debit is None):
            raise ParserError(
                f"row {index} ('{' '.join(row.description)[:40]}') has "
                f"{'both' if row.credit is not None else 'no'} amount columns"
            )

        if row.credit is not None:
            amount, direction = row.credit, "CREDIT"
            running += amount
        else:
            amount, direction = row.debit, "DEBIT"  # type: ignore[assignment]
            running -= amount

        if row.balance is not None and row.balance != running:
            raise ParserError(
                f"row {index} ('{' '.join(row.description)[:40]}'): running "
                f"balance {running} does not match printed balance {row.balance}"
            )

        mm, dd = (int(part) for part in row.date_token.split("-"))
        txn_date = _resolve_date(mm, dd, start, end)
        raw = " ".join(row.description)
        transactions.append(
            ParsedTransaction(
                transaction_date=txn_date,
                posted_date=txn_date,
                description_raw=raw,
                description_normalized=_normalize_description(raw),
                amount=amount,
                direction=direction,
                balance_after=row.balance,
                source_page=row.page,
            )
        )

    return transactions


def parse(pdf_path: Path, extraction: ExtractionResult) -> ParsedStatement:
    if extraction.method != "NATIVE":
        raise ParserError(
            "santander_checking_v1 needs native text; this statement required OCR"
        )

    full_text = "\n".join(p.text for p in extraction.pages)

    period = _PERIOD.search(full_text)
    summary = _CHECKING_SUMMARY.search(full_text)
    if period is None or summary is None:
        raise ParserError(
            "could not locate the statement period / checking summary block"
        )

    start = date(
        2000 + int(period.group(3)), int(period.group(1)), int(period.group(2))
    )
    end = date(2000 + int(period.group(6)), int(period.group(4)), int(period.group(5)))
    account_number = summary.group("acct")
    opening = _money(summary.group("open"))
    closing = _money(summary.group("close"))
    summary_credits = _money(summary.group("credits"))
    summary_debits = _money(summary.group("debits"))

    with pdfplumber.open(pdf_path) as pdf:
        raw_rows = _collect_checking_rows(pdf, account_number)

    transactions = _build_transactions(raw_rows, opening=opening, start=start, end=end)

    # Cross-check the parsed rows against the statement's own printed totals.
    # A mismatch means a row was missed or misread -- a parser problem, not a
    # statement that fails to reconcile (that is validation's job).
    parsed_credits = sum(
        (t.amount for t in transactions if t.direction == "CREDIT"), Decimal(0)
    )
    parsed_debits = sum(
        (t.amount for t in transactions if t.direction == "DEBIT"), Decimal(0)
    )
    if parsed_credits != summary_credits or parsed_debits != summary_debits:
        raise ParserError(
            f"parsed totals (credits {parsed_credits}, debits {parsed_debits}) "
            f"do not match the statement summary (credits {summary_credits}, "
            f"debits {summary_debits})"
        )

    return ParsedStatement(
        bank=bank,
        account_type=account_type,
        account_identifier_masked=account_number[-4:],
        statement_start_date=start,
        statement_end_date=end,
        opening_balance=opening,
        closing_balance=closing,
        parser_version=parser_version,
        transactions=transactions,
        unreadable_pages=[],
    )


# This module *is* the parser: it has the required attributes and functions, so
# it satisfies the `Parser` protocol structurally.
register(sys.modules[__name__])
