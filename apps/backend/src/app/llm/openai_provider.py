"""OpenAI chat-completions client. Raw `httpx` (the project has no SDKs anywhere
and keeps its dependency surface small -- the `claude-api` skill recommends the
Anthropic SDK for the Claude path; the deviation and rationale are in
`docs/activity.md`).

The client accepts an injected `httpx.Client` so tests can drive it with a
`MockTransport` and never touch the network.
"""

import httpx

from app.llm.base import CategorySuggestion, LLMUnavailable, parse_category_suggestion
from app.models import CATEGORIES
from app.services.privacy_gateway import OutboundAnalytics, OutboundTransaction

_ENDPOINT = "https://api.openai.com/v1/chat/completions"

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


class OpenAIProvider:
    name = "openai"

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

    def _complete(self, system: str, user: str, *, max_tokens: int) -> str:
        try:
            resp = self._client.post(
                _ENDPOINT,
                headers={"Authorization": f"Bearer {self._key}"},
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    "max_tokens": max_tokens,
                },
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]
        except (httpx.HTTPError, KeyError, IndexError, ValueError, TypeError) as exc:
            raise LLMUnavailable(f"openai: {type(exc).__name__}") from exc

    def categorize(self, payload: OutboundTransaction) -> CategorySuggestion | None:
        raw = self._complete(
            _CATEGORIZE_SYSTEM, payload.model_dump_json(), max_tokens=120
        )
        return parse_category_suggestion(raw)

    def explain(self, payload: OutboundAnalytics) -> str | None:
        text = self._complete(
            _EXPLAIN_SYSTEM, payload.model_dump_json(), max_tokens=800
        ).strip()
        return text or None
