"""REQ-VAL-001/002: the three-level check every statement clears before analytics.

- **structural**   -- required fields present and coherent
- **transaction**  -- each transaction has a sane date / description
- **reconciliation** -- opening + credits - debits == closing, exactly

Result is one of `VALID` / `WARNING` / `FAILED` (REQ-VAL-002), stored on
`Statement.validation_result`. Structural or reconciliation failure -> `FAILED`
(excluded from trusted analytics, REQ-VAL-003). Transaction-level oddities alone
-> `WARNING` (usable, but flagged). Everything clean -> `VALID`.

All arithmetic is in integer cents. This module never divides -- ratios and
averages are a read-time concern for the analytics engine, not validation.
"""

import logging

from sqlmodel import Session, col, select

from app.models import Statement, Transaction

logger = logging.getLogger(__name__)

# REQ-VAL-001 allows a "rounding tolerance". With integer-cent storage and a
# correct parse there is nothing to round: a mismatch is a real discrepancy.
RECONCILIATION_TOLERANCE_CENTS = 0


def _structural_issues(statement: Statement) -> list[str]:
    issues: list[str] = []
    if statement.statement_start_date > statement.statement_end_date:
        issues.append("statement start date is after the end date")
    if not statement.parser_version:
        issues.append("no parser_version recorded")
    return issues


def _transaction_issues(
    statement: Statement, transactions: list[Transaction]
) -> list[str]:
    issues: list[str] = []
    for txn in transactions:
        if not (
            statement.statement_start_date
            <= txn.transaction_date
            <= statement.statement_end_date
        ):
            issues.append(
                f"transaction {txn.transaction_date} is outside the statement period"
            )
        if not txn.description_normalized.strip():
            issues.append(
                f"transaction {txn.transaction_date} has an empty description"
            )
    return issues


def _reconciles(statement: Statement, transactions: list[Transaction]) -> bool:
    credits = sum(t.amount_cents for t in transactions if t.direction == "CREDIT")
    debits = sum(t.amount_cents for t in transactions if t.direction == "DEBIT")
    computed_closing = statement.opening_balance_cents + credits - debits
    return (
        abs(computed_closing - statement.closing_balance_cents)
        <= RECONCILIATION_TOLERANCE_CENTS
    )


def validate_statement(session: Session, statement: Statement) -> str:
    transactions = list(
        session.exec(
            select(Transaction)
            .where(col(Transaction.statement_id) == statement.id)
            .order_by(col(Transaction.transaction_date), col(Transaction.id))
        )
    )

    structural = _structural_issues(statement)
    if structural:
        logger.warning(
            "statement %s failed structural validation: %s", statement.id, structural
        )
        return "FAILED"

    if not _reconciles(statement, transactions):
        logger.warning("statement %s does not reconcile", statement.id)
        return "FAILED"

    if _transaction_issues(statement, transactions):
        return "WARNING"

    return "VALID"
