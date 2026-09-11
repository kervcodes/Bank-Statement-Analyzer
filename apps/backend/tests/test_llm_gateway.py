"""Build-plan #8 Part 2, P2-3: the single LLM gateway.

Includes the build-plan's explicit leak test -- a description carrying an account
number and a person's name, and an assertion that neither reaches the provider.
"""

import re
from pathlib import Path

import pytest

from app.llm.base import CategorySuggestion, LLMUnavailable
from app.services import llm_gateway
from app.services.llm_gateway import explain_analytics, suggest_category
from app.services.privacy_gateway import OutboundAnalytics

ACCOUNT_NUMBER = "4012888812345678"
PERSON = "JOHN DOE"


class RecordingProvider:
    """Captures the payload it is handed and returns a fixed result."""

    def __init__(self, name="rec", *, suggestion=None, text=None, fail=False):
        self.name = name
        self.model = f"{name}-model"
        self._suggestion = suggestion
        self._text = text
        self._fail = fail
        self.categorize_payloads: list = []
        self.explain_payloads: list = []

    def categorize(self, payload):
        self.categorize_payloads.append(payload)
        if self._fail:
            raise LLMUnavailable("boom")
        return self._suggestion

    def explain(self, payload):
        self.explain_payloads.append(payload)
        if self._fail:
            raise LLMUnavailable("boom")
        return self._text


def _install(monkeypatch: pytest.MonkeyPatch, *providers):
    monkeypatch.setattr(llm_gateway, "configured_providers", lambda: list(providers))


# --- the leak test --------------------------------------------------------


def test_account_number_and_name_never_reach_the_provider(
    monkeypatch: pytest.MonkeyPatch,
):
    spy = RecordingProvider(suggestion=CategorySuggestion("Transfers", 0.9))
    _install(monkeypatch, spy)

    suggest_category(
        merchant_normalized="Zelle",
        description_normalized=(
            f"ZELLE TRANSFER TO {PERSON} 877-000-1111 ACCT {ACCOUNT_NUMBER} "
            "memo rent john.doe@example.com"
        ),
        amount_cents=120_000,
        direction="DEBIT",
    )

    assert len(spy.categorize_payloads) == 1
    blob = spy.categorize_payloads[0].model_dump_json()
    for secret in (ACCOUNT_NUMBER, PERSON, "JOHN", "DOE", "877-000-1111", "john.doe@"):
        assert secret not in blob, f"{secret!r} reached the provider: {blob!r}"
    # only the four allowlisted keys crossed the boundary
    assert set(spy.categorize_payloads[0].model_dump()) == {
        "merchant",
        "description",
        "amount",
        "direction",
    }


def test_privacy_blocked_payload_calls_no_provider(monkeypatch: pytest.MonkeyPatch):
    spy = RecordingProvider(suggestion=CategorySuggestion("Dining", 0.9))
    _install(monkeypatch, spy)

    # an unknown direction makes the gateway fail closed
    result = suggest_category(
        merchant_normalized="Netflix",
        description_normalized="NETFLIX",
        amount_cents=100,
        direction="REFUND",
    )
    assert result is None
    assert spy.categorize_payloads == []


# --- fallback semantics --------------------------------------------------


def test_falls_back_only_on_provider_failure(monkeypatch: pytest.MonkeyPatch):
    primary = RecordingProvider("primary", fail=True)
    fallback = RecordingProvider(
        "fallback", suggestion=CategorySuggestion("Fuel", 0.95)
    )
    _install(monkeypatch, primary, fallback)

    result = suggest_category(
        merchant_normalized="Shell",
        description_normalized="SHELL OIL",
        amount_cents=5000,
        direction="DEBIT",
    )
    assert result == CategorySuggestion("Fuel", 0.95)
    assert len(primary.categorize_payloads) == 1
    assert len(fallback.categorize_payloads) == 1


def test_does_not_fall_back_on_a_low_confidence_answer(
    monkeypatch: pytest.MonkeyPatch,
):
    primary = RecordingProvider(
        "primary", suggestion=CategorySuggestion("Shopping", 0.30)
    )
    fallback = RecordingProvider(
        "fallback", suggestion=CategorySuggestion("Dining", 0.99)
    )
    _install(monkeypatch, primary, fallback)

    result = suggest_category(
        merchant_normalized="Amazon",
        description_normalized="AMAZON.COM",
        amount_cents=2500,
        direction="DEBIT",
    )
    assert result == CategorySuggestion("Shopping", 0.30)  # the primary's weak answer
    assert fallback.categorize_payloads == []  # fallback never consulted


