"""Build-plan #7: deduplication. Traces to REQ-DEDUP-001..004; NFR-MAINT-002
names dedup confidence scoring as a must-test area."""

from datetime import UTC, date, datetime
from decimal import Decimal

from sqlmodel import Session, col, func, select

from app.models import Account, Batch, Statement, Transaction, to_cents
from app.services.deduplication import run_dedup_for_batch


def _at(year: int, month: int, day: int) -> datetime:
    return datetime(year, month, day, tzinfo=UTC)


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


def _batch(session: Session, when: datetime) -> Batch:
    b = Batch(
        created_at=when,
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
    account_id: str = "acct-1",
    start: date,
    end: date,
    opening: str = "100.00",
    closing: str = "100.00",
    validation: str = "VALID",
    created: datetime,
) -> Statement:
    _account(session, account_id)
    s = Statement(
        batch_id=batch.id,
        account_id=account_id,
        created_at=created,
        bank="Santander",
        account_type="checking",
        account_identifier_masked="0520",
        statement_start_date=start,
        statement_end_date=end,
        opening_balance_cents=to_cents(Decimal(opening)),
        closing_balance_cents=to_cents(Decimal(closing)),
        parser_version="santander_checking_v1",
        extraction_status="SUCCESS",
        validation_result=validation,
    )
    session.add(s)
    session.commit()
    return s


def _txn(
    session: Session,
    statement: Statement,
    *,
    day: int,
    amount: str,
    desc: str = "COFFEE SHOP",
    direction: str = "DEBIT",
    month: int = 1,
) -> Transaction:
    t = Transaction(
        statement_id=statement.id,
        account_id=statement.account_id,
        transaction_date=date(2026, month, day),
        posted_date=date(2026, month, day),
        description_raw=desc,
        description_normalized=desc,
        amount_cents=to_cents(Decimal(amount)),
        direction=direction,
        source_bank="Santander",
        source_page=1,
    )
    session.add(t)
    session.commit()
    return t


def _ledger_count(session: Session) -> int:
    return session.exec(
        select(func.count())
        .select_from(Transaction)
        .where(col(Transaction.dedup_status) != "DUPLICATE")
    ).one()


# --- statement-level (REQ-DEDUP-001) -------------------------------------


def test_reuploading_a_statement_collapses_it(session: Session):
    b1 = _batch(session, _at(2026, 2, 1))
    s1 = _statement(
        session,
        b1,
        start=date(2026, 1, 1),
        end=date(2026, 1, 31),
        closing="80.00",
        created=_at(2026, 2, 1),
    )
    _txn(session, s1, day=5, amount="20.00")

    b2 = _batch(session, _at(2026, 2, 10))
    s2 = _statement(
        session,
        b2,
        start=date(2026, 1, 1),
        end=date(2026, 1, 31),
        closing="80.00",
        created=_at(2026, 2, 10),
    )
    _txn(session, s2, day=5, amount="20.00")

    run_dedup_for_batch(session, b2.id)
    session.expire_all()

    assert session.get(Statement, s1.id).dedup_status == "UNIQUE"
    s2 = session.get(Statement, s2.id)
    assert s2.dedup_status == "DUPLICATE"
    assert s2.duplicate_of_id == s1.id
    assert all(t.dedup_status == "DUPLICATE" for t in s2.transactions)
    assert _ledger_count(session) == 1  # the re-upload added nothing to the ledger


def test_a_different_month_is_not_a_duplicate(session: Session):
    b1 = _batch(session, _at(2026, 2, 1))
    s1 = _statement(
        session,
        b1,
        start=date(2026, 1, 1),
        end=date(2026, 1, 31),
        created=_at(2026, 2, 1),
    )
    b2 = _batch(session, _at(2026, 3, 1))
    s2 = _statement(
        session,
        b2,
        start=date(2026, 2, 1),
        end=date(2026, 2, 28),
        created=_at(2026, 3, 1),
    )

    run_dedup_for_batch(session, b2.id)
    session.expire_all()

    assert session.get(Statement, s1.id).dedup_status == "UNIQUE"
    assert session.get(Statement, s2.id).dedup_status == "UNIQUE"


def test_failed_statements_are_skipped_by_dedup(session: Session):
    b1 = _batch(session, _at(2026, 2, 1))
    _statement(
        session,
        b1,
        start=date(2026, 1, 1),
        end=date(2026, 1, 31),
        created=_at(2026, 2, 1),
    )
    b2 = _batch(session, _at(2026, 2, 10))
    s2 = _statement(
        session,
        b2,
        start=date(2026, 1, 1),
        end=date(2026, 1, 31),
        validation="FAILED",
        created=_at(2026, 2, 10),
    )

    run_dedup_for_batch(session, b2.id)
    session.expire_all()

    assert session.get(Statement, s2.id).dedup_status == "UNIQUE"  # untouched


