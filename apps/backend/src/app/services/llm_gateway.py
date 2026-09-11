"""The one bridge between the application and an LLM provider.

This is the **only** module that imports both a Privacy Gateway payload builder
and `app.llm`. Every LLM-assisted feature calls a function here; there is no
other call site (enforced by `tests/test_llm_gateway.py`).

Fallback rule (owner decision): providers are tried in `configured_providers()`
order; one that raises `LLMUnavailable` (timeout, rate limit, HTTP/API error) is
skipped and the next is tried. A provider that *answers* -- even with a
low-confidence suggestion or nothing usable -- ends the walk. We never call the
fallback just because the primary was unsure; a weak answer routes to Review at
no extra cost.
"""

import logging
from dataclasses import dataclass
from typing import Literal

from app.llm.anthropic_provider import AnthropicProvider
from app.llm.base import CategorySuggestion, LLMProvider, LLMUnavailable
from app.llm.null import NullProvider
from app.llm.openai_provider import OpenAIProvider
from app.llm.providers import configured_providers
from app.services.analytics import Analytics
from app.services.privacy_gateway import (
    OutboundTransaction,
    PrivacyBlockedError,
    build_categorization_payload,
    build_explanation_payload,
)

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = {"anthropic": "claude-sonnet-5", "openai": "gpt-5.6-luna"}

# A minimal, fixed payload for REQ-SET-001's "test connection" -- cheap and
# fast (categorize, not explain: no extended thinking, ~120 max_tokens). Only
# whether the call raises LLMUnavailable matters; the suggestion is discarded.
_PING_TRANSACTION = OutboundTransaction(
    merchant="Test Merchant",
    description="Test transaction",
    amount="1.00",
    direction="debit",
)


@dataclass(frozen=True)
class Explanation:
    provider: str | None
    model: str | None
    text: str | None


NO_EXPLANATION = Explanation(provider=None, model=None, text=None)


def _chain() -> list[LLMProvider]:
    return configured_providers() or [NullProvider()]


def suggest_category(
    *,
    merchant_normalized: str | None,
    description_normalized: str,
    amount_cents: int,
    direction: str,
) -> CategorySuggestion | None:
    """An LLM category suggestion for one transaction, or ``None`` (skip / send
    to Review). Builds the sanitized payload first; if the Privacy Gateway
    refuses to produce one, no provider is called."""
    try:
        payload = build_categorization_payload(
            merchant_normalized=merchant_normalized,
            description_normalized=description_normalized,
            amount_cents=amount_cents,
            direction=direction,
        )
    except PrivacyBlockedError:
        logger.info("llm categorization skipped: privacy gateway blocked the payload")
        return None

    for provider in _chain():
        try:
            return provider.categorize(payload)
        except LLMUnavailable:
            continue
    return None


def test_provider_key(
    provider: Literal["anthropic", "openai"], api_key: str, model: str | None = None
) -> str | None:
    """REQ-SET-001: verify an API key works before it's saved. Returns ``None``
    on success, or an error string (provider name + exception class only --
    never payload content) on failure. Stateless -- never persists or logs the
    key; the only call site is `app/api/settings.py`."""
    instance: LLMProvider = (
        AnthropicProvider(api_key, model or _DEFAULT_MODEL["anthropic"])
        if provider == "anthropic"
        else OpenAIProvider(api_key, model or _DEFAULT_MODEL["openai"])
    )
    try:
        instance.categorize(_PING_TRANSACTION)
    except LLMUnavailable as exc:
        return str(exc)
    return None


def explain_analytics(analytics: Analytics) -> Explanation:
    """A plain-English summary of the analytics payload, labelled with its
    provider. All ``None`` when no provider is configured or every provider
    failed."""
    payload = build_explanation_payload(analytics)
    for provider in _chain():
        try:
            text = provider.explain(payload)
        except LLMUnavailable:
            continue
        if text:
            return Explanation(provider=provider.name, model=provider.model, text=text)
        return NO_EXPLANATION
    return NO_EXPLANATION
