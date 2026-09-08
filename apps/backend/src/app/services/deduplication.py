"""REQ-DEDUP-001..004: find duplicate statements and transactions after a batch
finishes processing.

Two passes, statement-level first (REQ-DEDUP-001):

- **statement-level** -- an exact match on account, period, and reconciled
  endpoints is the same PDF uploaded twice. High confidence: the newer statement
  and every transaction on it become ``DUPLICATE`` of the older one, and it is
  skipped by the transaction pass.
- **transaction-level** -- for the partial-overlap case (a "last 90 days"
  statement overlapping three monthly ones). Only compares transactions across
  *different* statements of the *same* account whose periods overlap. A clean
  1:1 match on ``(date, amount, direction, normalized description)`` inside the
  overlap is ``DUPLICATE``; anything with ambiguous cardinality is
  ``POSSIBLE_DUPLICATE`` -- kept and flagged, never deleted (REQ-DEDUP-004).

Rows are never removed. A ``DUPLICATE`` row keeps its place for traceability
(REQ-RPT-003); analytics simply excludes it from the ledger view.
"""

import logging
from collections import defaultdict

from sqlmodel import Session, col, select

from app.models import Statement, Transaction

logger = logging.getLogger(__name__)

# Statuses a statement must have to be considered by dedup at all. A FAILED
# statement is excluded from the ledger anyway (REQ-VAL-003).
_DEDUPABLE_VALIDATION = ("VALID", "WARNING")

_TxnKey = tuple[
    str, int, str, str
]  # (iso date, amount_cents, direction, normalized desc)


def _txn_key(txn: Transaction) -> _TxnKey:
    return (
        txn.transaction_date.isoformat(),
        txn.amount_cents,
        txn.direction,
        txn.description_normalized.strip().casefold(),
    )


def _find_matching_statement(
    session: Session, statement: Statement
) -> Statement | None:
    """The oldest non-duplicate statement with the same account, period, and
    reconciled endpoints -- i.e. the same document already in the ledger."""
    if statement.account_id is None:
        return None
    candidates = session.exec(
        select(Statement)
        .where(col(Statement.id) != statement.id)
        .where(col(Statement.account_id) == statement.account_id)
        .where(col(Statement.statement_start_date) == statement.statement_start_date)
        .where(col(Statement.statement_end_date) == statement.statement_end_date)
        .where(col(Statement.opening_balance_cents) == statement.opening_balance_cents)
        .where(col(Statement.closing_balance_cents) == statement.closing_balance_cents)
        .where(col(Statement.dedup_status) != "DUPLICATE")
    ).all()
    if not candidates:
        return None
    return min(candidates, key=lambda s: (s.created_at, s.id))


def _mark_statement_duplicate(
    session: Session, statement: Statement, canonical: Statement
) -> None:
    statement.dedup_status = "DUPLICATE"
    statement.duplicate_of_id = canonical.id
    session.add(statement)
    for txn in statement.transactions:
        txn.dedup_status = "DUPLICATE"
        txn.duplicate_of_id = None  # the whole statement is the duplicate
        session.add(txn)
    session.commit()


def _overlapping_statements(session: Session, statement: Statement) -> list[Statement]:
    if statement.account_id is None:
        return []
    others = session.exec(
        select(Statement)
        .where(col(Statement.id) != statement.id)
        .where(col(Statement.account_id) == statement.account_id)
        .where(col(Statement.dedup_status) != "DUPLICATE")
        .where(col(Statement.statement_start_date) <= statement.statement_end_date)
        .where(col(Statement.statement_end_date) >= statement.statement_start_date)
    ).all()
    return [s for s in others if s.validation_result in _DEDUPABLE_VALIDATION]


def _dedup_transactions(session: Session, statement: Statement) -> None:
    others = _overlapping_statements(session, statement)
    if not others:
        return

    # Prior transactions from overlapping statements, keyed. Only those dated
    # inside this statement's period can be a duplicate of one of its rows.
    prior: dict[_TxnKey, list[Transaction]] = defaultdict(list)
    for other in others:
        for txn in other.transactions:
            if txn.dedup_status == "DUPLICATE":
                continue
            if (
                statement.statement_start_date
                <= txn.transaction_date
                <= statement.statement_end_date
            ):
                prior[_txn_key(txn)].append(txn)

    own_counts: dict[_TxnKey, int] = defaultdict(int)
    for txn in statement.transactions:
        own_counts[_txn_key(txn)] += 1

    changed = False
    for txn in statement.transactions:
        if txn.dedup_status != "UNIQUE":
            continue
        key = _txn_key(txn)
        matches = prior.get(key, [])
        if not matches:
            continue
        if len(matches) == 1 and own_counts[key] == 1:
            txn.dedup_status = "DUPLICATE"
            txn.duplicate_of_id = matches[0].id
        else:
            # Ambiguous cardinality -- keep every row, flag for review.
            txn.dedup_status = "POSSIBLE_DUPLICATE"
            txn.duplicate_of_id = matches[0].id
        session.add(txn)
        changed = True

    if changed:
        session.commit()


def run_dedup_for_batch(session: Session, batch_id: str) -> None:
    """Dedup every not-yet-classified VALID/WARNING statement in the batch,
    oldest first. Idempotent -- an already-classified statement is skipped, so a
    second call is a no-op."""
    statements = session.exec(
        select(Statement)
        .where(col(Statement.batch_id) == batch_id)
        .order_by(col(Statement.created_at), col(Statement.id))
    ).all()

    for statement in statements:
        if statement.dedup_status != "UNIQUE":
            continue
        if statement.validation_result not in _DEDUPABLE_VALIDATION:
            continue

        canonical = _find_matching_statement(session, statement)
        if canonical is not None:
            _mark_statement_duplicate(session, statement, canonical)
            logger.info("statement %s is a duplicate of %s", statement.id, canonical.id)
            continue

        _dedup_transactions(session, statement)
