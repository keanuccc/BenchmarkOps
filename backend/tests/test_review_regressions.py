"""Regression tests for adversarial-review findings.

Covers two gaps called out during review:
  * schemas._sanitize_error must pass through operational keywords (database is
    locked / rate limited) so the UI stays diagnostic, while still redacting SQL
    and filesystem paths (review 4.3).
  * OpenRouterProvider aborts a single row on 429 once _MAX_429_PER_CALL is hit,
    even under an alternating 429/200 pattern where the cross-row breaker never
    trips (review 2.2).
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import httpx
import pytest

import app.providers.openrouter as openrouter_mod
from app.providers.base import (
    CompletionRequest,
    ProviderRateLimitedError,
)
from app.providers.openrouter import OpenRouterProvider
from app.schemas.experiment import ExperimentRead


def _resp(status: int) -> httpx.Response:
    return httpx.Response(status, request=httpx.Request("POST", "http://x"))


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
    def __init__(self, responses: list[httpx.Response]):
        self._responses = list(responses)
        self.post = AsyncMock(side_effect=self._responses)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


@pytest.mark.parametrize(
    "raw,expected_keyword",
    [
        ("(sqlite3.OperationalError) database is locked", "database is locked"),
        ("OpenRouter rate limited (429) persistently; aborting run", "rate limited"),
        (
            "app.providers.base.ProviderRateLimitedError: OpenRouter rate limited",
            "ProviderRateLimitedError",
        ),
    ],
)
def test_sanitize_error_passes_through_keywords(raw, expected_keyword):
    """Operational keywords reach the client so the UI can tell the user what broke."""
    cleaned = ExperimentRead.model_validate(
        {
            "id": "x" * 32,
            "project_id": "p",
            "name": "n",
            "dataset_id": "d",
            "benchmark_id": "b",
            "prompt_id": "pr",
            "model_id": "m",
            "params": {},
            "status": "failed",
            "metrics": {},
            "total_cost": 0.0,
            "total_tokens": 0,
            "runtime_ms": 0,
            "progress": 0,
            "rows_total": None,
            "cells_done": 0,
            "cells_error": 0,
            "accuracy": 0.0,
            "avg_latency_ms": 0.0,
            "error": raw,
            "created_at": "2026-07-20T00:00:00",
            "updated_at": "2026-07-20T00:00:00",
        }
    ).error
    assert expected_keyword in (cleaned or "")


def test_sanitize_error_redacts_sql_and_paths():
    """Even an allowed-keyword error must not leak raw SQL or filesystem paths."""
    cleaned = ExperimentRead.model_validate(
        {
            "id": "x" * 32,
            "project_id": "p",
            "name": "n",
            "dataset_id": "d",
            "benchmark_id": "b",
            "prompt_id": "pr",
            "model_id": "m",
            "params": {},
            "status": "failed",
            "metrics": {},
            "total_cost": 0.0,
            "total_tokens": 0,
            "runtime_ms": 0,
            "progress": 0,
            "rows_total": None,
            "cells_done": 0,
            "cells_error": 0,
            "accuracy": 0.0,
            "avg_latency_ms": 0.0,
            "error": "database is locked; SELECT * FROM users WHERE password='/etc/passwd'",
            "created_at": "2026-07-20T00:00:00",
            "updated_at": "2026-07-20T00:00:00",
        }
    ).error
    assert "SELECT" not in (cleaned or "")
    assert "/etc/passwd" not in (cleaned or "")
    assert "database is locked" in (cleaned or "")


async def test_single_row_429_capped_even_when_alternating(monkeypatch):
    """A single row must abort on 429 once _MAX_429_PER_CALL is hit, independent of
    the cross-row breaker. We isolate the per-call cap by raising the cross-row
    burst threshold above it, then feed exactly _MAX_429_PER_CALL consecutive 429s
    (no 200 in between, since a 200 would reset and return)."""
    max_per_call = openrouter_mod._MAX_429_PER_CALL
    # Isolate the per-call cap branch: make the cross-row breaker arm higher.
    monkeypatch.setattr(openrouter_mod, "_RATE_LIMIT_BURST", max_per_call + 5)

    sleeps: list[float] = []
    real_sleep = asyncio.sleep

    async def spy_sleep(d):
        sleeps.append(d)
        return await real_sleep(0)

    monkeypatch.setattr(asyncio, "sleep", spy_sleep)

    responses = [_resp(429) for _ in range(max_per_call)]
    fake = _FakeClient(responses)
    monkeypatch.setattr(openrouter_mod.httpx, "AsyncClient", lambda **kw: fake)
    provider = OpenRouterProvider()
    provider._api_key = "x"
    provider._base_url = "http://x"
    provider._timeout = 1.0

    with pytest.raises(ProviderRateLimitedError):
        await provider.complete(CompletionRequest(model_id="m", messages=[]))
    assert all(s <= openrouter_mod._BACKOFF_MAX for s in sleeps)
