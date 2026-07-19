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
_RATE_LIMIT_BURST = 5
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
        # Consecutive 429 counter, reset on any successful response. The runner
        # calls get_provider() once per run, so this instance is scoped to a single
        # experiment run — the breaker never trips because of *another* run's
        # throttling (it only reacts to this run's own consecutive 429s).
        self._consecutive_429 = 0

    async def complete(self, request: CompletionRequest) -> CompletionResult:
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