def test_does_not_fall_back_when_primary_returns_no_suggestion(
    monkeypatch: pytest.MonkeyPatch,
):
    primary = RecordingProvider("primary", suggestion=None)
    fallback = RecordingProvider(
        "fallback", suggestion=CategorySuggestion("Dining", 0.9)
    )
    _install(monkeypatch, primary, fallback)

    assert (
        suggest_category(
            merchant_normalized="Mystery",
            description_normalized="MYSTERY VENDOR",
            amount_cents=100,
            direction="DEBIT",
        )
        is None
    )
    assert fallback.categorize_payloads == []


def test_no_providers_configured_returns_none(monkeypatch: pytest.MonkeyPatch):
    _install(monkeypatch)  # empty chain -> NullProvider
    assert (
        suggest_category(
            merchant_normalized="Netflix",
            description_normalized="NETFLIX",
            amount_cents=100,
            direction="DEBIT",
        )
        is None
    )


def test_suggest_returns_none_when_every_provider_fails(
    monkeypatch: pytest.MonkeyPatch,
):
    _install(
        monkeypatch,
        RecordingProvider("a", fail=True),
        RecordingProvider("b", fail=True),
    )
    assert (
        suggest_category(
            merchant_normalized="Netflix",
            description_normalized="NETFLIX",
            amount_cents=100,
            direction="DEBIT",
        )
        is None
    )


# --- explain_analytics -------------------------------------------------


def _empty_analytics_payload() -> OutboundAnalytics:
    return OutboundAnalytics(
        cash_flow=[],
        spending_by_category=[],
        top_merchants=[],
        recurring_charges=[],
        trends={"current_period": None},
        statements_included=0,
        statements_excluded=0,
        transaction_count=0,
        date_range=None,
    )


def test_explain_labels_the_provider(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        llm_gateway, "build_explanation_payload", lambda a: _empty_analytics_payload()
    )
    _install(monkeypatch, RecordingProvider("openai", text="Spending was flat."))

    out = explain_analytics(analytics=None)  # payload build is monkeypatched
    assert out.provider == "openai"
    assert out.model == "openai-model"
    assert out.text == "Spending was flat."


def test_explain_all_none_without_a_provider(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        llm_gateway, "build_explanation_payload", lambda a: _empty_analytics_payload()
    )
    _install(monkeypatch)
    out = explain_analytics(analytics=None)
    assert out.provider is None and out.text is None


def test_explain_falls_back_on_provider_failure(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        llm_gateway, "build_explanation_payload", lambda a: _empty_analytics_payload()
    )
    _install(
        monkeypatch,
        RecordingProvider("primary", fail=True),
        RecordingProvider("fallback", text="Here is the summary."),
    )
    out = explain_analytics(analytics=None)
    assert out.provider == "fallback"
    assert out.text == "Here is the summary."


# --- test_provider_key (REQ-SET-001) -----------------------------------


class _FakeProvider:
    def __init__(self, api_key: str, model: str, outcome=None):
        self.api_key = api_key
        self.model = model
        self._outcome = outcome

    def categorize(self, _payload):
        if isinstance(self._outcome, Exception):
            raise self._outcome
        return self._outcome


def test_provider_key_returns_none_on_success(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        llm_gateway,
        "AnthropicProvider",
        lambda api_key, model: _FakeProvider(api_key, model),
    )

    assert llm_gateway.test_provider_key("anthropic", "sk-ant-fake") is None


def test_provider_key_returns_the_error_on_failure(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        llm_gateway,
        "OpenAIProvider",
        lambda api_key, model: _FakeProvider(
            api_key, model, outcome=LLMUnavailable("openai: HTTPStatusError")
        ),
    )

    assert (
        llm_gateway.test_provider_key("openai", "sk-bad") == "openai: HTTPStatusError"
    )


def test_provider_key_uses_the_default_model_when_none_given(
    monkeypatch: pytest.MonkeyPatch,
):
    captured = {}

    def _fake(api_key, model):
        captured["model"] = model
        return _FakeProvider(api_key, model)

    monkeypatch.setattr(llm_gateway, "AnthropicProvider", _fake)

    llm_gateway.test_provider_key("anthropic", "sk-ant-fake")

    assert captured["model"] == "claude-sonnet-5"


# --- import boundary --------------------------------------------------


def test_only_the_gateway_imports_app_llm():
    src = Path(__file__).resolve().parents[1] / "src" / "app"
    allowed = {src / "services" / "llm_gateway.py"}
    pattern = re.compile(r"^\s*(from app\.llm|import app\.llm)", re.MULTILINE)

    offenders = []
    for path in src.rglob("*.py"):
        if path in allowed or path.parts[-2] == "llm":
            continue
        if pattern.search(path.read_text(encoding="utf-8")):
            offenders.append(str(path.relative_to(src)))

    assert offenders == [], (
        f"modules importing app.llm outside the gateway: {offenders}"
    )
