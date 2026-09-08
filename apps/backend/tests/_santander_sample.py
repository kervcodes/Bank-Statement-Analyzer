"""A synthetic Santander checking statement that mirrors the real layout.

Built to match the column geometry and section structure of the real statements
in ``tests/fixtures/statements/local/`` (which never enter the repo), so CI has a
representative fixture to run the parser against. ``build_santander_sample()``
returns PDF bytes; the ``EXPECTED_*`` constants are what a correct parse yields.

Set ``balanced=False`` to get a statement whose printed closing balance does not
follow from its own transactions -- it parses fine but fails financial
reconciliation (REQ-VAL-001).
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from _pdf import Token, build_positioned_pdf

# Fully fictional statement data -- no real name, account number, or address.
ACCOUNT_HOLDER = "JORDAN RIVERA"
ACCOUNT_NUMBER = "1234567890"
SAVINGS_ACCOUNT_NUMBER = "9999000099"
START = date(2026, 3, 1)
END = date(2026, 3, 31)
OPENING = Decimal("500.00")


@dataclass(frozen=True)
class _Txn:
    day: int
    description: list[str]  # one entry per visual line (first + continuations)
    amount: Decimal
    direction: str  # DEBIT | CREDIT


_TXNS: list[_Txn] = [
    _Txn(2, ["PAYROLL DEPOSIT ACME CORP"], Decimal("1200.00"), "CREDIT"),
    _Txn(
        3, ["AMAZON.COM*A1B2 SEATTLE /WA US CARD PURCHASE"], Decimal("45.99"), "DEBIT"
    ),
    _Txn(
        5,
        ["Zelle Transfer to JOHN DOE 877-000-1111", "PAYMENT"],
        Decimal("1800.00"),
        "DEBIT",
    ),
    _Txn(6, ["INTERNET TRANSFER FROM SAVINGS"], Decimal("300.00"), "CREDIT"),
    _Txn(
        10,
        ["STARBUCKS STORE 555 BOSTON /MA US CARD PURCHASE"],
        Decimal("22.50"),
        "DEBIT",
    ),
    _Txn(15, ["PAYROLL DEPOSIT ACME CORP"], Decimal("1500.00"), "CREDIT"),
    _Txn(18, ["ELECTRIC COMPANY AUTO PYMT 260317"], Decimal("120.00"), "DEBIT"),
    _Txn(20, ["SHELL OIL STOUGHTON /MA US CARD PURCHASE"], Decimal("60.00"), "DEBIT"),
    _Txn(25, ["NETFLIX.COM CARD PURCHASE"], Decimal("15.00"), "DEBIT"),
    _Txn(28, ["VENMO CASHOUT"], Decimal("63.49"), "CREDIT"),
]

# Column x-positions (points from the left edge), matching the real layout.
_X_DATE = 62.0
_X_DESC = 106.0
_X_CREDIT = 373.0
_X_DEBIT = 460.0
_X_BALANCE = 515.0

_ROWS_PER_PAGE = 5  # transactions 1-5 on page 1, 6-10 on page 2


def _fmt(amount: Decimal) -> str:
    negative = amount < 0
    body = f"${abs(amount):,.2f}"
    return f"-{body}" if negative else body


def _running_balances() -> list[Decimal]:
    balances: list[Decimal] = []
    running = OPENING
    for txn in _TXNS:
        running += txn.amount if txn.direction == "CREDIT" else -txn.amount
        balances.append(running)
    return balances


_BALANCES = _running_balances()
_TOTAL_CREDITS = sum((t.amount for t in _TXNS if t.direction == "CREDIT"), Decimal(0))
_TOTAL_DEBITS = sum((t.amount for t in _TXNS if t.direction == "DEBIT"), Decimal(0))
_TRUE_CLOSING = _BALANCES[-1]

EXPECTED_TRANSACTION_COUNT = len(_TXNS)
EXPECTED_OPENING = OPENING
EXPECTED_CLOSING = _TRUE_CLOSING
EXPECTED_TOTAL_CREDITS = _TOTAL_CREDITS
EXPECTED_TOTAL_DEBITS = _TOTAL_DEBITS
EXPECTED_ACCOUNT_MASKED = ACCOUNT_NUMBER[-4:]
EXPECTED_FIRST_DESCRIPTION_RAW = "PAYROLL DEPOSIT ACME CORP"
EXPECTED_MULTILINE_DESCRIPTION_RAW = "Zelle Transfer to JOHN DOE 877-000-1111 PAYMENT"


def _header_tokens(y: float, closing_shown: Decimal) -> list[Token]:
    """The page-1 header + financial summary + checking summary block."""
    lines = [
        "Statement Period 03/01/26 TO 03/31/26",
        "SIMPLY RIGHT CHECKING",
        "www.santanderbank.com",
        "Santander Bank, N.A. is a Member FDIC",
        ACCOUNT_HOLDER,
        "SIMPLY RIGHT CHECKING Statement Period 03/01/26 - 03/31/26",
        f"{ACCOUNT_HOLDER} Account # {ACCOUNT_NUMBER}",
        "Balances",
        f"Beginning Balance {_fmt(OPENING)} Current Balance {_fmt(closing_shown)}",
        f"Deposits/Credits +{_fmt(_TOTAL_CREDITS)} Average Daily Balance $123.45",
        f"Withdrawals/Debits -{_fmt(_TOTAL_DEBITS)}",
    ]
    tokens: list[Token] = []
    for i, text in enumerate(lines):
        tokens.append((54.0, y - i * 12.0, text))
    return tokens


def _activity_header(y: float) -> list[Token]:
    return [
        (_X_DATE, y, "Date"),
        (_X_DESC, y, "Description"),
        (_X_CREDIT, y, "Additions"),
        (_X_DEBIT, y, "Subtractions"),
        (_X_BALANCE, y, "Balance"),
    ]


def _txn_tokens(
    txn: _Txn, balance: Decimal, y: float, row_height: float
) -> list[Token]:
    tokens: list[Token] = [(_X_DATE, y, f"03-{txn.day:02d}")]
    # first description line beside the date, continuations on following rows
    for i, line in enumerate(txn.description):
        tokens.append((_X_DESC, y - i * row_height, line))
    amount_x = _X_CREDIT if txn.direction == "CREDIT" else _X_DEBIT
    tokens.append((amount_x, y, _fmt(txn.amount)))
    tokens.append((_X_BALANCE, y, _fmt(balance)))
    return tokens


def build_santander_sample(*, balanced: bool = True) -> bytes:
    closing_shown = _TRUE_CLOSING if balanced else _TRUE_CLOSING - Decimal("50.00")
    row_height = 11.0

    # --- page 1: header + summary + first chunk of activity ---
    page1: list[Token] = _header_tokens(720.0, closing_shown)
    y = 530.0
    page1.append((54.0, y, "Account Activity"))
    y -= row_height
    page1 += _activity_header(y)
    y -= row_height
    page1.append((_X_DATE, y, "03-01"))
    page1.append((_X_DESC, y, "Beginning Balance"))
    page1.append((_X_BALANCE, y, _fmt(OPENING)))
    y -= row_height
    for txn, balance in list(zip(_TXNS, _BALANCES, strict=True))[:_ROWS_PER_PAGE]:
        page1 += _txn_tokens(txn, balance, y, row_height)
        y -= row_height * len(txn.description)
    page1.append((_X_DATE, 40.0, "Page 1 of 2"))

    # --- page 2: continuation + rest of activity + ending + savings section ---
    page2: list[Token] = [
        (54.0, 730.0, f"Account Activity (Cont. for Acct# {ACCOUNT_NUMBER})")
    ]
    y = 700.0
    page2 += _activity_header(y)
    y -= row_height
    for txn, balance in list(zip(_TXNS, _BALANCES, strict=True))[_ROWS_PER_PAGE:]:
        page2 += _txn_tokens(txn, balance, y, row_height)
        y -= row_height * len(txn.description)
    page2.append((_X_DATE, y, "03-31"))
    page2.append((_X_DESC, y, "Ending Balance"))
    page2.append((_X_BALANCE, y, _fmt(_TRUE_CLOSING)))
    y -= row_height * 2
    # savings section -- the parser must stop before this. Its lone transaction
    # would corrupt the checking totals if it leaked in.
    page2.append((54.0, y, "SANTANDER SAVINGS Statement Period 03/01/26 - 03/31/26"))
    y -= row_height
    page2.append((54.0, y, f"{ACCOUNT_HOLDER} Account # {SAVINGS_ACCOUNT_NUMBER}"))
    y -= row_height
    page2 += _activity_header(y)
    y -= row_height
    page2 += [
        (_X_DATE, y, "03-15"),
        (_X_DESC, y, "INTEREST PAYMENT"),
        (_X_CREDIT, y, "$999.00"),
        (_X_BALANCE, y, "$999.00"),
    ]
    page2.append((_X_DATE, 40.0, "Page 2 of 2"))

    return build_positioned_pdf([page1, page2])
