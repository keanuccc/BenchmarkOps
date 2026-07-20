"""OpenRouter provider — single gateway to all supported models.

Uses the OpenAI-compatible /chat/completions endpoint OpenRouter exposes. Selected
by the registry only when OPENROUTER_API_KEY is set; otherwise Mock is used.
"""
from __future__ import annotations

import asyncio
import time

import httpx

from app.core.config import settings
from app.providers.base import (
    CompletionRequest,
    CompletionResult,
    LLMProvider,
    ProviderRateLimitedError,
)

# Retry on transient upstream failures: 429 (rate limited), 5xx, or request
# timeouts. Per-row attempt count, independent of the cross-row circuit breaker.
_RETRY_COUNT = 3
# Exponential backoff base; each attempt doubles (0.5s -> 1s -> 2s -> ...).
_BACKOFF_BASE = 0.5
# Hard ceiling on a single backoff wait so a long Retry-After math never explodes.
_BACKOFF_MAX = 30.0
# Cross-row circuit breaker: once we see this many *consecutive* 429s (no
# successful response in between) the upstream is clearly throttled and will not
# recover on its own, so we abort the whole run instead of spinning row-by-row.
# Raised from 5 to 10: free models (e.g. hy3:free) can hit a few consecutive 429s
# on cold start even under proper throttling, and we must not abort a healthy run.
_RATE_LIMIT_BURST = 10

# Models whose id ends with this marker are OpenRouter free tiers. Probing showed
# hy3:free sustains high concurrency + RPM>=325, so we throttle with a token bucket
# (free_model_rpm_cap) rather than a fixed sleep — the bucket is sized well under the
# measured ceiling and rarely blocks in practice.
_FREE_MODEL_MARKER = ":free"
# Per-call 429 retry cap: a single row backs off at most this many times on 429.
# Guards against an alternating 429/200 pattern where the cross-row breaker never
# trips (each 200 resets the count) yet one row would otherwise spin until timeout.
_MAX_429_PER_CALL = 10


