"""Anthropic Messages API client (the fallback provider). Raw `httpx` for
consistency with the rest of the codebase -- see the note in `openai_provider`
and `docs/activity.md` for why not the SDK.

`claude-sonnet-5` runs adaptive thinking by default; for a one-line
classification that is wasted latency and tokens, so `categorize` disables it and
the reply is parsed from the first `text` block regardless.
"""

import httpx

from app.llm.base import CategorySuggestion, LLMUnavailable, parse_category_suggestion
from app.models import CATEGORIES
from app.services.privacy_gateway import OutboundAnalytics, OutboundTransaction

_ENDPOINT = "https://api.anthropic.com/v1/messages"
_VERSION = "2023-06-01"

_CATEGORIZE_SYSTEM = (
    "You classify a single bank transaction into exactly one category from this "
    "fixed list. Never invent a category outside it.\n"
    "Categories: " + ", ".join(CATEGORIES) + "\n"
    "Reply with ONLY a JSON object and nothing else: "
    '{"category": "<one from the list>", "confidence": <number between 0 and 1>}.'
)
_EXPLAIN_SYSTEM = (
    "You explain already-computed personal-finance analytics in plain English "
    "for the account holder, in 2-4 short paragraphs. Use only the figures "
    "provided; never invent a number. You are describing results, never the "
    "source of any figure."
)


def _first_text_block(content: list[dict]) -> str | None:
    return next((b.get("text") for b in content if b.get("type") == "text"), None)


class AnthropicProvider:
    name = "anthropic"

    def __init__(
        self,
        api_key: str,
        model: str,
        *,
        timeout: float = 15.0,
        client: httpx.Client | None = None,
    ) -> None:
        self.model = model
        self._key = api_key
        self._client = client or httpx.Client(timeout=timeout)

    def _message(
        self, system: str, user: str, *, max_tokens: int, think: bool
    ) -> str | None:
        body: dict = {
            "model": self.model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        if not think:
            body["thinking"] = {"type": "disabled"}
        try:
            resp = self._client.post(
                _ENDPOINT,
                headers={"x-api-key": self._key, "anthropic-version": _VERSION},
                json=body,
            )
            resp.raise_for_status()
            return _first_text_block(resp.json()["content"])
        except (httpx.HTTPError, KeyError, IndexError, ValueError, TypeError) as exc:
            raise LLMUnavailable(f"anthropic: {type(exc).__name__}") from exc

    def categorize(self, payload: OutboundTransaction) -> CategorySuggestion | None:
        raw = self._message(
            _CATEGORIZE_SYSTEM,
            payload.model_dump_json(),
            max_tokens=120,
            think=False,
        )
        return parse_category_suggestion(raw)

    def explain(self, payload: OutboundAnalytics) -> str | None:
        text = self._message(
            _EXPLAIN_SYSTEM,
            payload.model_dump_json(),
            max_tokens=2000,
            think=True,
        )
        return (text or "").strip() or None
