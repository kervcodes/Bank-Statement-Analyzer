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

from app.llm.base import CategorySuggestion, LLMProvider, LLMUnavailable
from app.llm.null import NullProvider
from app.llm.providers import configured_providers
from app.services.analytics import Analytics
from app.services.privacy_gateway import (
    PrivacyBlockedError,
    build_categorization_payload,
    build_explanation_payload,
)

logger = logging.getLogger(__name__)


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