class OpenRouterProvider(LLMProvider):
    name = "openrouter"

    def __init__(self) -> None:
        self._api_key = settings.openrouter_api_key
        self._base_url = settings.openrouter_base_url.rstrip("/")
        self._timeout = settings.eval_request_timeout
        # Free-model token bucket (throttle, not serialize): caps overall send rate
        # under free_model_rpm_cap. Free models measured RPM>=325, so the bucket is
        # sized for headroom and rarely blocks. Created lazily on first use to bind
        # to whatever event loop the call runs on (provider is built once per run).
        self._free_bucket_lock: asyncio.Lock | None = None
        self._free_tokens: float = 0.0
        self._free_last_refill: float = 0.0
        # Consecutive 429 counter, reset on any successful response. The runner
        # calls get_provider() once per run, so this instance is scoped to a single
        # experiment run — the breaker never trips because of *another* run's
        # throttling (it only reacts to this run's own consecutive 429s).
        self._consecutive_429 = 0

    def _is_free_model(self, model_id: str) -> bool:
        return model_id.endswith(_FREE_MODEL_MARKER)

    async def complete(self, request: CompletionRequest) -> CompletionResult:
        # Free models: throttle via a token bucket (measured RPM>=325, so the bucket
        # is sized for headroom and rarely blocks) instead of a fixed sleep. This lets
        # the runner fire many rows concurrently without self-inflicting 429s. Non-free
        # models skip the bucket and keep their current high-throughput path.
        if self._is_free_model(request.model_id):
            await self._acquire_free_token()
            return await self._call(request)
        return await self._call(request)

    async def _acquire_free_token(self) -> None:
        """Block until a free-tier send token is available (token-bucket rate limit).

        Refills `free_model_rpm_cap` tokens per minute; caps in-flight send rate without
        forcing a fixed per-call sleep. Under normal load the bucket stays full and this
        returns immediately. Lazily initialized on first use to bind to the call's loop.
        """
        if self._free_bucket_lock is None:
            self._free_bucket_lock = asyncio.Lock()
            self._free_tokens = float(settings.free_model_rpm_cap)
            self._free_last_refill = time.perf_counter()
        async with self._free_bucket_lock:
            capacity = float(settings.free_model_rpm_cap)
            refill_per_sec = capacity / 60.0
            while self._free_tokens < 1.0:
                elapsed = time.perf_counter() - self._free_last_refill
                self._free_tokens = min(capacity, self._free_tokens + elapsed * refill_per_sec)
                self._free_last_refill = time.perf_counter()
                if self._free_tokens < 1.0:
                    # Sleep just long enough for one token, then re-check under the lock.
                    await asyncio.sleep((1.0 - self._free_tokens) / refill_per_sec)
            self._free_tokens -= 1.0

    async def _call(self, request: CompletionRequest) -> CompletionResult:
        payload: dict = {
            "model": request.model_id,
            "messages": [{"role": m.role, "content": m.content} for m in request.messages],
            "temperature": request.temperature,
        }
        if request.max_tokens is not None:
            payload["max_tokens"] = request.max_tokens
        payload.update(request.extra or {})

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "HTTP-Referer": settings.openrouter_http_referer,
            "X-Title": settings.openrouter_app_title,
            "Content-Type": "application/json",
        }

        started = time.perf_counter()
        last_exc: Exception | None = None
        # Instant-retry counter for transient non-rate-limit failures (5xx/timeout).
        transient_attempts = 0
        # Per-call 429 retry cap. A single row must not retry 429 forever: under an
        # alternating 429/200 pattern the cross-row breaker never trips (each 200
        # resets the count), so without this cap one slow row could spin until the
        # runner's wait_for timeout. Hitting the cap aborts this row like the breaker.
        call_429 = 0
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            while True:
                try:
                    resp = await client.post(
                        f"{self._base_url}/chat/completions", json=payload, headers=headers
                    )
                    if resp.status_code == 429:
                        # Persistent throttle: keep backing off, but count it toward
                        # the cross-row circuit breaker. When the burst threshold is
                        # hit the upstream clearly won't recover on its own, so we
                        # abort the whole run (runner turns it into a 'failed' status)
                        # instead of spinning row-by-row for hours.
                        self._consecutive_429 += 1
                        call_429 += 1
                        if call_429 >= _MAX_429_PER_CALL or self._consecutive_429 >= _RATE_LIMIT_BURST:
                            raise ProviderRateLimitedError(
                                "OpenRouter rate limited (429) persistently; aborting run"
                            )
                        last_exc = httpx.HTTPStatusError(
                            "upstream returned 429",
                            request=resp.request,
                            response=resp,
                        )
                        await self._backoff(resp, self._consecutive_429)
                        continue
                    if resp.status_code >= 500:
                        # Server-side transient error: retry a bounded number of
                        # times, distinct from the rate-limit circuit breaker.
                        transient_attempts += 1
                        if transient_attempts >= _RETRY_COUNT:
                            resp.raise_for_status()
                        last_exc = httpx.HTTPStatusError(
                            f"upstream returned {resp.status_code}",
                            request=resp.request,
                            response=resp,
                        )
                        await self._backoff(resp, transient_attempts)
                        continue
                    resp.raise_for_status()
                    data = resp.json()
                    # Any successful response resets the throttle counter.
                    self._consecutive_429 = 0
                    break
                except (httpx.TimeoutException, asyncio.TimeoutError) as exc:
                    # The configured eval_request_timeout elapsed; retry if attempts
                    # remain, else surface the failure to the runner.
                    transient_attempts += 1
                    last_exc = exc
                    if transient_attempts >= _RETRY_COUNT:
                        raise
                    await self._backoff(None, transient_attempts)

        latency_ms = int((time.perf_counter() - started) * 1000)

        text = data["choices"][0]["message"]["content"] or ""
        usage = data.get("usage", {}) or {}
        return CompletionResult(
            text=text,
            prompt_tokens=int(usage.get("prompt_tokens", 0)),
            completion_tokens=int(usage.get("completion_tokens", 0)),
            latency_ms=latency_ms,
            raw={"provider": "openrouter", "id": data.get("id")},
        )

    async def _backoff(self, resp: httpx.Response | None, attempt: int) -> None:
        if resp is not None:
            retry_after = resp.headers.get("Retry-After")
            if retry_after and retry_after.isdigit():
                await asyncio.sleep(int(retry_after))
                return
        # Exponential backoff: 0.5s, 1s, 2s, ... capped at _BACKOFF_MAX so a single
        # wait never grows unbounded.
        await asyncio.sleep(min(_BACKOFF_BASE * (2 ** attempt), _BACKOFF_MAX))