# --- transaction-level (REQ-DEDUP-002/003/004) --------------------------


def test_overlapping_statements_collapse_shared_transactions(session: Session):
    b1 = _batch(session, _at(2026, 2, 1))
    monthly = _statement(
        session,
        b1,
        start=date(2026, 1, 1),
        end=date(2026, 1, 31),
        created=_at(2026, 2, 1),
    )
    _txn(session, monthly, day=10, amount="30.00", desc="GROCERY")
    _txn(session, monthly, day=20, amount="15.00", desc="GAS STATION")

    b2 = _batch(session, _at(2026, 3, 1))
    ninety_day = _statement(
        session,
        b2,
        start=date(2026, 1, 15),
        end=date(2026, 4, 15),
        created=_at(2026, 3, 1),
    )
    shared = _txn(session, ninety_day, day=20, amount="15.00", desc="GAS STATION")
    outside = _txn(session, ninety_day, day=5, amount="9.99", desc="STREAMING", month=3)

    run_dedup_for_batch(session, b2.id)
    session.expire_all()

    assert session.get(Transaction, shared.id).dedup_status == "DUPLICATE"
    assert session.get(Transaction, outside.id).dedup_status == "UNIQUE"
    # the 01-10 GROCERY charge is only in the monthly statement -> untouched
    assert _ledger_count(session) == 3


def test_ambiguous_cardinality_is_flagged_not_deleted(session: Session):
    b1 = _batch(session, _at(2026, 2, 1))
    a = _statement(
        session,
        b1,
        start=date(2026, 1, 1),
        end=date(2026, 1, 31),
        created=_at(2026, 2, 1),
    )
    _txn(session, a, day=14, amount="7.82", desc="STARBUCKS")
    _txn(session, a, day=14, amount="7.82", desc="STARBUCKS")

    b2 = _batch(session, _at(2026, 3, 1))
    b = _statement(
        session,
        b2,
        start=date(2026, 1, 10),
        end=date(2026, 2, 10),
        created=_at(2026, 3, 1),
    )
    x = _txn(session, b, day=14, amount="7.82", desc="STARBUCKS")
    y = _txn(session, b, day=14, amount="7.82", desc="STARBUCKS")

    run_dedup_for_batch(session, b2.id)
    session.expire_all()

    assert session.get(Transaction, x.id).dedup_status == "POSSIBLE_DUPLICATE"
    assert session.get(Transaction, y.id).dedup_status == "POSSIBLE_DUPLICATE"
    # nothing deleted -- all four rows still there (REQ-DEDUP-004)
    assert session.exec(select(func.count()).select_from(Transaction)).one() == 4


def test_identical_same_day_charges_in_one_statement_are_both_kept(session: Session):
    b1 = _batch(session, _at(2026, 2, 1))
    s = _statement(
        session,
        b1,
        start=date(2026, 1, 1),
        end=date(2026, 1, 31),
        created=_at(2026, 2, 1),
    )
    t1 = _txn(session, s, day=3, amount="4.50", desc="VENDING")
    t2 = _txn(session, s, day=3, amount="4.50", desc="VENDING")

    run_dedup_for_batch(session, b1.id)
    session.expire_all()

    assert session.get(Transaction, t1.id).dedup_status == "UNIQUE"
    assert session.get(Transaction, t2.id).dedup_status == "UNIQUE"


def test_run_dedup_for_batch_is_idempotent(session: Session):
    b1 = _batch(session, _at(2026, 2, 1))
    s1 = _statement(
        session,
        b1,
        start=date(2026, 1, 1),
        end=date(2026, 1, 31),
        created=_at(2026, 2, 1),
    )
    _txn(session, s1, day=5, amount="20.00")
    b2 = _batch(session, _at(2026, 2, 10))
    s2 = _statement(
        session,
        b2,
        start=date(2026, 1, 1),
        end=date(2026, 1, 31),
        created=_at(2026, 2, 10),
    )
    _txn(session, s2, day=5, amount="20.00")

    run_dedup_for_batch(session, b2.id)
    run_dedup_for_batch(session, b2.id)  # second call
    session.expire_all()

    s2 = session.get(Statement, s2.id)
    assert s2.dedup_status == "DUPLICATE"
    assert s2.duplicate_of_id == s1.id
