"""Build-plan #8 Part 2, P2-1: the Privacy Gateway (REQ-LLM-001/002/003).

These tests prove the *serialized outbound payload itself* carries no forbidden
fields and no seeded PII, using adversarial descriptions.
"""

import json
from datetime import date

import pytest

from app.services.analytics import (
    Analytics,
    CategoryTotal,
    CoverageSummary,
    ExcludedStatementSummary,
    MerchantTotal,
    PeriodCashFlow,
    Trends,
)
from app.services.privacy_gateway import (
    OutboundTransaction,
    PrivacyBlockedError,
    build_categorization_payload,
    build_explanation_payload,
    sanitize_text,
)

# Seeded PII that must never appear in an outbound payload.
ACCOUNT_NUMBER = "4012888812345678"
ROUTING_NUMBER = "011000015"
CARD_SPACED = "4111 1111 1111 1111"
PHONE = "877-000-1111"
EMAIL = "john.doe@example.com"
SSN = "123-45-6789"
PERSON = "JOHN DOE"


@pytest.mark.parametrize(
    "raw",
    [
        f"ZELLE TO {PERSON}",
        f"ZELLE TRANSFER TO {PERSON} {PHONE} PAYMENT",
        f"VENMO PAYMENT {PERSON} 1017283746",
        f"ACH DEBIT ACCT {ACCOUNT_NUMBER}",
        f"WIRE TRANSFER TO {PERSON}",
        f"CHECK CARD PURCHASE {CARD_SPACED}",
        f"ONLINE PMT REF {ROUTING_NUMBER}0000",
        f"PAYPAL TRANSFER {EMAIL}",
        f"CUSTOMER SVC {PHONE}",
        f"REBATE SSN {SSN}",
    ],
)
def test_sanitize_removes_adversarial_pii(raw: str):
    cleaned = sanitize_text(raw)
    for secret in (ACCOUNT_NUMBER, ROUTING_NUMBER, "4111", PHONE, EMAIL, SSN, "DOE"):
        assert secret not in cleaned, (
            f"{secret!r} survived sanitize of {raw!r}: {cleaned!r}"
        )


@pytest.mark.parametrize(
    "merchant",
    ["Netflix", "Shell", "Whole Foods", "The Corner Cafe", "Uber"],
)
def test_sanitize_keeps_ordinary_merchant_names(merchant: str):
    assert sanitize_text(merchant.upper()) == merchant.upper()


def test_payload_is_a_closed_allowlist():
    payload = build_categorization_payload(
        merchant_normalized="Netflix",
        description_normalized="NETFLIX.COM CARD PURCHASE",
        amount_cents=1599,
        direction="DEBIT",
    )
    assert isinstance(payload, OutboundTransaction)
    assert set(payload.model_dump().keys()) == {
        "merchant",
        "description",
        "amount",
        "direction",
    }
    assert payload.amount == "15.99"
    assert payload.direction == "debit"
    # the model rejects any extra field
    with pytest.raises(ValueError):
        OutboundTransaction(
            merchant="x",
            description="y",
            amount="1.00",
            direction="debit",
            account_number="secret",
        )


def test_serialized_payload_has_no_seeded_pii():
    payload = build_categorization_payload(
        merchant_normalized="Zelle",
        description_normalized=(
            f"ZELLE TRANSFER TO {PERSON} {PHONE} MEMO ACCT {ACCOUNT_NUMBER} {EMAIL}"
        ),
        amount_cents=5000,
        direction="DEBIT",
    )
    blob = payload.model_dump_json()
    for secret in (ACCOUNT_NUMBER, PHONE, EMAIL, "DOE", "JOHN"):
        assert secret not in blob, f"{secret!r} leaked into {blob!r}"
    # sanity: it is real JSON with exactly the four keys
    assert set(json.loads(blob)) == {"merchant", "description", "amount", "direction"}


def test_fails_closed_on_unknown_direction():
    with pytest.raises(PrivacyBlockedError):
        build_categorization_payload(
            merchant_normalized="Netflix",
            description_normalized="NETFLIX",
            amount_cents=100,
            direction="REFUND",
        )


def test_fails_closed_when_nothing_left_to_classify():
    with pytest.raises(PrivacyBlockedError):
        build_categorization_payload(
            merchant_normalized="",
            description_normalized="  ",
            amount_cents=100,
            direction="DEBIT",
        )


def test_fails_closed_on_residual_pii(monkeypatch: pytest.MonkeyPatch):
    # simulate a sanitize gap: sanitize returns the text unchanged
    monkeypatch.setattr("app.services.privacy_gateway.sanitize_text", lambda s: s or "")
    with pytest.raises(PrivacyBlockedError):
        build_categorization_payload(
            merchant_normalized="Something",
            description_normalized=f"ACCT {ACCOUNT_NUMBER}",
            amount_cents=100,
            direction="DEBIT",
        )


def test_amount_is_absolute_dollars():
    payload = build_categorization_payload(
        merchant_normalized="Store",
        description_normalized="STORE PURCHASE",
        amount_cents=250_000,
        direction="DEBIT",
    )
    assert payload.amount == "2500.00"


def _analytics_with_a_name_in_a_merchant() -> Analytics:
    return Analytics(
        start=None,
        end=None,
        cash_flow=[
            PeriodCashFlow(
                period="2026-01",
                credits_cents=200_000,
                debits_cents=50_000,
                net_cents=150_000,
                spending_cents=40_000,
                transfers_cents=10_000,
            )
        ],
        spending_by_category=[
            CategoryTotal(category="Groceries", total_cents=40_000, transaction_count=3)
        ],
        merchant_totals=[
            MerchantTotal(
                merchant=f"ZELLE {PERSON} {ACCOUNT_NUMBER}",
                total_cents=10_000,
                transaction_count=1,
            )
        ],
        recurring_charges=[],
        trends=Trends(
            current_period="2026-01",
            previous_period=None,
            spending_delta_cents=0,
            spending_delta_ratio=None,
            net_delta_cents=0,
            net_delta_ratio=None,
        ),
        coverage=CoverageSummary(
            statements_included=1,
            statements_excluded=1,
            transaction_count=3,
            ledger_start=date(2026, 1, 1),
            ledger_end=date(2026, 1, 31),
            excluded=[
                ExcludedStatementSummary(
                    statement_id="secret-stmt-id",
                    bank="Santander",
                    account_identifier_masked="0520",
                    period_start=date(2026, 2, 1),
                    period_end=date(2026, 2, 28),
                    reason="FAILED",
                )
            ],
        ),
    )


def test_explanation_payload_drops_ids_and_sanitizes_merchants():
    payload = build_explanation_payload(_analytics_with_a_name_in_a_merchant())
    blob = payload.model_dump_json()

    assert "secret-stmt-id" not in blob
    assert "Santander" not in blob
    assert "0520" not in blob
    assert ACCOUNT_NUMBER not in blob
    assert "DOE" not in blob
    # aggregates that should be there
    assert payload.statements_excluded == 1
    assert payload.transaction_count == 3
    assert payload.cash_flow[0].transfers == "100.00"


def test_does_not_accept_a_transaction_object():
    # build_categorization_payload takes primitives only; there is no path that
    # passes a model. Passing an object where an int is expected fails closed.
    with pytest.raises((PrivacyBlockedError, TypeError, AttributeError)):
        build_categorization_payload(
            merchant_normalized="X",
            description_normalized="Y",
            amount_cents=object(),  # type: ignore[arg-type]
            direction="DEBIT",
        )
