"""Unit tests for QiniuProvider.complete.

Mirrors the OpenRouter backoff tests but adds Qiniu-specific behavior:
  * normal 200 + usage -> parsed CompletionResult
  * 429 (plain) -> backoff then success
  * 429 + quota-exhausted body -> ProviderQuotaExhaustedError (no retry loop)
  * 400/401/404 -> immediate ProviderRateLimitedError (no retry)
  * 5xx -> retries then success
  * network timeout -> retries then raises
  * missing choices / missing usage -> safe defaults, no crash
  * concurrency: free-model token bucket lets many calls through quickly
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import httpx
import pytest

import app.providers.qiniu as qiniu_mod
from app.providers.base import (
    CompletionRequest,
    CompletionResult,
    ProviderQuotaExhaustedError,
    ProviderRateLimitedError,
)
from app.providers.qiniu import QiniuProvider

_RATE_LIMIT_BURST = qiniu_mod._RATE_LIMIT_BURST


@pytest.fixture(autouse=True)
def _qiniu_key(monkeypatch):
    """QiniuProvider now fails fast when no API key is configured. These unit
    tests mock the HTTP layer and only need the constructor to succeed, so give
    the singleton settings a dummy key for this module's tests.
    """
    monkeypatch.setattr(qiniu_mod.settings, "qiniu_api_key", "x")


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
    """httpx.AsyncClient replacement. `post` returns queued responses in order."""

    def __init__(self, responses: list[httpx.Response]):
        self._responses = list(responses)
        self.post = AsyncMock(side_effect=self._responses)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def _patch_client(monkeypatch, responses: list[httpx.Response]) -> _FakeClient:
    fake = _FakeClient(responses)
    monkeypatch.setattr(qiniu_mod.httpx, "AsyncClient", lambda **kw: fake)
    return fake


def _provider() -> QiniuProvider:
    p = QiniuProvider()
    p._api_key = "x"
    p._base_url = "http://x"
    p._timeout = 1.0
    return p


# ---------------------------------------------------------------------------
# happy path
# ---------------------------------------------------------------------------
async def test_ok_parses_result(monkeypatch):
    _patch_client(monkeypatch, [_ok_resp()])
    provider = _provider()
    result = await provider.complete(CompletionRequest(model_id="m", messages=[]))
    assert isinstance(result, CompletionResult)
    assert result.text == "answer"
    assert result.prompt_tokens == 3
    assert result.completion_tokens == 2
    assert result.raw["provider"] == "qiniu"
    assert result.raw["content_source"] == "content"
    assert provider._consecutive_429 == 0


async def test_ok_empty_content_falls_back_to_reasoning_content(monkeypatch):
    """Reasoning models can exhaust the token budget before `content` is set;
    the provider must fall back to `reasoning_content` instead of scoring 0."""
    _patch_client(
        monkeypatch,
        [
            httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "content": "",
                                "reasoning_content": "让我先想想……答案：4",
                            },
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
    provider = _provider()
    result = await provider.complete(CompletionRequest(model_id="m", messages=[]))
    assert result.text == "让我先想想……答案：4"
    assert result.raw["content_source"] == "reasoning_content"
    assert result.raw["finish_reason"] == "length"


async def test_ok_content_takes_precedence_over_reasoning(monkeypatch):
    """When both fields are present, `content` is the final answer and wins."""
    _patch_client(
        monkeypatch,
        [
            httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "content": "4",
                                "reasoning_content": "内部思考过程",
                            },
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
    provider = _provider()
    result = await provider.complete(CompletionRequest(model_id="m", messages=[]))
    assert result.text == "4"
    assert result.raw["content_source"] == "content"


async def test_ok_missing_usage_defaults(monkeypatch):
    """Missing usage falls back to 0 tokens (no crash)."""
    _patch_client(
        monkeypatch,
        [
            httpx.Response(
                200,
                json={"choices": [{"message": {"content": "hi"}}]},
                request=httpx.Request("POST", "http://x"),
            )
        ],
    )
    provider = _provider()
    result = await provider.complete(CompletionRequest(model_id="m", messages=[]))
    assert result.text == "hi"
    assert result.prompt_tokens == 0
    assert result.completion_tokens == 0


async def test_ok_missing_choices_raises(monkeypatch):
    """A 200 with no choices is treated as a provider error (not silent garbage)."""
    _patch_client(
        monkeypatch,
        [
            httpx.Response(
                200, json={"usage": {"prompt_tokens": 1, "completion_tokens": 1}},
                request=httpx.Request("POST", "http://x"),
            )
        ],
    )
    provider = _provider()
    with pytest.raises(ProviderRateLimitedError):
        await provider.complete(CompletionRequest(model_id="m", messages=[]))


# ---------------------------------------------------------------------------
# 429 handling
# ---------------------------------------------------------------------------
async def test_plain_429_backoff_then_success(monkeypatch):
    sleeps: list[float] = []
    real_sleep = asyncio.sleep

    async def spy_sleep(d):
        sleeps.append(d)
        return await real_sleep(0)

    monkeypatch.setattr(asyncio, "sleep", spy_sleep)

    # stay under the burst threshold, then succeed.
    responses = [_resp(429) for _ in range(_RATE_LIMIT_BURST - 1)] + [_ok_resp()]
    _patch_client(monkeypatch, responses)
    provider = _provider()

    result = await provider.complete(CompletionRequest(model_id="m", messages=[]))
    assert isinstance(result, CompletionResult)
    # not a quota error; breaker did not trip.
    assert provider._consecutive_429 == 0


async def test_429_quota_exhausted_stops(monkeypatch):
    """A 429 whose body signals quota exhaustion raises immediately, no backoff loop."""
    sleeps: list[float] = []
    real_sleep = asyncio.sleep

    async def spy_sleep(d):
        sleeps.append(d)
        return await real_sleep(0)

    monkeypatch.setattr(asyncio, "sleep", spy_sleep)

    responses = [
        _resp(
            429,
            json={"code": "429001", "message": "rate limit exceeded"},
        )
    ]
    _patch_client(monkeypatch, responses)
    provider = _provider()

    with pytest.raises(ProviderQuotaExhaustedError) as excinfo:
        await provider.complete(CompletionRequest(model_id="m", messages=[]))
    assert excinfo.value.quota_exhausted is True
    # quota exhaustion must NOT trigger the backoff/retry loop.
    assert sleeps == []


async def test_429_quota_exhausted_by_message(monkeypatch):
    """FreeQuotaExhausted in the message also trips quota exhaustion."""
    responses = [
        _resp(
            429,
            json={"error": {"code": "FailedOperation.FreeQuotaExhausted",
                            "message": "free quota exhausted"}},
        )
    ]
    _patch_client(monkeypatch, responses)
    provider = _provider()
    with pytest.raises(ProviderQuotaExhaustedError):
        await provider.complete(CompletionRequest(model_id="m", messages=[]))


async def test_plain_429_burst_trips_circuit_breaker(monkeypatch):
    """Enough consecutive plain 429s trip the cross-row circuit breaker."""
    sleeps: list[float] = []
    real_sleep = asyncio.sleep

    async def spy_sleep(d):
        sleeps.append(d)
        return await real_sleep(0)

    monkeypatch.setattr(asyncio, "sleep", spy_sleep)

    responses = [_resp(429) for _ in range(_RATE_LIMIT_BURST)]
    _patch_client(monkeypatch, responses)
    provider = _provider()

    with pytest.raises(ProviderRateLimitedError) as excinfo:
        await provider.complete(CompletionRequest(model_id="m", messages=[]))
    assert excinfo.value.quota_exhausted is False
    assert provider._consecutive_429 >= _RATE_LIMIT_BURST


# ---------------------------------------------------------------------------
# client errors: immediate, no retry
# ---------------------------------------------------------------------------
async def test_401_raises_immediately(monkeypatch):
    sleeps: list[float] = []
    real_sleep = asyncio.sleep

    async def spy_sleep(d):
        sleeps.append(d)
        return await real_sleep(0)

    monkeypatch.setattr(asyncio, "sleep", spy_sleep)
    _patch_client(monkeypatch, [_resp(401, json={"error": "unauthorized"})])
    provider = _provider()
    with pytest.raises(ProviderRateLimitedError):
        await provider.complete(CompletionRequest(model_id="m", messages=[]))
    assert sleeps == [], "client errors must not be retried"


async def test_400_raises_immediately(monkeypatch):
    _patch_client(monkeypatch, [_resp(400, json={"error": "bad request"})])
    provider = _provider()
    with pytest.raises(ProviderRateLimitedError):
        await provider.complete(CompletionRequest(model_id="m", messages=[]))


# ---------------------------------------------------------------------------
# 5xx / timeout: bounded retry
# ---------------------------------------------------------------------------
async def test_5xx_retries_then_success(monkeypatch):
    responses = [_resp(503) for _ in range(qiniu_mod._RETRY_COUNT - 1)] + [_ok_resp()]
    _patch_client(monkeypatch, responses)
    provider = _provider()
    result = await provider.complete(CompletionRequest(model_id="m", messages=[]))
    assert isinstance(result, CompletionResult)


async def test_5xx_exhausts_retries_raises(monkeypatch):
    responses = [_resp(500) for _ in range(qiniu_mod._RETRY_COUNT)]
    _patch_client(monkeypatch, responses)
    provider = _provider()
    with pytest.raises(ProviderRateLimitedError):
        await provider.complete(CompletionRequest(model_id="m", messages=[]))


async def test_timeout_retries_then_raises(monkeypatch):
    """Network timeouts retry up to _RETRY_COUNT then surface the failure."""

    class _TimeoutClient:
        def __init__(self):
            self.post = AsyncMock(side_effect=httpx.ConnectTimeout("timed out"))

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(qiniu_mod.httpx, "AsyncClient", lambda **kw: _TimeoutClient())
    provider = _provider()
    with pytest.raises(httpx.ConnectTimeout):
        await provider.complete(CompletionRequest(model_id="m", messages=[]))


# ---------------------------------------------------------------------------
# init guard
# ---------------------------------------------------------------------------
def test_init_without_key_raises(monkeypatch):
    monkeypatch.setattr(qiniu_mod.settings, "qiniu_api_key", "")
    with pytest.raises(ValueError):
        QiniuProvider()


# ---------------------------------------------------------------------------
# concurrency: free-model token bucket does not block under light load
# ---------------------------------------------------------------------------
async def test_free_model_concurrent_token_bucket(monkeypatch):
    """5 concurrent free-model calls (matching free_model_concurrency) all succeed without exhausting the RPM bucket."""
    _patch_client(monkeypatch, [_ok_resp() for _ in range(8)])
    provider = _provider()

    async def one(i: int) -> CompletionResult:
        return await provider.complete(
            CompletionRequest(model_id="qwen:free", messages=[], is_free=True)
        )

    results = await asyncio.gather(*(one(i) for i in range(8)))
    assert all(isinstance(r, CompletionResult) for r in results)
    assert all(r.text == "answer" for r in results)


async def test_non_free_model_skips_bucket(monkeypatch):
    """Non-free model (no is_free) skips the token bucket and calls directly."""
    _patch_client(monkeypatch, [_ok_resp()])
    provider = _provider()
    result = await provider.complete(
        CompletionRequest(model_id="qwen-plus", messages=[], is_free=False)
    )
    assert result.text == "answer"
    # bucket was never initialized.
    assert provider._free_bucket_lock is None


# ---------------------------------------------------------------------------
# regression: 429 message mentioning "quota" must NOT be misread as exhausted
# ---------------------------------------------------------------------------
async def test_plain_429_with_quota_word_is_not_exhausted(monkeypatch):
    """A 429 whose message mentions 'quota' but is a transient throttle must back off
    and retry, NOT be treated as quota-exhausted (which would abort the whole run)."""
    sleeps: list[float] = []
    real_sleep = asyncio.sleep

    async def spy_sleep(d):
        sleeps.append(d)
        return await real_sleep(0)

    monkeypatch.setattr(asyncio, "sleep", spy_sleep)
    # Below the burst threshold so it retries, then succeeds.
    responses = [
        _resp(429, json={"message": "rate limit: daily quota temporarily throttled"}),
        _resp(429, json={"message": "rate limit: daily quota temporarily throttled"}),
        _ok_resp(),
    ]
    _patch_client(monkeypatch, responses)
    provider = _provider()
    result = await provider.complete(CompletionRequest(model_id="m", messages=[]))
    assert isinstance(result, CompletionResult)
    # It must have backed off (retried), proving it was NOT treated as an immediate
    # quota-exhausted abort.
    assert sleeps


# ---------------------------------------------------------------------------
# 404 (client error) raises immediately, no retry
# ---------------------------------------------------------------------------
async def test_404_raises_immediately(monkeypatch):
    _patch_client(monkeypatch, [_resp(404, json={"error": "not found"})])
    provider = _provider()
    with pytest.raises(ProviderRateLimitedError):
        await provider.complete(CompletionRequest(model_id="m", messages=[]))


# ---------------------------------------------------------------------------
# token bucket actually throttles when rpm_cap is tiny
# ---------------------------------------------------------------------------
async def test_token_bucket_throttles_under_low_cap(monkeypatch):
    """With qiniu_rpm_cap=1, two back-to-back free-model calls must incur at least one
    real backoff wait (the bucket starts with 1 token and refills at 1/min)."""
    sleeps: list[float] = []
    real_sleep = asyncio.sleep

    async def spy_sleep(d):
        sleeps.append(d)
        return await real_sleep(0)

    monkeypatch.setattr(asyncio, "sleep", spy_sleep)
    monkeypatch.setattr(qiniu_mod.settings, "qiniu_rpm_cap", 1)
    _patch_client(monkeypatch, [_ok_resp(), _ok_resp()])
    provider = _provider()

    await provider.complete(CompletionRequest(model_id="qwen:free", messages=[], is_free=True))
    await provider.complete(CompletionRequest(model_id="qwen:free", messages=[], is_free=True))

    # The second call must have waited for a token to refill.
    assert any(s > 0 for s in sleeps), "token bucket did not throttle under low cap"
