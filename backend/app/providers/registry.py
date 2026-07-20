"""Provider registry / factory.

Chooses the active provider from configuration. Real gateways register here so the
Evaluation Engine can resolve a provider by name without importing concrete classes.
"""
from __future__ import annotations

from app.core.config import settings
from app.providers.base import LLMProvider
from app.providers.mock import MockProvider
from app.providers.openrouter import OpenRouterProvider
from app.providers.qiniu import QiniuProvider

# name -> factory
_PROVIDERS: dict[str, type[LLMProvider]] = {
    "mock": MockProvider,
    "openrouter": OpenRouterProvider,
    "qiniu": QiniuProvider,
}


# Known gateways. Anything else (e.g. the seed defaults "openai"/"anthropic")
# is not a real provider here and is normalized to the configured default so a stale
# model row never crashes a run.
_KNOWN = ("mock", "openrouter", "qiniu")


def get_provider(name: str | None = None) -> LLMProvider:
    """Return a provider instance.

    If `name` is given, use it directly (lets a model route to its own provider).
    Otherwise pick the configured default provider when its key is present; if no
    real gateway is configured, fall back to the deterministic Mock provider so the
    pipeline still runs offline.

    A gateway name whose key is missing raises ValueError (misconfiguration — we
    must not silently produce fake scores). Any name outside the known set (e.g. a
    stale "openai" model row) is normalized to the default provider instead of
    crashing, so existing model-center seed data still runs.
    """
    if name is None:
        name = settings.default_provider
    if name not in _KNOWN:
        # Unknown/legacy provider label: route to the configured default rather than
        # failing the whole experiment.
        name = settings.default_provider
    if name in ("openrouter", "qiniu") and not _key_present(name):
        # A real gateway was requested but its key is missing. If the default gateway
        # itself has no key, there is no real provider at all -> Mock. Otherwise the
        # user explicitly pinned a gateway without configuring its key -> error.
        if not settings.provider_enabled:
            name = "mock"
        else:
            raise ValueError(
                f"Provider '{name}' requested but its API key is not configured"
            )
    factory = _PROVIDERS.get(name)
    if factory is None:
        raise ValueError(f"Unknown provider: {name}")
    return factory()


def _key_present(name: str) -> bool:
    if name == "openrouter":
        return bool(settings.openrouter_api_key.strip())
    if name == "qiniu":
        return bool(settings.qiniu_api_key.strip())
    return True


def active_provider_name() -> str:
    """The provider name the runner will use when no explicit model provider is set.

    Returns the configured default if its key is present, else falls back to Mock.
    """
    if settings.provider_enabled:
        return settings.default_provider if _key_present(settings.default_provider) else "mock"
    return "mock"
