"""REQ-ANLY-003 / REQ-RPT-001: the unified, deduplicated ledger the analytics
engine reads, and the coverage summary shown alongside any totals.

A transaction is in the ledger when all of these hold:

- the transaction itself is not ``DUPLICATE`` (a ``POSSIBLE_DUPLICATE`` is kept
  in -- it was deliberately not collapsed, REQ-DEDUP-004);
- its statement is not ``DUPLICATE``;
- its statement passed validation as ``VALID`` or ``WARNING`` -- a ``FAILED`` or
  not-yet-validated statement is excluded from trusted analytics (REQ-VAL-003).

Nothing here branches on which bank produced the data (REQ-NORM-005).
"""

from dataclasses import dataclass, field
from datetime import date

from sqlmodel import Session, col, or_, select

from app.models import Statement, Transaction

# Validation results a statement must have for its transactions to be trusted.
# Mirrors app/services/deduplication._DEDUPABLE_VALIDATION.
_LEDGER_VALIDATION = ("VALID", "WARNING")


@dataclass(frozen=True)
class ExcludedStatement:
    statement_id: str
    bank: str
    account_identifier_masked: str
    period_start: date
    period_end: date
    reason: str  # "FAILED" | "DUPLICATE"


@dataclass(frozen=True)
class Coverage:
    statements_included: int
    statements_excluded: int
    transaction_count: int
    ledger_start: date | None
    ledger_end: date | None
    excluded: list[ExcludedStatement] = field(default_factory=list)


def _date_filters(start: date | None, end: date | None):
    filters = []
    if start is not None:
        filters.append(col(Transaction.transaction_date) >= start)
    if end is not None:
        filters.append(col(Transaction.transaction_date) <= end)
    return filters


def _trusted_statement_ids():
    """Statements whose transactions are trusted: not a duplicate re-upload, and
    validated VALID/WARNING (a FAILED or not-yet-validated one is out)."""
    return select(Statement.id).where(
        col(Statement.dedup_status) != "DUPLICATE",
        col(Statement.validation_result).in_(_LEDGER_VALIDATION),
    )


def ledger_query(*, include_duplicates: bool = False):
    """The base ``select(Transaction)`` for the deduplicated, validated ledger --
    a starting point other queries refine with more filters, ordering, and
    pagination. ``include_duplicates`` keeps transaction rows marked
    ``DUPLICATE`` (still on an otherwise-trusted statement) for a
    "show me what I collapsed" view."""
    query = select(Transaction).where(
        col(Transaction.statement_id).in_(_trusted_statement_ids())
    )
    if not include_duplicates:
        query = query.where(col(Transaction.dedup_status) != "DUPLICATE")
    return query


def ledger_transactions(
    session: Session, *, start: date | None = None, end: date | None = None
) -> list[Transaction]:
    """Every transaction in the deduplicated, validated ledger, oldest first.

    ``start`` / ``end`` (inclusive) optionally clip to a ``transaction_date``
    window.
    """
    query = (
        ledger_query()
        .where(*_date_filters(start, end))
        .order_by(col(Transaction.transaction_date), col(Transaction.id))
    )
    return list(session.exec(query))


def coverage_summary(
    session: Session, *, start: date | None = None, end: date | None = None
) -> Coverage:
    """Statements included vs excluded (with reason), the ledger's real date
    span, and its live transaction count (REQ-RPT-001).

    "Excluded" means a statement that parsed but is kept out of analytics: it
    failed validation, or it was collapsed as a duplicate re-upload. When a date
    window is given, only statements whose period overlaps it are reported.
    """
    txns = ledger_transactions(session, start=start, end=end)
    included_statement_ids = {t.statement_id for t in txns}

    excluded_query = select(Statement).where(
        or_(
            col(Statement.dedup_status) == "DUPLICATE",
            col(Statement.validation_result) == "FAILED",
        )
    )
    if start is not None:
        excluded_query = excluded_query.where(
            col(Statement.statement_end_date) >= start
        )
    if end is not None:
        excluded_query = excluded_query.where(
            col(Statement.statement_start_date) <= end
        )

    excluded = [
        ExcludedStatement(
            statement_id=s.id,
            bank=s.bank,
            account_identifier_masked=s.account_identifier_masked,
            period_start=s.statement_start_date,
            period_end=s.statement_end_date,
            reason="DUPLICATE" if s.dedup_status == "DUPLICATE" else "FAILED",
        )
        for s in session.exec(excluded_query)
    ]

    return Coverage(
        statements_included=len(included_statement_ids),
        statements_excluded=len(excluded),
        transaction_count=len(txns),
        ledger_start=txns[0].transaction_date if txns else None,
        ledger_end=txns[-1].transaction_date if txns else None,
        excluded=excluded,
    )
