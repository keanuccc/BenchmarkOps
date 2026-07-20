"""Unit tests for provider routing: registry default + per-model provider pinning.

Verifies the multi-provider router:
  * default_provider is returned when no name is given (and its key is present)
  * an explicit known name routes to that provider
  * unknown/legacy provider labels (e.g. stale "openai" seed rows) are normalized
    to the default provider instead of crashing a run
  * a known gateway *with no key* raises ValueError (misconfiguration)
  * a model pinning provider="openrouter" routes to OpenRouter even when the
    default is qiniu
"""
from __future__ import annotations

import pytest

import app.providers.registry as registry_mod
from app.providers.base import LLMProvider
from app.providers.mock import MockProvider
from app.providers.openrouter import OpenRouterProvider
from app.providers.qiniu import QiniuProvider
from app.providers.registry import get_provider


def _set(monkeypatch, *, openrouter_key: str = "", qiniu_key: str = "", default: str = "qiniu"):
    monkeypatch.setattr(registry_mod.settings, "openrouter_api_key", openrouter_key)
    monkeypatch.setattr(registry_mod.settings, "qiniu_api_key", qiniu_key)
    monkeypatch.setattr(registry_mod.settings, "default_provider", default)


def test_default_qiniu_routes_to_qiniu(monkeypatch):
    _set(monkeypatch, qiniu_key="sk-x", default="qiniu")
    provider = get_provider()
    assert isinstance(provider, QiniuProvider)
    assert provider.name == "qiniu"


def test_explicit_openrouter_routes_openrouter(monkeypatch):
    _set(monkeypatch, openrouter_key="sk-or", qiniu_key="sk-x", default="qiniu")
    provider = get_provider("openrouter")
    assert isinstance(provider, OpenRouterProvider)


def test_explicit_qiniu_routes_qiniu(monkeypatch):
    _set(monkeypatch, qiniu_key="sk-x", default="openrouter")
    provider = get_provider("qiniu")
    assert isinstance(provider, QiniuProvider)


def test_unknown_provider_normalized_to_default(monkeypatch):
    """A stale/unknown provider label must not crash a run; it routes to the default."""
    _set(monkeypatch, qiniu_key="sk-x", default="qiniu")
    provider = get_provider("openai")  # legacy seed row label
    assert isinstance(provider, QiniuProvider)


def test_known_gateway_without_key_raises(monkeypatch):
    """Pinning qiniu but having only an OpenRouter key configured is a misconfig."""
    _set(monkeypatch, openrouter_key="sk-or", qiniu_key="", default="openrouter")
    with pytest.raises(ValueError):
        get_provider("qiniu")


def test_no_real_key_falls_back_to_mock(monkeypatch):
    _set(monkeypatch, openrouter_key="", qiniu_key="", default="qiniu")
    provider = get_provider()
    assert isinstance(provider, MockProvider)


def test_provider_enabled_true_with_any_key(monkeypatch):
    _set(monkeypatch, openrouter_key="", qiniu_key="sk-x")
    assert registry_mod.settings.provider_enabled is True
    _set(monkeypatch, openrouter_key="sk-or", qiniu_key="")
    assert registry_mod.settings.provider_enabled is True
    _set(monkeypatch, openrouter_key="", qiniu_key="")
    assert registry_mod.settings.provider_enabled is False


def test_model_pin_openrouter_beats_default_qiniu(monkeypatch):
    """A model whose provider is pinned to openrouter must route there even though
    the configured default is qiniu."""
    _set(monkeypatch, openrouter_key="sk-or", qiniu_key="sk-x", default="qiniu")
    provider = get_provider("openrouter")
    assert isinstance(provider, OpenRouterProvider)
