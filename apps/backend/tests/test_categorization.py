"""Build-plan #8 Part 1: the deterministic categorization hierarchy
(REQ-CAT-001/003/004)."""

from datetime import date

from sqlmodel import Session, col, select

from app.models import Batch, CategoryRule, Statement, Transaction
from app.services.categorization import (
    AUTO_ASSIGN_THRESHOLD,
    categorize_statement,
    predict_category,
    recategorize_transaction,
    resolve_category,
)


def _statement(session: Session) -> Statement:
    batch = Batch(
        selected=1,
        uploaded=1,
        upload_failed=0,
        validation_failed=0,
        processed=1,
        processing_failed=0,
        status="COMPLETED",
    )
    session.add(batch)
    session.commit()
    s = Statement(
        batch_id=batch.id,
        bank="Santander",
        account_type="checking",
        account_identifier_masked="0520",
        statement_start_date=date(2026, 1, 1),
        statement_end_date=date(2026, 1, 31),
        opening_balance_cents=0,
        closing_balance_cents=0,
        parser_version="santander_checking_v1",
        extraction_status="SUCCESS",
        validation_result="VALID",
    )
    session.add(s)
    session.commit()
    return s


def _txn(
    session: Session,
    statement: Statement,
    *,
    desc: str,
    direction: str = "DEBIT",
    amount_cents: int = 1000,
) -> Transaction:
    t = Transaction(
        statement_id=statement.id,
        transaction_date=date(2026, 1, 10),
        posted_date=date(2026, 1, 10),
        description_raw=desc,
        description_normalized=desc,
        amount_cents=amount_cents,
        direction=direction,
        source_bank="Santander",
        source_page=1,
    )
    session.add(t)
    session.commit()
    return t


# --- predict_category (pure) -------------------------------------------------


def test_predict_exact_merchant_hit():
    p = predict_category("Netflix", "NETFLIX.COM", "DEBIT")
    assert p.category == "Subscriptions"
    assert p.confidence >= AUTO_ASSIGN_THRESHOLD
    assert p.source == "RULE"


def test_predict_keyword_hit():
    p = predict_category("City Water Dept", "CITY WATER DEPT", "DEBIT")
    assert p.category == "Utilities"
    assert p.source == "RULE"


def test_predict_credit_with_no_signal_is_income():
    p = predict_category("Acme Corp", "ACME CORP", "CREDIT")
    assert p.category == "Income"


def test_predict_unknown_debit_is_no_prediction():
    p = predict_category("Zzq Unknown", "ZZQ UNKNOWN LLC", "DEBIT")
    assert p.category is None
    assert p.source == "NONE"


# --- resolve_category (the hierarchy) --------------------------------------


def test_resolve_prefers_user_over_everything(session: Session):
    s = _statement(session)
    t = _txn(session, s, desc="STARBUCKS")
    t.predicted_category = "Dining"
    t.predicted_confidence = 0.97
    t.predicted_source = "RULE"
    t.user_category = "Personal Care"
    resolve_category(t, merchant_rule_category="Groceries")
    assert t.category == "Personal Care"
    assert t.category_source == "USER"


def test_resolve_merchant_rule_beats_prediction(session: Session):
    s = _statement(session)
    t = _txn(session, s, desc="AMAZON")
    t.predicted_category = "Shopping"
    t.predicted_confidence = 0.97
    t.predicted_source = "RULE"
    resolve_category(t, merchant_rule_category="Groceries")
    assert t.category == "Groceries"
    assert t.category_source == "MERCHANT_RULE"


def test_resolve_below_threshold_goes_to_review(session: Session):
    s = _statement(session)
    t = _txn(session, s, desc="XYZ SERVICES")
    t.predicted_category = "Housing"
    t.predicted_confidence = AUTO_ASSIGN_THRESHOLD - 0.05
    t.predicted_source = "RULE"
    resolve_category(t, merchant_rule_category=None)
    assert t.category == "Uncategorized"
    assert t.category_source == "NONE"


# --- categorize_statement (the pipeline pass) -----------------------------


def test_categorize_statement_sets_merchant_and_category(session: Session):
    s = _statement(session)
    _txn(session, s, desc="NETFLIX.COM CARD PURCHASE")
    _txn(session, s, desc="STARBUCKS STORE 5 BOSTON /MA US CARD PURCHASE")
    _txn(session, s, desc="PAYROLL DEPOSIT ACME CORP", direction="CREDIT")
    _txn(session, s, desc="ZZQ MYSTERY VENDOR 99")

    categorize_statement(session, s)

    rows = {
        t.description_normalized: t
        for t in session.exec(
            select(Transaction).where(col(Transaction.statement_id) == s.id)
        )
    }
    assert rows["NETFLIX.COM CARD PURCHASE"].merchant_normalized == "Netflix"
    assert rows["NETFLIX.COM CARD PURCHASE"].category == "Subscriptions"
    assert rows["STARBUCKS STORE 5 BOSTON /MA US CARD PURCHASE"].category == "Dining"
    assert rows["PAYROLL DEPOSIT ACME CORP"].category == "Income"
    mystery = rows["ZZQ MYSTERY VENDOR 99"]
    assert mystery.category == "Uncategorized"
    assert mystery.category_source == "NONE"
    # the prediction is still recorded even though it didn't win
    assert mystery.predicted_source == "NONE"


def test_categorize_statement_is_idempotent(session: Session):
    s = _statement(session)
    _txn(session, s, desc="NETFLIX.COM CARD PURCHASE")
    categorize_statement(session, s)
    categorize_statement(session, s)
    (t,) = session.exec(
        select(Transaction).where(col(Transaction.statement_id) == s.id)
    )
    assert t.category == "Subscriptions"


def test_categorize_statement_respects_an_existing_user_override(session: Session):
    s = _statement(session)
    t = _txn(session, s, desc="NETFLIX.COM CARD PURCHASE")
    t.user_category = "Entertainment"
    session.add(t)
    session.commit()

    categorize_statement(session, s)

    session.refresh(t)
    assert t.category == "Entertainment"
    assert t.category_source == "USER"
    # prediction was not run/overwritten for a user-set row
    assert t.predicted_category is None


def test_deleting_a_merchant_rule_restores_the_prediction(session: Session):
    s = _statement(session)
    t = _txn(session, s, desc="AMAZON.COM CARD PURCHASE")
    session.add(CategoryRule(merchant="Amazon", category="Groceries"))
    session.commit()

    categorize_statement(session, s)
    session.refresh(t)
    assert t.category == "Groceries"
    assert t.category_source == "MERCHANT_RULE"
    assert t.predicted_category == "Shopping"  # kept

    rule = session.exec(select(CategoryRule)).one()
    session.delete(rule)
    session.commit()
    recategorize_transaction(session, t)
    session.commit()

    session.refresh(t)
    assert t.category == "Shopping"
    assert t.category_source == "RULE"
