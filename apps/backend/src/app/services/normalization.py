"""REQ-NORM-001..006 / REQ-ACC-001..002: turn a `ParsedStatement` into rows.

The only place a parser's `Decimal` amounts become stored integer cents, so
`SubCentPrecisionError` surfaces here and nowhere else. The only writer of
`Statement` / `Transaction` / `Account` rows in the pipeline.
"""

from sqlmodel import Session, col, select

from app.models import Account, Statement, Transaction, to_cents
from app.parsers.base import ParsedStatement


def _resolve_account(session: Session, parsed: ParsedStatement) -> Account:
    """Find the account this statement belongs to, or create it.

    Identity is (bank, account_type, masked digits) -- never the full number
    (REQ-ACC-001). Two accounts at the same bank with different masked digits
    stay separate (REQ-ACC-002).
    """
    existing = session.exec(
        select(Account)
        .where(col(Account.bank) == parsed.bank)
        .where(col(Account.account_type) == parsed.account_type)
        .where(
            col(Account.account_identifier_masked) == parsed.account_identifier_masked
        )
    ).first()
    if existing is not None:
        return existing

    account = Account(
        bank=parsed.bank,
        account_type=parsed.account_type,
        account_identifier_masked=parsed.account_identifier_masked,
    )
    session.add(account)
    session.commit()
    session.refresh(account)
    return account


def normalize(session: Session, parsed: ParsedStatement, *, batch_id: str) -> Statement:
    # Convert every amount to integer cents first, before writing anything. A
    # sub-cent value means the parser misread a number (REQ-NORM-006); aborting
    # here leaves no half-written Statement behind (REQ-VAL-005).
    opening_cents = to_cents(parsed.opening_balance)
    closing_cents = to_cents(parsed.closing_balance)
    txn_cents = [
        (
            txn,
            to_cents(txn.amount),
            to_cents(txn.balance_after) if txn.balance_after is not None else None,
        )
        for txn in parsed.transactions
    ]

    account = _resolve_account(session, parsed)

    statement = Statement(
        batch_id=batch_id,
        account_id=account.id,
        bank=parsed.bank,
        account_type=parsed.account_type,
        account_identifier_masked=parsed.account_identifier_masked,
        statement_start_date=parsed.statement_start_date,
        statement_end_date=parsed.statement_end_date,
        opening_balance_cents=opening_cents,
        closing_balance_cents=closing_cents,
        parser_version=parsed.parser_version,
        # REQ-VAL-004: "could we read it", separate from "do the numbers add up".
        extraction_status="PARTIAL" if parsed.unreadable_pages else "SUCCESS",
        validation_result=None,  # set by financial_validation, after this
    )
    session.add(statement)
    session.flush()  # assign statement.id without committing yet

    for txn, amount_cents, balance_after_cents in txn_cents:
        session.add(
            Transaction(
                statement_id=statement.id,
                account_id=account.id,
                transaction_date=txn.transaction_date,
                posted_date=txn.posted_date,
                description_raw=txn.description_raw,  # never overwritten (REQ-NORM-002)
                description_normalized=txn.description_normalized,
                amount_cents=amount_cents,
                direction=txn.direction,
                balance_after_cents=balance_after_cents,
                source_bank=parsed.bank,
                source_page=txn.source_page,
            )
        )
    session.commit()
    session.refresh(statement)
    return statement
