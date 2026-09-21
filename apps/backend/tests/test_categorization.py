"""Build-plan #8 Part 1: the deterministic categorization hierarchy
(REQ-CAT-001/003/004)."""

from datetime import date

from sqlmodel import Session, col, select

from app.models import Batch, CategoryRule, Statement, Transaction
from app.services.categorization import (
    AUTO_ASSIGN_THRESHOLD,
    categorize_statement,
    predict_category,
    recategorize_pending,
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


# --- merchant-contextual rules (a merchant sells across >1 category) -------


def test_contextual_pattern_overrides_merchant_default():
    p = predict_category("BJ's Wholesale Club", "BJ'S FUEL #9101", "DEBIT")
    assert p.category == "Fuel"
    assert p.source == "RULE"
    assert p.confidence >= AUTO_ASSIGN_THRESHOLD


def test_contextual_pattern_matches_the_mobile_channel_signal():
    # This bank's "MOBILE - " channel prefix is itself the fuel signal for
    # BJ's specifically -- see MERCHANT_CONTEXTUAL_RULES.
    p = predict_category("BJ's Wholesale Club", "MOBILE - BJS", "DEBIT")
    assert p.category == "Fuel"


def test_merchant_default_still_applies_with_no_contextual_match():
    p = predict_category("BJ's Wholesale Club", "BJS WHOLESALE #123", "DEBIT")
    assert p.category == "Groceries"


def test_costco_fuel_overrides_the_groceries_default():
    p = predict_category("Costco", "COSTCO GAS #445", "DEBIT")
    assert p.category == "Fuel"


def test_costco_default_is_still_groceries():
    p = predict_category("Costco", "COSTCO WHOLESALE #445", "DEBIT")
    assert p.category == "Groceries"


def test_contextual_pattern_never_fires_for_the_wrong_merchant():
    # "FUEL" appearing in some unrelated merchant's description must not
    # trigger a rule scoped to a different merchant.
    p = predict_category("Some Fuel Depot", "SOME FUEL DEPOT INC", "DEBIT")
    assert p.category is None


# --- newly-added deterministic coverage -------------------------------------


def test_predict_new_common_chains():
    assert predict_category("Aldi", "ALDI 123 CAMBRIDGE", "DEBIT").category == (
        "Groceries"
    )
    assert predict_category("Wendy's", "WENDY'S #2284", "DEBIT").category == "Dining"
    assert (
        predict_category("Burger King", "BURGER KING #1", "DEBIT").category == "Dining"
    )
    assert predict_category("7-Eleven", "7-ELEVEN #1", "DEBIT").category == "Shopping"
    assert (
        predict_category("Home Depot", "HOME DEPOT #1", "DEBIT").category == "Shopping"
    )


def test_predict_toll_and_generic_fee_keywords():
    assert (
        predict_category("Mass Pike", "E-ZPASS MA WALTHAM", "DEBIT").category
        == "Transportation"
    )
    assert (
        predict_category("Capital One", "CAPITAL ONE CRCARDPMT", "DEBIT").category
        == "Credit Card Payments"
    )
    assert (
        predict_category("Some Bank", "INTERNATIONAL TRANSACTION FEE", "DEBIT").category
        == "Fees & Interest"
    )


def test_generic_fee_keyword_does_not_shadow_parking():
    # PARKING is checked before the generic FEE catch-all.
    assert (
        predict_category("City Garage", "CITY GARAGE PARKING FEE", "DEBIT").category
        == "Transportation"
    )


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


def test_llm_fills_a_merchant_the_rules_could_not_place(session: Session, monkeypatch):
    import app.services.categorization as cat
    from app.llm.base import CategorySuggestion

    calls: list = []

    def fake_suggest(**kwargs):
        calls.append(kwargs)
        return CategorySuggestion("Personal Care", 0.91)

    monkeypatch.setattr(cat, "suggest_category", fake_suggest)

    s = _statement(session)
    _txn(session, s, desc="ZZQ SPA RETREAT 44")
    _txn(session, s, desc="ZZQ SPA RETREAT 91")  # same merchant -> one LLM call

    categorize_statement(session, s)

    assert len(calls) == 1  # one call per unique merchant
    rows = list(
        session.exec(select(Transaction).where(col(Transaction.statement_id) == s.id))
    )
    for t in rows:
        assert t.predicted_source == "LLM"
        assert t.predicted_category == "Personal Care"
        assert t.category == "Personal Care"
        assert t.category_source == "LLM"


def test_low_confidence_llm_suggestion_goes_to_review(session: Session, monkeypatch):
    import app.services.categorization as cat
    from app.llm.base import CategorySuggestion

    monkeypatch.setattr(
        cat, "suggest_category", lambda **k: CategorySuggestion("Shopping", 0.40)
    )
    s = _statement(session)
    t = _txn(session, s, desc="ZZQ MYSTERY VENDOR")

    categorize_statement(session, s)

    session.refresh(t)
    assert t.category == "Uncategorized"
    assert t.category_source == "NONE"
    assert t.predicted_category == "Shopping"  # kept, not discarded


def test_no_provider_leaves_categorization_deterministic(session: Session):
    # suggest_category returns None with no env keys -> identical to Part 1
    s = _statement(session)
    _txn(session, s, desc="ZZQ MYSTERY VENDOR")
    categorize_statement(session, s)
    (t,) = session.exec(
        select(Transaction).where(col(Transaction.statement_id) == s.id)
    )
    assert t.category == "Uncategorized"
    assert t.predicted_source == "NONE"


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


# --- recategorize_pending (the backfill path) -------------------------------


def test_recategorize_pending_reprocesses_a_transaction_left_none(session: Session):
    # Simulates a transaction imported before "Aldi" existed as a rule: it was
    # committed with the pipeline's own defaults and never touched again.
    s = _statement(session)
    t = _txn(session, s, desc="ALDI 123 CAMBRIDGE")
    assert t.merchant_normalized is None
    assert t.category == "Uncategorized"

    considered = recategorize_pending(session)

    session.refresh(t)
    assert considered == 1
    assert t.merchant_normalized == "Aldi"
    assert t.category == "Groceries"
    assert t.category_source == "RULE"


def test_recategorize_pending_never_touches_a_user_override(session: Session):
    s = _statement(session)
    t = _txn(session, s, desc="ALDI 123 CAMBRIDGE")
    t.user_category = "Personal Care"
    recategorize_transaction(session, t)  # the real path: resolves immediately
    session.commit()

    recategorize_pending(session)

    session.refresh(t)
    assert t.category == "Personal Care"
    assert t.category_source == "USER"
    # a user-set row's prediction is still never populated
    assert t.predicted_category is None


def test_recategorize_pending_honors_an_active_merchant_rule(session: Session):
    s = _statement(session)
    t = _txn(session, s, desc="ALDI 123 CAMBRIDGE")
    session.add(CategoryRule(merchant="Aldi", category="Personal Care"))
    session.commit()

    recategorize_pending(session)

    session.refresh(t)
    assert t.category == "Personal Care"
    assert t.category_source == "MERCHANT_RULE"
    # the fresh deterministic guess is still recorded underneath
    assert t.predicted_category == "Groceries"


def test_recategorize_pending_picks_up_a_new_contextual_rule(session: Session):
    # A Costco gas purchase that was mis-categorized as Groceries under the
    # old flat-default behavior gets corrected by a re-run.
    s = _statement(session)
    t = _txn(session, s, desc="COSTCO GAS #445")
    t.merchant_normalized = "Costco"
    t.predicted_category = "Groceries"
    t.predicted_confidence = 0.97
    t.predicted_source = "RULE"
    t.category = "Groceries"
    t.category_source = "RULE"
    session.add(t)
    session.commit()

    recategorize_pending(session)

    session.refresh(t)
    assert t.category == "Fuel"


def test_recategorize_pending_is_idempotent(session: Session):
    s = _statement(session)
    _txn(session, s, desc="ALDI 123 CAMBRIDGE")
    recategorize_pending(session)
    considered_again = recategorize_pending(session)
    (t,) = session.exec(
        select(Transaction).where(col(Transaction.statement_id) == s.id)
    )
    assert considered_again == 1
    assert t.category == "Groceries"


def test_recategorize_pending_is_a_no_op_with_nothing_eligible(session: Session):
    s = _statement(session)
    t = _txn(session, s, desc="ALDI 123 CAMBRIDGE")
    t.user_category = "Groceries"
    session.add(t)
    session.commit()

    considered = recategorize_pending(session)

    assert considered == 0
