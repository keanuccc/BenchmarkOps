"""Qiniu Cloud AI Token API provider — second model gateway.

Uses the OpenAI-compatible /chat/completions endpoint Qiniu exposes
(`https://api.qnaigc.com/v1`). Selected by the registry only when QINIU_API_KEY is
set. Mirrors OpenRouterProvider's shape (OpenAI-compatible payload, httpx.AsyncClient,
parse `choices[].message.content` + `usage`) so the two gateways are interchangeable
behind the registry.

Differences / robustness:
  * 429 is classified into a transient throttle (back off + retry) vs a *quota
    exhausted* signal (e.g. `FailedOperation.FreeQuotaExhausted` / code `429001`),
    which raises ProviderQuotaExhaustedError so the runner stops instead of spinning.
  * Missing `usage` / missing `choices` fall back to safe defaults instead of crashing.
  * All network calls are wrapped in the configured eval_request_timeout.
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
    ProviderQuotaExhaustedError,
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
_RATE_LIMIT_BURST = 10
# Per-call 429 retry cap: a single row backs off at most this many times on 429.
# Guards against an alternating 429/200 pattern where the cross-row breaker never
# trips (each 200 resets the count) yet one row would otherwise spin until timeout.
_MAX_429_PER_CALL = 10

# Qiniu error codes / messages that mean "quota exhausted" — retrying today is
# futile, so we raise ProviderQuotaExhaustedError (the runner stops, no backoff loop).
_QUOTA_EXHAUSTED_CODES = {"429001", "FailedOperation.FreeQuotaExhausted"}


class QiniuProvider(LLMProvider):
    name = "qiniu"

    def __init__(self) -> None:
        self._api_key = settings.qiniu_api_key
        # Fail fast on a missing key: silently falling back to Mock would corrupt
        # evaluation results with fake data. Callers pick this provider only when a
        # real Qiniu key is configured, so an empty key is a misconfiguration.
        if not self._api_key.strip():
            raise ValueError(
                "QiniuProvider requires QINIU_API_KEY; set it in .env (do not leave empty)"
            )
        self._base_url = settings.qiniu_base_url.rstrip("/")
        self._timeout = settings.eval_request_timeout
        # Free-model token bucket (throttle, not serialize): caps overall send rate
        # under qiniu_rpm_cap=75. Created lazily on first use to bind to whatever
        # event loop the call runs on (provider is built once per run).
        self._free_bucket_lock: asyncio.Lock | None = None
        self._free_tokens: float = 0.0
        self._free_last_refill: float = 0.0
        # Consecutive 429 counter, reset on any successful response. The runner calls
        # get_provider() once per run, so this instance is scoped to a single
        # experiment run — the breaker never trips because of *another* run's
        # throttling (it only reacts to this run's own consecutive 429s).
        self._consecutive_429 = 0

    def _is_free_model(self, request: CompletionRequest) -> bool:
        # The Qiniu model id need not carry a ":free" suffix, so free-model detection
        # is driven by: (1) the control-plane request.is_free flag the runner sets from
        # the model's metadata, (2) the conventional ":free" marker, (3) the configured
        # qiniu_free_models id list as a fallback.
        if request.is_free:
            return True
        if request.model_id.endswith(":free"):
            return True
        return request.model_id in settings.qiniu_free_set

    async def complete(self, request: CompletionRequest) -> CompletionResult:
        # Free-model throttling via a token bucket (measured RPM well above the cap),
        # so the runner can fire many rows concurrently without self-inflicting 429s.
        if self._is_free_model(request):
            await self._acquire_free_token()
        return await self._call(request)

    async def _acquire_free_token(self) -> None:
        """Block until a free-tier send token is available (token-bucket rate limit).

        Refills `qiniu_rpm_cap` tokens per minute; caps in-flight send rate without
        forcing a fixed per-call sleep. Under normal load the bucket stays full and this
        returns immediately. Lazily initialized on first use to bind to the call's loop.
        """
        if self._free_bucket_lock is None:
            self._free_bucket_lock = asyncio.Lock()
            self._free_tokens = float(settings.qiniu_rpm_cap)
            self._free_last_refill = time.perf_counter()
        async with self._free_bucket_lock:
            capacity = float(settings.qiniu_rpm_cap)
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
            "Content-Type": "application/json",
        }

        started = time.perf_counter()
        last_exc: Exception | None = None
        # Instant-retry counter for transient non-rate-limit failures (5xx/timeout).
        transient_attempts = 0
        # Per-call 429 retry cap. A single row must not retry 429 forever.
        call_429 = 0
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            while True:
                try:
                    resp = await client.post(
                        f"{self._base_url}/chat/completions", json=payload, headers=headers
                    )
                    if resp.status_code == 429:
                        # Quota-exhausted signal: retrying today is futile — stop the
                        # run rather than backing off forever.
                        if self._is_quota_exhausted(resp):
                            raise ProviderQuotaExhaustedError(
                                "Qiniu quota exhausted (free/daily quota used up); "
                                "stopping run until quota resets"
                            )
                        # Persistent throttle: keep backing off, but count it toward
                        # the cross-row circuit breaker. When the burst threshold is
                        # hit the upstream clearly won't recover on its own, so we
                        # abort the whole run instead of spinning row-by-row.
                        self._consecutive_429 += 1
                        call_429 += 1
                        if call_429 >= _MAX_429_PER_CALL or self._consecutive_429 >= _RATE_LIMIT_BURST:
                            raise ProviderRateLimitedError(
                                "Qiniu rate limited (429) persistently; aborting run"
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
                            raise ProviderRateLimitedError(
                                f"Qiniu returned {resp.status_code} persistently; aborting run"
                            )
                        last_exc = httpx.HTTPStatusError(
                            f"upstream returned {resp.status_code}",
                            request=resp.request,
                            response=resp,
                        )
                        await self._backoff(resp, transient_attempts)
                        continue
                    if resp.status_code == 403:
                        # 403 "access denied for invalid user" was observed as a
                        # transient, one-off event in request logs (the same model
                        # succeeds on adjacent calls). Retry it sparingly like a 5xx
                        # rather than failing the row instantly; a sustained 403
                        # (truly invalid key) will still exhaust _RETRY_COUNT fast.
                        transient_attempts += 1
                        if transient_attempts >= _RETRY_COUNT:
                            try:
                                detail = resp.json()
                            except Exception:  # noqa: BLE001
                                detail = resp.text
                            raise ProviderRateLimitedError(
                                f"Qiniu returned 403: {detail}"
                            )
                        last_exc = httpx.HTTPStatusError(
                            f"upstream returned 403",
                            request=resp.request,
                            response=resp,
                        )
                        await self._backoff(resp, transient_attempts)
                        continue
                    if resp.status_code >= 400:
                        # Client error other than 403/429 (e.g. 400/401/404): the
                        # request is bad or the key is invalid — retrying won't help,
                        # surface it immediately with the upstream detail.
                        try:
                            detail = resp.json()
                        except Exception:  # noqa: BLE001
                            detail = resp.text
                        raise ProviderRateLimitedError(
                            f"Qiniu returned {resp.status_code}: {detail}"
                        )
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

        # Robust parsing: tolerate missing usage / choices without crashing.
        choices = data.get("choices") or []
        if not choices:
            raise ProviderRateLimitedError(
                "Qiniu returned no choices in response"
            )
        first = choices[0] or {}
        message = first.get("message") or {}
        text = message.get("content") or ""
        usage = data.get("usage", {}) or {}
        return CompletionResult(
            text=text,
            prompt_tokens=int(usage.get("prompt_tokens", 0)),
            completion_tokens=int(usage.get("completion_tokens", 0)),
            latency_ms=latency_ms,
            raw={"provider": "qiniu", "id": data.get("id")},
        )

    @staticmethod
    def _is_quota_exhausted(resp: httpx.Response) -> bool:
        """Detect a quota-exhausted 429 (vs a transient throttle).

        Qiniu signals this via an error body whose `code`/`error.code` is one of
        _QUOTA_EXHAUSTED_CODES, or a message containing the free-quota marker. Best
        effort: if we cannot read the body, treat it as a normal throttle and let the
        retry/breaker logic handle it.
        """
        try:
            body = resp.json()
        except Exception:  # noqa: BLE001
            return False
        # Qiniu nests the code either at top-level `code` or under `error.code`.
        code = str(body.get("code") or (body.get("error") or {}).get("code") or "")
        if code in _QUOTA_EXHAUSTED_CODES:
            return True
        # Secondary, high-confidence message signal: only the precise free-quota
        # marker. A plain 429 whose message merely mentions "quota" must NOT be
        # misclassified as exhausted — that would abort a healthy run that just needs
        # to back off. We deliberately avoid fuzzy "quota" + "exhaust" substring
        # matching for that reason.
        message = str(body.get("message") or (body.get("error") or {}).get("message") or "")
        return "FreeQuotaExhausted" in message

    async def _backoff(self, resp: httpx.Response | None, attempt: int) -> None:
        if resp is not None:
            retry_after = resp.headers.get("Retry-After")
            if retry_after and retry_after.isdigit():
                await asyncio.sleep(int(retry_after))
                return
        # Exponential backoff: 0.5s, 1s, 2s, ... capped at _BACKOFF_MAX so a single
        # wait never grows unbounded.
        await asyncio.sleep(min(_BACKOFF_BASE * (2 ** attempt), _BACKOFF_MAX))
