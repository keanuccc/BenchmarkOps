"""Provider registry / factory.

Chooses the active provider from configuration. Real gateways register here so the
Evaluation Engine can resolve a provider by name without importing concrete classes.
"""
from __future__ import annotations

from app.core.config import settings
from app.providers.base import LLMProvider
from app.providers.mock import MockProvider
from app.providers.openrouter import OpenRouterProvider

# name -> factory
_PROVIDERS: dict[str, type[LLMProvider]] = {
    "mock": MockProvider,
    "openrouter": OpenRouterProvider,
}


def get_provider(name: str | None = None) -> LLMProvider:
    """Return a provider instance.

    If `name` is given, use it. Otherwise pick based on config: OpenRouter when a
    key is present, else the deterministic Mock provider.
    """
    if name is None:
        name = "openrouter" if settings.provider_enabled else "mock"
    factory = _PROVIDERS.get(name)
    if factory is None:
        raise ValueError(f"Unknown provider: {name}")
    return factory()


def active_provider_name() -> str:
    return "openrouter" if settings.provider_enabled else "mock"
