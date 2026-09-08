"""The provider-agnostic contract.

A provider is given an already-sanitized, allowlisted payload
(`OutboundTransaction` / `OutboundAnalytics` from the Privacy Gateway) and
returns a small structured result. Two failure modes are kept distinct:

- **`LLMUnavailable`** -- the provider could not answer (timeout, rate limit,
  HTTP/API error, unparseable response). The gateway falls back to the next
  provider. This is the *only* trigger for fallback (owner decision).
- **`None`** -- the provider answered, but not usably (an unknown category, a
  malformed body). No fallback; the transaction goes to Review, an explanation
  is simply absent.
"""

import json
import re
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from app.models import CATEGORIES
from app.services.privacy_gateway import OutboundAnalytics, OutboundTransaction


class LLMUnavailable(Exception):
    """The provider failed to produce a result. Message carries only the
    provider name and exception class -- never payload content."""


@dataclass(frozen=True)
class CategorySuggestion:
    category: str
    confidence: float


@runtime_checkable
class LLMProvider(Protocol):
    name: str
    model: str

    def categorize(self, payload: OutboundTransaction) -> CategorySuggestion | None: ...

    def explain(self, payload: OutboundAnalytics) -> str | None: ...


_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.IGNORECASE)
_FIRST_OBJECT = re.compile(r"\{.*\}", re.DOTALL)


def parse_category_suggestion(raw: str | None) -> CategorySuggestion | None:
    """Parse a provider's classification reply. Returns None (not an error) for
    anything unusable -- so a bad answer routes to Review, it does not trigger a
    fallback."""
    if not raw:
        return None
    text = _FENCE.sub("", raw.strip())
    match = _FIRST_OBJECT.search(text)
    if match is None:
        return None
    try:
        obj = json.loads(match.group(0))
        category = obj["category"]
        confidence = float(obj["confidence"])
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None
    if category not in CATEGORIES:
        return None
    return CategorySuggestion(
        category=category, confidence=max(0.0, min(1.0, confidence))
    )
