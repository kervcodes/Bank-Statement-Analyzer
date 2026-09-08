"""The provider used when no API key is configured -- REQ-LLM-102: the app is
fully functional without an LLM. Every method returns None, so the deterministic
path behaves exactly as it does in Part 1."""

from app.llm.base import CategorySuggestion
from app.services.privacy_gateway import OutboundAnalytics, OutboundTransaction


class NullProvider:
    name = "null"
    model = "none"

    def categorize(self, payload: OutboundTransaction) -> CategorySuggestion | None:
        return None

    def explain(self, payload: OutboundAnalytics) -> str | None:
        return None
