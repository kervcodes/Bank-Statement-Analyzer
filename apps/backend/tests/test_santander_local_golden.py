"""Golden parse of the real Santander statements in
``tests/fixtures/statements/local/``.

Those PDFs are gitignored and never in CI, so this whole module skips when the
folder is empty. On a machine that has them, it is the strongest check in the
suite: every real statement must parse, its running balance must be continuous,
and the parsed transaction totals must match the statement's own printed summary
(NFR-MAINT-001).
"""

from decimal import Decimal
from pathlib import Path

import pytest

from app.parsers import get_parser
from app.services.extraction import extract_text

_LOCAL_DIR = Path(__file__).parent / "fixtures" / "statements" / "local"
_REAL_STATEMENTS = sorted(_LOCAL_DIR.glob("*.pdf"))

pytestmark = pytest.mark.skipif(
    not _REAL_STATEMENTS,
    reason="no real statements in tests/fixtures/statements/local/",
)


@pytest.mark.parametrize("pdf_path", _REAL_STATEMENTS, ids=lambda p: p.name)
def test_real_statement_parses_and_reconciles(pdf_path: Path):
    parser = get_parser("Santander", "checking", "v1")
    parsed = parser.parse(pdf_path, extract_text(pdf_path))

    assert parsed.transactions, "no transactions parsed"

    running = parsed.opening_balance
    for txn in parsed.transactions:
        running += txn.amount if txn.direction == "CREDIT" else -txn.amount
        if txn.balance_after is not None:
            assert txn.balance_after == running, (
                f"balance breaks at {txn.description_raw!r}"
            )

    credits = sum(
        (t.amount for t in parsed.transactions if t.direction == "CREDIT"), Decimal(0)
    )
    debits = sum(
        (t.amount for t in parsed.transactions if t.direction == "DEBIT"), Decimal(0)
    )
    assert parsed.opening_balance + credits - debits == parsed.closing_balance
    assert len(parsed.account_identifier_masked) == 4
