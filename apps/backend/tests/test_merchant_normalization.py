"""Build-plan #8 Part 1: merchant normalization (REQ-CAT-002)."""

import pytest

from app.services.merchant_normalization import normalize_merchant


@pytest.mark.parametrize(
    ("description", "expected"),
    [
        # REQ-CAT-002: the two shapes of the same merchant collapse.
        ("UBER *TRIP HELP.UBER.COM", "Uber"),
        ("UBER   TECHNOLOGIES", "Uber"),
        # real-shaped Santander card-purchase lines
        ("AMAZON.COM*A1B2 SEATTLE /WA US CARD PURCHASE", "Amazon"),
        ("STARBUCKS STORE 555 BOSTON /MA US CARD PURCHASE", "Starbucks"),
        ("SHELL OIL STOUGHTON /MA US CARD PURCHASE", "Shell"),
        ("NETFLIX.COM CARD PURCHASE", "Netflix"),
        ("POS DEBIT WALMART SUPERCENTER #1234 CHICAGO IL", "Walmart"),
        # processor prefixes
        ("SQ *BLUE BOTTLE COFFEE", "Blue Bottle Coffee"),
        ("TST* THE CORNER CAFE 12345", "The Corner Cafe"),
        # a P2P line drops the counterparty's name (privacy + stability)
        ("Zelle Transfer to JOHN DOE 877-000-1111 PAYMENT", "Zelle"),
        ("VENMO PAYMENT 1017283746", "Venmo"),
        # payroll / direct deposit → the payer, channel words removed
        ("PAYROLL DEPOSIT ACME CORP", "Acme Corp"),
        ("DIRECT DEP GOOGLE LLC", "Google Llc"),
        # unknown merchant: cleaned but still recognizable, never empty
        ("ELECTRIC COMPANY AUTO PYMT 260317", "Electric Company"),
    ],
)
def test_normalize_merchant(description: str, expected: str):
    assert normalize_merchant(description) == expected


def test_blank_input_returns_empty():
    assert normalize_merchant("") == ""
    assert normalize_merchant("   ") == ""


def test_is_deterministic():
    line = "AMAZON.COM*Z9 SEATTLE /WA US CARD PURCHASE"
    assert normalize_merchant(line) == normalize_merchant(line)
