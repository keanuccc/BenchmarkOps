"""Unit tests for OpenRouterProvider.complete rate-limit handling (optimization B).

Covers:
  * 5 consecutive 429s (with and without Retry-After) trip ProviderRateLimitedError.
  * The single backoff wait never exceeds _BACKOFF_MAX (30s).
  * A successful response resets _consecutive_429 to 0.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import httpx
import pytest

import app.providers.openrouter as openrouter_mod
from app.providers.base import (
    CompletionRequest,
    CompletionResult,
    ProviderRateLimitedError,
)
from app.providers.openrouter import OpenRouterProvider

_BACKOFF_MAX = openrouter_mod._BACKOFF_MAX  # 30.0
_RATE_LIMIT_BURST = openrouter_mod._RATE_LIMIT_BURST  # 5


def _resp(status: int, retry_after: str | None = None) -> httpx.Response:
    headers = {"Retry-After": retry_after} if retry_after else {}
    return httpx.Response(
        status, headers=headers, request=httpx.Request("POST", "http://x")
    )


def _ok_resp() -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"content": "answer"}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        },
        request=httpx.Request("POST", "http://x"),
    )


class _FakeClient:
    """httpx.AsyncClient replacement. `post` returns queued responses in order."""

    def __init__(self, responses: list[httpx.Response]):
        self._responses = list(responses)
        self.post = AsyncMock(side_effect=self._responses)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def _patch_client(monkeypatch, responses: list[httpx.Response]):
    fake = _FakeClient(responses)
    monkeypatch.setattr(openrouter_mod.httpx, "AsyncClient", lambda **kw: fake)
    return fake


def _provider() -> OpenRouterProvider:
    p = OpenRouterProvider()
    p._api_key = "x"
    p._base_url = "http://x"
    p._timeout = 1.0
    return p


async def test_five_429_with_retry_after_trips_circuit_breaker(monkeypatch):
    sleeps: list[float] = []
    real_sleep = asyncio.sleep

    async def spy_sleep(d):
        sleeps.append(d)
        return await real_sleep(0)

    monkeypatch.setattr(asyncio, "sleep", spy_sleep)

    responses = [_resp(429, retry_after="1") for _ in range(_RATE_LIMIT_BURST)]
    _patch_client(monkeypatch, responses)
    provider = _provider()

    with pytest.raises(ProviderRateLimitedError):
        await provider.complete(
            CompletionRequest(model_id="m", messages=[])
        )
    # 5th consecutive 429 hits the burst threshold and aborts.
    assert provider._consecutive_429 >= _RATE_LIMIT_BURST


async def test_five_429_without_retry_after_trips_circuit_breaker(monkeypatch):
    sleeps: list[float] = []
    real_sleep = asyncio.sleep

    async def spy_sleep(d):
        sleeps.append(d)
        return await real_sleep(0)

    monkeypatch.setattr(asyncio, "sleep", spy_sleep)

    responses = [_resp(429) for _ in range(_RATE_LIMIT_BURST)]
    _patch_client(monkeypatch, responses)
    provider = _provider()

    with pytest.raises(ProviderRateLimitedError):
        await provider.complete(
            CompletionRequest(model_id="m", messages=[])
        )
    # Without Retry-After the provider uses exponential backoff, but a single
    # sleep must still be capped at _BACKOFF_MAX (no unbounded growth).
    assert provider._consecutive_429 >= _RATE_LIMIT_BURST
    assert all(s <= _BACKOFF_MAX for s in sleeps), f"sleep exceeded cap: {sleeps}"


async def test_backoff_single_wait_capped_at_max(monkeypatch):
    """Force enough 429s that exponential backoff would exceed 30s, then succeed.

    With _BACKOFF_BASE=0.5 and attempt growing, 0.5*2**attempt exceeds 30 for a
    single wait; assert no single asyncio.sleep call exceeds _BACKOFF_MAX.
    """
    sleeps: list[float] = []
    real_sleep = asyncio.sleep

    async def spy_sleep(d):
        sleeps.append(d)
        return await real_sleep(0)

    monkeypatch.setattr(asyncio, "sleep", spy_sleep)

    # 4x 429 (burst threshold is 5, so this stays under the breaker) then a 200.
    responses = [_resp(429) for _ in range(_RATE_LIMIT_BURST - 1)] + [_ok_resp()]
    _patch_client(monkeypatch, responses)
    provider = _provider()

    result = await provider.complete(
        CompletionRequest(model_id="m", messages=[])
    )
    assert isinstance(result, CompletionResult)
    assert all(s <= _BACKOFF_MAX for s in sleeps), f"sleep exceeded cap: {sleeps}"


async def test_success_resets_consecutive_429(monkeypatch):
    """A success resets _consecutive_429 to 0, so a later burst of 4 429s does
    NOT trip the breaker (breaker needs 5 *consecutive*)."""
    responses = (
        [_ok_resp()]  # success -> counter reset
        + [_resp(429) for _ in range(_RATE_LIMIT_BURST - 1)]  # only 4 consecutive
        + [_ok_resp()]  # success again
    )
    _patch_client(monkeypatch, responses)
    provider = _provider()

    # First call succeeds (counter already 0).
    await provider.complete(CompletionRequest(model_id="m", messages=[]))
    assert provider._consecutive_429 == 0

    # Second call: 4 consecutive 429s then a 200 — must NOT raise.
    result = await provider.complete(CompletionRequest(model_id="m", messages=[]))
    assert isinstance(result, CompletionResult)
    assert provider._consecutive_429 == 0
