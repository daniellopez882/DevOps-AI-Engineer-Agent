"""
Provider clients, built from configuration, with the key passed explicitly.

``llm_config.py`` built LangChain ``ChatAnthropic(model_name="claude-3-5-sonnet-20240620")``
-- a retired model, hardcoded -- and ``ChatOpenAI(model_name="gpt-4o")``, and
``DevOpsOSCrew.__init__`` constructed all six of them for every node, so a
node that used one provider failed if the *other* provider's key was missing.

crewai unwraps a LangChain model and rebuilds its own client from
``os.environ``; a key that lives only in ``.env`` never reaches it. crewai's
own ``LLM`` with an explicit ``api_key`` is what it actually wants.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from config import settings

Provider = str  # "anthropic" | "openai"

_factory: Callable[[Provider], Any] | None = None


class LLMNotConfigured(RuntimeError):
    pass


def set_llm_factory(factory: Callable[[Provider], Any] | None) -> None:
    """Install (or with ``None`` remove) the factory the tests use."""
    global _factory
    _factory = factory


def for_provider(provider: Provider, temperature: float = 0.2) -> Any:
    if _factory is not None:
        return _factory(provider)

    if provider == "anthropic":
        key = settings.ANTHROPIC_API_KEY.strip()
        if not key:
            raise LLMNotConfigured("ANTHROPIC_API_KEY is not set.")
        model = settings.ANTHROPIC_MODEL
        if not model.startswith("anthropic/"):
            model = f"anthropic/{model}"
    elif provider == "openai":
        key = settings.OPENAI_API_KEY.strip()
        if not key:
            raise LLMNotConfigured("OPENAI_API_KEY is not set.")
        model = settings.OPENAI_MODEL
    else:
        raise ValueError(f"unknown provider {provider!r}")

    from crewai import LLM

    return LLM(model=model, api_key=key, temperature=temperature)
