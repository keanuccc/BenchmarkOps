"""OpenRouter provider — single gateway to all supported models.

Uses the OpenAI-compatible /chat/completions endpoint OpenRouter exposes. Selected
by the registry only when OPENROUTER_API_KEY is set; otherwise Mock is used.
"""
from __future__ import annotations

import asyncio
import time

import httpx

from app.core.config import settings
from app.providers.base import CompletionRequest, CompletionResult, LLMProvider

# Retry on transient upstream failures: 429 (rate limited), 5xx, or request
# timeouts. Backoff base grows 0.5s -> 1s -> 2s (capped at _RETRY_COUNT).
_RETRY_COUNT = 3
_BACKOFF_BASE = 0.5


class OpenRouterProvider(LLMProvider):
    name = "openrouter"

    def __init__(self) -> None:
        self._api_key = settings.openrouter_api_key
        self._base_url = settings.openrouter_base_url.rstrip("/")
        self._timeout = settings.eval_request_timeout

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
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            for attempt in range(_RETRY_COUNT):
                try:
                    resp = await client.post(
                        f"{self._base_url}/chat/completions", json=payload, headers=headers
                    )
                    if resp.status_code == 429 or resp.status_code >= 500:
                        last_exc = httpx.HTTPStatusError(
                            f"upstream returned {resp.status_code}",
                            request=resp.request,
                            response=resp,
                        )
                        await self._backoff(resp, attempt)
                        continue
                    resp.raise_for_status()
                    data = resp.json()
                    break
                except (httpx.TimeoutException, asyncio.TimeoutError) as exc:
                    # The configured eval_request_timeout elapsed; retry if attempts remain.
                    last_exc = exc
                    await self._backoff(None, attempt)
            else:
                # Exhausted retries without a successful response.
                assert last_exc is not None
                raise last_exc

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
        # Exponential backoff: 0.5s, 1s, 2s, ... (capped so it never explodes).
        await asyncio.sleep(_BACKOFF_BASE * (2 ** attempt))
