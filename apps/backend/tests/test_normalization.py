"""Build-plan #6: normalization into the canonical schema + account resolution.
Traces to REQ-NORM-001/002/006 and REQ-ACC-001/002."""

from datetime import date
from decimal import Decimal

import pytest
from sqlmodel import Session, select

from app.models import Account, SubCentPrecisionError, Transaction
from app.parsers.base import ParsedStatement, ParsedTransaction
from app.services.normalization import normalize


def _parsed(
    *, masked: str = "6789", amount: str = "10.00", n: int = 1
) -> ParsedStatement:
    return ParsedStatement(
        bank="Santander",
        account_type="checking",
        account_identifier_masked=masked,
        statement_start_date=date(2026, 3, 1),
        statement_end_date=date(2026, 3, 31),
        opening_balance=Decimal("100.00"),
        closing_balance=Decimal("100.00") + Decimal(amount) * n,
        parser_version="santander_checking_v1",
        transactions=[
            ParsedTransaction(
                transaction_date=date(2026, 3, 2 + i),
                posted_date=date(2026, 3, 2 + i),
                description_raw=f"  RAW  DESC {i}  ",
                description_normalized=f"DESC {i}",
                amount=Decimal(amount),
                direction="CREDIT",
                balance_after=Decimal("100.00") + Decimal(amount) * (i + 1),
                source_page=1,
            )
            for i in range(n)
        ],
    )


def test_creates_statement_and_transactions(session: Session, batch):
    statement = normalize(session, _parsed(n=3), batch_id=batch.id)

    assert statement.bank == "Santander"
    assert statement.extraction_status == "SUCCESS"
    assert statement.validation_result is None  # set later, by validation
    assert statement.opening_balance_cents == 10000
    txns = session.exec(
        select(Transaction).where(Transaction.statement_id == statement.id)
    ).all()
    assert len(txns) == 3
    assert all(t.source_bank == "Santander" for t in txns)
    assert all(t.account_id == statement.account_id for t in txns)


def test_req_norm_002_raw_description_is_preserved_verbatim(session: Session, batch):
    statement = normalize(session, _parsed(n=1), batch_id=batch.id)
    txn = session.exec(
        select(Transaction).where(Transaction.statement_id == statement.id)
    ).one()

    assert txn.description_raw == "  RAW  DESC 0  "
    assert txn.description_normalized == "DESC 0"


def test_req_acc_002_same_account_resolves_to_one_row(session: Session, batch):
    normalize(session, _parsed(masked="1111"), batch_id=batch.id)
    normalize(session, _parsed(masked="1111"), batch_id=batch.id)

    accounts = session.exec(
        select(Account).where(Account.account_identifier_masked == "1111")
    ).all()
    assert len(accounts) == 1


def test_req_acc_002_different_masked_digits_stay_separate(session: Session, batch):
    s1 = normalize(session, _parsed(masked="1111"), batch_id=batch.id)
    s2 = normalize(session, _parsed(masked="2222"), batch_id=batch.id)

    assert s1.account_id != s2.account_id
    assert len(session.exec(select(Account)).all()) == 2


def test_sub_cent_amount_is_rejected_not_rounded(session: Session, batch):
    parsed = _parsed(n=1)
    parsed.transactions[0].amount = Decimal("10.001")

    with pytest.raises(SubCentPrecisionError):
        normalize(session, parsed, batch_id=batch.id)


def test_partial_extraction_marks_the_statement_partial(session: Session, batch):
    parsed = _parsed(n=1)
    parsed.unreadable_pages = [2]

    statement = normalize(session, parsed, batch_id=batch.id)

    assert statement.extraction_status == "PARTIAL"
