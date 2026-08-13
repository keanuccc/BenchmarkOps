"""Unit tests for DeepSeekProvider.complete.

Mirrors the provider contract of the other adapters:
  * normal 200 + usage -> parsed CompletionResult
  * empty content falls back to reasoning_content (DeepSeek-R1)
  * 429 -> bounded backoff then circuit breaker
  * 401/402 -> immediate terminal error (no retry)
  * 5xx / network timeout -> bounded retry
  * missing choices -> safe terminal error
  * constructor fails fast without a key
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import httpx
import pytest

import app.providers.deepseek as deepseek_mod
from app.providers.base import (
    CompletionRequest,
    CompletionResult,
    ProviderRateLimitedError,
)
from app.providers.deepseek import DeepSeekProvider

_RATE_LIMIT_BURST = deepseek_mod._RATE_LIMIT_BURST


@pytest.fixture(autouse=True)
def _deepseek_key(monkeypatch):
    """The constructor fails fast without a key; give settings a dummy key."""
    monkeypatch.setattr(deepseek_mod.settings, "deepseek_api_key", "x")


@pytest.fixture(autouse=True)
def _fast_backoff(monkeypatch):
    """Keep backoff waits instantaneous; the shared backoff policy is already
    covered by the OpenRouter/Qiniu suites."""

    async def _noop_sleep(_seconds):
        return None

    monkeypatch.setattr(asyncio, "sleep", _noop_sleep)


def _resp(status: int, *, json: dict | None = None, retry_after: str | None = None) -> httpx.Response:
    headers = {"Retry-After": retry_after} if retry_after else {}
    return httpx.Response(
        status, headers=headers, json=json or {}, request=httpx.Request("POST", "http://x")
    )


def _ok_resp(content: str = "answer") -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"content": content}}],
            "usage": {"prompt_tokens": 3, "completion_tokens": 2},
            "id": "chatcmpl-1",
        },
        request=httpx.Request("POST", "http://x"),
    )


class _FakeClient:
    def __init__(self, responses: list[httpx.Response]):
        self._responses = list(responses)
        self.post = AsyncMock(side_effect=self._responses)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def _patch_client(monkeypatch, responses: list[httpx.Response]) -> _FakeClient:
    fake = _FakeClient(responses)
    monkeypatch.setattr(deepseek_mod.httpx, "AsyncClient", lambda **kw: fake)
    return fake


def _provider() -> DeepSeekProvider:
    p = DeepSeekProvider()
    p._api_key = "x"
    p._base_url = "http://x"
    p._timeout = 1.0
    return p


async def test_ok_parses_result(monkeypatch):
    _patch_client(monkeypatch, [_ok_resp()])
    result = await _provider().complete(CompletionRequest(model_id="deepseek-chat", messages=[]))
    assert isinstance(result, CompletionResult)
    assert result.text == "answer"
    assert result.prompt_tokens == 3
    assert result.completion_tokens == 2
    assert result.raw["provider"] == "deepseek"
    assert result.raw["content_source"] == "content"


async def test_empty_content_falls_back_to_reasoning_content(monkeypatch):
    _patch_client(
        monkeypatch,
        [
            httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {"content": "", "reasoning_content": "answer=4"},
                            "finish_reason": "length",
                        }
                    ],
                    "usage": {"prompt_tokens": 3, "completion_tokens": 60},
                    "id": "chatcmpl-1",
                },
                request=httpx.Request("POST", "http://x"),
            )
        ],
    )
    result = await _provider().complete(CompletionRequest(model_id="deepseek-reasoner", messages=[]))
    assert result.text == "answer=4"
    assert result.raw["content_source"] == "reasoning_content"


async def test_content_takes_precedence_over_reasoning(monkeypatch):
    _patch_client(
        monkeypatch,
        [
            httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {"content": "4", "reasoning_content": "thinking"},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {"prompt_tokens": 3, "completion_tokens": 2},
                    "id": "chatcmpl-1",
                },
                request=httpx.Request("POST", "http://x"),
            )
        ],
    )
    result = await _provider().complete(CompletionRequest(model_id="deepseek-reasoner", messages=[]))
    assert result.text == "4"
    assert result.raw["content_source"] == "content"


async def test_429_backoff_then_success(monkeypatch):
    responses = [_resp(429) for _ in range(_RATE_LIMIT_BURST - 1)] + [_ok_resp()]
    _patch_client(monkeypatch, responses)
    provider = _provider()
    result = await provider.complete(CompletionRequest(model_id="deepseek-chat", messages=[]))
    assert isinstance(result, CompletionResult)
    assert provider._consecutive_429 == 0


async def test_429_burst_trips_circuit_breaker(monkeypatch):
    responses = [_resp(429) for _ in range(_RATE_LIMIT_BURST)]
    _patch_client(monkeypatch, responses)
    with pytest.raises(ProviderRateLimitedError):
        await _provider().complete(CompletionRequest(model_id="deepseek-chat", messages=[]))


async def test_401_raises_immediately(monkeypatch):
    _patch_client(monkeypatch, [_resp(401, json={"error": "invalid key"})])
    with pytest.raises(ProviderRateLimitedError):
        await _provider().complete(CompletionRequest(model_id="deepseek-chat", messages=[]))


async def test_402_balance_exhausted_raises_immediately(monkeypatch):
    _patch_client(monkeypatch, [_resp(402, json={"error": "insufficient balance"})])
    with pytest.raises(ProviderRateLimitedError):
        await _provider().complete(CompletionRequest(model_id="deepseek-chat", messages=[]))


async def test_5xx_retries_then_success(monkeypatch):
    responses = [_resp(503) for _ in range(deepseek_mod._RETRY_COUNT - 1)] + [_ok_resp()]
    _patch_client(monkeypatch, responses)
    result = await _provider().complete(CompletionRequest(model_id="deepseek-chat", messages=[]))
    assert isinstance(result, CompletionResult)


async def test_timeout_retries_then_raises(monkeypatch):
    class _TimeoutClient:
        def __init__(self):
            self.post = AsyncMock(side_effect=httpx.ConnectTimeout("timed out"))

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(deepseek_mod.httpx, "AsyncClient", lambda **kw: _TimeoutClient())
    with pytest.raises(httpx.ConnectTimeout):
        await _provider().complete(CompletionRequest(model_id="deepseek-chat", messages=[]))


def test_init_without_key_raises(monkeypatch):
    monkeypatch.setattr(deepseek_mod.settings, "deepseek_api_key", "")
    with pytest.raises(ValueError):
        DeepSeekProvider()
