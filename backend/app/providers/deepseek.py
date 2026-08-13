"""DeepSeek provider — direct domestic gateway to DeepSeek models.

DeepSeek exposes an OpenAI-compatible ``/chat/completions`` endpoint at
``https://api.deepseek.com`` and is the default, cheapest strong domestic
gateway for this project. This adapter mirrors the robustness contract of the
other providers (bounded retry on transient failures, circuit breaker on
persistent 429s, no silent fallback), but is deliberately smaller: DeepSeek's
official catalog is paid-only and has no ``:free`` tier, so there is no token
bucket throttle path here.

DeepSeek specifics:
  * ``deepseek-reasoner`` returns its chain-of-thought in ``reasoning_content``
    and may leave ``content`` empty when the output budget is exhausted; like
    the Qiniu adapter we fall back to ``reasoning_content`` so the run still
    scores something instead of silently producing zero.
  * 402 Payment Required means the account balance is exhausted — a terminal,
    non-retryable condition surfaced immediately.
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
# Hard ceiling on a single backoff wait so Retry-After math never explodes.
_BACKOFF_MAX = 30.0
# Cross-row circuit breaker: after this many *consecutive* 429s (no successful
# response in between) the upstream is clearly throttled and will not recover on
# its own, so we abort the whole run instead of spinning row-by-row.
_RATE_LIMIT_BURST = 10
# Per-call 429 retry cap: a single row backs off at most this many times on 429.
_MAX_429_PER_CALL = 10


class DeepSeekProvider(LLMProvider):
    name = "deepseek"

    def __init__(self) -> None:
        self._api_key = settings.deepseek_api_key
        # Fail fast on a missing key: silently falling back to Mock would corrupt
        # evaluation results with fake data.
        if not self._api_key.strip():
            raise ValueError(
                "DeepSeekProvider requires DEEPSEEK_API_KEY; set it in .env (do not leave empty)"
            )
        self._base_url = settings.deepseek_base_url.rstrip("/")
        self._timeout = settings.eval_request_timeout
        # Consecutive 429 counter, reset on any successful response. The runner
        # calls get_provider() once per run, so this instance is scoped to a
        # single experiment run.
        self._consecutive_429 = 0

    async def complete(self, request: CompletionRequest) -> CompletionResult:
        return await self._call(request)

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
            "Content-Type": "application/json",
        }

        started = time.perf_counter()
        transient_attempts = 0
        call_429 = 0
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            while True:
                try:
                    resp = await client.post(
                        f"{self._base_url}/chat/completions", json=payload, headers=headers
                    )
                    if resp.status_code == 429:
                        self._consecutive_429 += 1
                        call_429 += 1
                        if call_429 >= _MAX_429_PER_CALL or self._consecutive_429 >= _RATE_LIMIT_BURST:
                            raise ProviderRateLimitedError(
                                "DeepSeek rate limited (429) persistently; aborting run"
                            )
                        await self._backoff(resp, self._consecutive_429)
                        continue
                    if resp.status_code >= 500:
                        transient_attempts += 1
                        if transient_attempts >= _RETRY_COUNT:
                            raise ProviderRateLimitedError(
                                f"DeepSeek returned {resp.status_code} persistently; aborting run"
                            )
                        await self._backoff(resp, transient_attempts)
                        continue
                    if resp.status_code >= 400:
                        # Client error other than 429 (e.g. 400/401/402/404): the
                        # request is bad, the key is invalid, or the balance is
                        # exhausted — retrying won't help, surface it immediately.
                        try:
                            detail = resp.json()
                        except Exception:  # noqa: BLE001
                            detail = resp.text
                        raise ProviderRateLimitedError(
                            f"DeepSeek returned {resp.status_code}: {detail}"
                        )
                    resp.raise_for_status()
                    data = resp.json()
                    # Any successful response resets the throttle counter.
                    self._consecutive_429 = 0
                    break
                except (httpx.TimeoutException, asyncio.TimeoutError):
                    # The configured eval_request_timeout elapsed; retry if attempts
                    # remain, else surface the failure to the runner.
                    transient_attempts += 1
                    if transient_attempts >= _RETRY_COUNT:
                        raise
                    await self._backoff(None, transient_attempts)

        latency_ms = int((time.perf_counter() - started) * 1000)

        # Robust parsing: tolerate missing usage / choices without crashing.
        choices = data.get("choices") or []
        if not choices:
            raise ProviderRateLimitedError("DeepSeek returned no choices in response")
        first = choices[0] or {}
        message = first.get("message") or {}
        text = message.get("content") or ""
        content_source = "content"
        if not text:
            reasoning = message.get("reasoning_content") or ""
            if reasoning:
                text = reasoning
                content_source = "reasoning_content"
        usage = data.get("usage", {}) or {}
        return CompletionResult(
            text=text,
            prompt_tokens=int(usage.get("prompt_tokens", 0)),
            completion_tokens=int(usage.get("completion_tokens", 0)),
            latency_ms=latency_ms,
            raw={
                "provider": "deepseek",
                "id": data.get("id"),
                "content_source": content_source,
                "finish_reason": first.get("finish_reason"),
            },
        )

    async def _backoff(self, resp: httpx.Response | None, attempt: int) -> None:
        if resp is not None:
            retry_after = resp.headers.get("Retry-After")
            if retry_after and retry_after.isdigit():
                await asyncio.sleep(int(retry_after))
                return
        # Exponential backoff: 0.5s, 1s, 2s, ... capped at _BACKOFF_MAX.
        await asyncio.sleep(min(_BACKOFF_BASE * (2 ** attempt), _BACKOFF_MAX))
