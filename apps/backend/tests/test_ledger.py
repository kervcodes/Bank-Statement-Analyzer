"""Build-plan #7 Part B: the deduplicated ledger the analytics engine reads
(REQ-ANLY-003) and its coverage summary (REQ-RPT-001)."""

from datetime import date

from sqlmodel import Session

from app.models import Account, Batch, Statement, Transaction
from app.services.ledger import coverage_summary, ledger_transactions


def _account(session: Session, account_id: str = "acct-1") -> str:
    if session.get(Account, account_id) is None:
        session.add(
            Account(
                id=account_id,
                bank="Santander",
                account_type="checking",
                account_identifier_masked="0520",
            )
        )
        session.commit()
    return account_id


def _batch(session: Session) -> Batch:
    b = Batch(
        selected=1,
        uploaded=1,
        upload_failed=0,
        validation_failed=0,
        processed=1,
        processing_failed=0,
        status="COMPLETED",
    )
    session.add(b)
    session.commit()
    return b


def _statement(
    session: Session,
    batch: Batch,
    *,
    start: date,
    end: date,
    validation: str = "VALID",
    dedup: str = "UNIQUE",
) -> Statement:
    _account(session)
    s = Statement(
        batch_id=batch.id,
        account_id="acct-1",
        bank="Santander",
        account_type="checking",
        account_identifier_masked="0520",
        statement_start_date=start,
        statement_end_date=end,
        opening_balance_cents=0,
        closing_balance_cents=0,
        parser_version="santander_checking_v1",
        extraction_status="SUCCESS",
        validation_result=validation,
        dedup_status=dedup,
    )
    session.add(s)
    session.commit()
    return s


def _txn(
    session: Session,
    statement: Statement,
    *,
    day: date,
    amount_cents: int = 1000,
    direction: str = "DEBIT",
    desc: str = "COFFEE SHOP",
    dedup: str = "UNIQUE",
) -> Transaction:
    t = Transaction(
        statement_id=statement.id,
        account_id="acct-1",
        transaction_date=day,
        posted_date=day,
        description_raw=desc,
        description_normalized=desc,
        amount_cents=amount_cents,
        direction=direction,
        source_bank="Santander",
        source_page=1,
        dedup_status=dedup,
    )
    session.add(t)
    session.commit()
    return t


def test_ledger_excludes_duplicates_and_failed_keeps_warning_and_possible(
    session: Session,
):
    batch = _batch(session)

    good = _statement(session, batch, start=date(2026, 1, 1), end=date(2026, 1, 31))
    _txn(session, good, day=date(2026, 1, 5), desc="KEPT-VALID")
    _txn(
        session,
        good,
        day=date(2026, 1, 6),
        desc="KEPT-POSSIBLE",
        dedup="POSSIBLE_DUPLICATE",
    )
    _txn(session, good, day=date(2026, 1, 7), desc="DROPPED-DUP-TXN", dedup="DUPLICATE")

    warned = _statement(
        session,
        batch,
        start=date(2026, 2, 1),
        end=date(2026, 2, 28),
        validation="WARNING",
    )
    _txn(session, warned, day=date(2026, 2, 3), desc="KEPT-WARNING")

    failed = _statement(
        session,
        batch,
        start=date(2026, 3, 1),
        end=date(2026, 3, 31),
        validation="FAILED",
    )
    _txn(session, failed, day=date(2026, 3, 3), desc="DROPPED-FAILED-STMT")

    dup_stmt = _statement(
        session,
        batch,
        start=date(2026, 4, 1),
        end=date(2026, 4, 30),
        dedup="DUPLICATE",
    )
    _txn(session, dup_stmt, day=date(2026, 4, 3), desc="DROPPED-DUP-STMT")

    kept = {t.description_normalized for t in ledger_transactions(session)}
    assert kept == {"KEPT-VALID", "KEPT-POSSIBLE", "KEPT-WARNING"}


def test_ledger_date_window_is_inclusive(session: Session):
    batch = _batch(session)
    stmt = _statement(session, batch, start=date(2026, 1, 1), end=date(2026, 3, 31))
    _txn(session, stmt, day=date(2026, 1, 15), desc="JAN")
    _txn(session, stmt, day=date(2026, 2, 15), desc="FEB")
    _txn(session, stmt, day=date(2026, 3, 15), desc="MAR")

    windowed = ledger_transactions(
        session, start=date(2026, 2, 1), end=date(2026, 2, 28)
    )
    assert [t.description_normalized for t in windowed] == ["FEB"]

    edges = ledger_transactions(session, start=date(2026, 1, 15), end=date(2026, 3, 15))
    assert [t.description_normalized for t in edges] == ["JAN", "FEB", "MAR"]


def test_coverage_summary_reports_included_and_excluded(session: Session):
    batch = _batch(session)

    good = _statement(session, batch, start=date(2026, 1, 1), end=date(2026, 1, 31))
    _txn(session, good, day=date(2026, 1, 5))
    _txn(session, good, day=date(2026, 1, 25))

    failed = _statement(
        session,
        batch,
        start=date(2026, 2, 1),
        end=date(2026, 2, 28),
        validation="FAILED",
    )
    _txn(session, failed, day=date(2026, 2, 3))

    _statement(
        session,
        batch,
        start=date(2026, 3, 1),
        end=date(2026, 3, 31),
        dedup="DUPLICATE",
    )

    cov = coverage_summary(session)

    assert cov.statements_included == 1
    assert cov.statements_excluded == 2
    assert cov.transaction_count == 2
    assert cov.ledger_start == date(2026, 1, 5)
    assert cov.ledger_end == date(2026, 1, 25)

    reasons = {e.reason for e in cov.excluded}
    assert reasons == {"FAILED", "DUPLICATE"}
    failed_entry = next(e for e in cov.excluded if e.reason == "FAILED")
    assert failed_entry.statement_id == failed.id
    assert failed_entry.period_start == date(2026, 2, 1)


def test_coverage_summary_date_window_limits_excluded_statements(session: Session):
    batch = _batch(session)
    _statement(
        session,
        batch,
        start=date(2026, 1, 1),
        end=date(2026, 1, 31),
        validation="FAILED",
    )
    in_window = _statement(
        session,
        batch,
        start=date(2026, 6, 1),
        end=date(2026, 6, 30),
        validation="FAILED",
    )

    cov = coverage_summary(session, start=date(2026, 5, 1), end=date(2026, 7, 31))

    assert [e.statement_id for e in cov.excluded] == [in_window.id]


def test_coverage_summary_empty_ledger(session: Session):
    cov = coverage_summary(session)
    assert cov.statements_included == 0
    assert cov.statements_excluded == 0
    assert cov.transaction_count == 0
    assert cov.ledger_start is None
    assert cov.ledger_end is None
    assert cov.excluded == []
