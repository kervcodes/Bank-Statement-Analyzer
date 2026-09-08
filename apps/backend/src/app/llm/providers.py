"""Build the ordered provider chain from the environment.

Config is four independent env vars (owner decision -- provider and model are
never coupled in code):

- ``LLM_PROVIDER``   -- ``openai`` (default) or ``anthropic``; which one is tried first
- ``OPENAI_API_KEY`` / ``OPENAI_MODEL``     (model default ``gpt-5.6-luna``)
- ``ANTHROPIC_API_KEY`` / ``ANTHROPIC_MODEL`` (model default ``claude-sonnet-5``)

A provider is included only if its key is present. With no keys, the chain is
empty and the gateway uses `NullProvider`. The second provider is a fallback for
*provider failure only* -- never for a low-confidence answer.
"""

import os

from app.llm.anthropic_provider import AnthropicProvider
from app.llm.base import LLMProvider
from app.llm.openai_provider import OpenAIProvider

_OPENAI_DEFAULT_MODEL = "gpt-5.6-luna"
_ANTHROPIC_DEFAULT_MODEL = "claude-sonnet-5"


def configured_providers() -> list[LLMProvider]:
    primary = (os.environ.get("LLM_PROVIDER") or "openai").strip().lower()

    built: dict[str, LLMProvider] = {}
    if os.environ.get("OPENAI_API_KEY"):
        built["openai"] = OpenAIProvider(
            os.environ["OPENAI_API_KEY"],
            os.environ.get("OPENAI_MODEL") or _OPENAI_DEFAULT_MODEL,
        )
    if os.environ.get("ANTHROPIC_API_KEY"):
        built["anthropic"] = AnthropicProvider(
            os.environ["ANTHROPIC_API_KEY"],
            os.environ.get("ANTHROPIC_MODEL") or _ANTHROPIC_DEFAULT_MODEL,
        )

    order = (
        ["anthropic", "openai"] if primary == "anthropic" else ["openai", "anthropic"]
    )
    return [built[name] for name in order if name in built]
