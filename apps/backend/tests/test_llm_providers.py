"""Build-plan #8 Part 2, P2-2: the provider clients. No network -- every request
is served by an `httpx.MockTransport`."""

import json

import httpx
import pytest

from app.llm.anthropic_provider import AnthropicProvider
from app.llm.base import LLMUnavailable
from app.llm.null import NullProvider
from app.llm.openai_provider import OpenAIProvider
from app.llm.providers import configured_providers
from app.services.privacy_gateway import OutboundAnalytics, OutboundTransaction

TXN = OutboundTransaction(
    merchant="Netflix", description="NETFLIX.COM", amount="15.99", direction="debit"
)
EMPTY_ANALYTICS = OutboundAnalytics(
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


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def _openai_reply(content: str) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})


def _anthropic_reply(*blocks: dict) -> httpx.Response:
    return httpx.Response(200, json={"content": list(blocks)})


# --- NullProvider ----------------------------------------------------------


def test_null_provider_returns_none():
    p = NullProvider()
    assert p.categorize(TXN) is None
    assert p.explain(EMPTY_ANALYTICS) is None


# --- OpenAIProvider ------------------------------------------------------


def test_openai_categorize_parses_a_good_reply():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        captured["auth"] = request.headers.get("authorization")
        return _openai_reply('{"category": "Subscriptions", "confidence": 0.93}')

    p = OpenAIProvider("sk-test", "gpt-5.6-luna", client=_client(handler))
    result = p.categorize(TXN)

    assert result is not None
    assert result.category == "Subscriptions"
    assert result.confidence == pytest.approx(0.93)
    assert captured["auth"] == "Bearer sk-test"
    # only the allowlisted payload is in the user message
    user_msg = captured["body"]["messages"][-1]["content"]
    assert set(json.loads(user_msg)) == {
        "merchant",
        "description",
        "amount",
        "direction",
    }


def test_openai_unknown_category_is_not_a_suggestion():
    p = OpenAIProvider(
        "k",
        "m",
        client=_client(
            lambda r: _openai_reply('{"category": "Yacht", "confidence": 0.9}')
        ),
    )
    assert p.categorize(TXN) is None


def test_openai_malformed_reply_is_not_a_suggestion():
    p = OpenAIProvider(
        "k", "m", client=_client(lambda r: _openai_reply("I think it is groceries"))
    )
    assert p.categorize(TXN) is None


def test_openai_fenced_json_is_parsed():
    p = OpenAIProvider(
        "k",
        "m",
        client=_client(
            lambda r: _openai_reply(
                '```json\n{"category": "Dining", "confidence": 0.8}\n```'
            )
        ),
    )
    assert p.categorize(TXN).category == "Dining"


def test_openai_server_error_is_unavailable():
    p = OpenAIProvider("k", "m", client=_client(lambda r: httpx.Response(500)))
    with pytest.raises(LLMUnavailable):
        p.categorize(TXN)


def test_openai_timeout_is_unavailable():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("timed out", request=request)

    p = OpenAIProvider("k", "m", client=_client(handler))
    with pytest.raises(LLMUnavailable):
        p.categorize(TXN)


def test_openai_explain_returns_text_or_none():
    good = OpenAIProvider(
        "k", "m", client=_client(lambda r: _openai_reply("You spent more on dining."))
    )
    assert good.explain(EMPTY_ANALYTICS) == "You spent more on dining."
    blank = OpenAIProvider("k", "m", client=_client(lambda r: _openai_reply("   ")))
    assert blank.explain(EMPTY_ANALYTICS) is None


# --- AnthropicProvider --------------------------------------------------


def test_anthropic_categorize_parses_first_text_block():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        captured["key"] = request.headers.get("x-api-key")
        return _anthropic_reply(
            {"type": "text", "text": '{"category": "Fuel", "confidence": 0.88}'}
        )

    p = AnthropicProvider("ak-test", "claude-sonnet-5", client=_client(handler))
    result = p.categorize(TXN)

    assert result.category == "Fuel"
    assert captured["key"] == "ak-test"
    assert captured["body"]["thinking"] == {
        "type": "disabled"
    }  # off for classification


def test_anthropic_skips_a_leading_thinking_block():
    p = AnthropicProvider(
        "k",
        "m",
        client=_client(
            lambda r: _anthropic_reply(
                {"type": "thinking", "thinking": "hmm"},
                {
                    "type": "text",
                    "text": '{"category": "Groceries", "confidence": 0.7}',
                },
            )
        ),
    )
    assert p.categorize(TXN).category == "Groceries"


def test_anthropic_rate_limited_is_unavailable():
    p = AnthropicProvider("k", "m", client=_client(lambda r: httpx.Response(429)))
    with pytest.raises(LLMUnavailable):
        p.categorize(TXN)


def test_anthropic_explain_uses_adaptive_thinking_and_returns_text():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return _anthropic_reply({"type": "text", "text": "Spending rose in February."})

    p = AnthropicProvider("k", "m", client=_client(handler))
    assert p.explain(EMPTY_ANALYTICS) == "Spending rose in February."
    assert "thinking" not in captured["body"]  # left adaptive for the summary


def test_parse_category_suggestion_edge_cases():
    from app.llm.base import parse_category_suggestion

    assert parse_category_suggestion(None) is None
    assert parse_category_suggestion("") is None
    assert parse_category_suggestion("no json here") is None
    assert parse_category_suggestion('{"category": "Dining"}') is None  # no confidence
    out = parse_category_suggestion('{"category": "Dining", "confidence": 5}')
    assert out is not None and out.confidence == 1.0  # clamped


# --- configured_providers ---------------------------------------------------


def test_provider_chain_defaults_to_openai_primary(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "o")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "a")
    chain = configured_providers()
    assert [p.name for p in chain] == ["openai", "anthropic"]


def test_provider_chain_anthropic_primary(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("OPENAI_API_KEY", "o")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "a")
    assert [p.name for p in configured_providers()] == ["anthropic", "openai"]


def test_provider_chain_one_key_only(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "o")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-5.6-luna")
    chain = configured_providers()
    assert [p.name for p in chain] == ["openai"]
    assert chain[0].model == "gpt-5.6-luna"


def test_provider_chain_empty_without_keys(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert configured_providers() == []
