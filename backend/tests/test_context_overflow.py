"""Tests for the runner's context-window pre-check."""
from __future__ import annotations

import asyncio

import pytest

from app.core.database import AsyncSessionLocal
from app.evaluation.runner import _estimate_tokens, run_experiment
from app.providers.base import CompletionRequest, CompletionResult, LLMProvider
from app.repositories.experiment import (
    ExperimentRepository,
    ExperimentResultRepository,
)


class _OkProvider(LLMProvider):
    name = "ok"

    async def complete(self, request: CompletionRequest) -> CompletionResult:
        return CompletionResult(
            text="a", prompt_tokens=1, completion_tokens=1, latency_ms=1
        )


@pytest.fixture()
def patched_ok(monkeypatch):
    monkeypatch.setattr(
        "app.evaluation.runner.get_provider", lambda name=None: _OkProvider()
    )
    yield


def test_estimate_tokens():
    # CJK ~1 token per char; other scripts ~1 token per 4 chars (rounded up).
    assert _estimate_tokens("你好世界") == 4
    assert _estimate_tokens("hello world") == 3  # 11 chars -> ceil(11/4)
    assert _estimate_tokens("") == 0


def test_context_overflow_fails_row(client, patched_ok):
    """A row whose rendered prompt exceeds the model's context window must fail
    fast with a clear diagnostic instead of hitting the upstream 400."""
    model = client.post(
        "/api/v1/models/",
        json={
            "name": "tiny",
            "provider": "mock",
            "model_id": "tiny-ctx",
            "context_length": 8,
            "is_active": True,
        },
    ).json()
    pid = client.post("/api/v1/projects/", json={"name": "Ctx"}).json()["id"]
    b = client.post(
        "/api/v1/benchmarks/",
        json={
            "project_id": pid,
            "name": "QA",
            "type": "qa",
            "metric": "exact_match_ci",
        },
    ).json()
    pr = client.post(
        "/api/v1/prompts/",
        json={"project_id": pid, "name": "P", "template": "{question}"},
    ).json()
    jsonl = (
        b'{"question":"this is a very long english question that definitely '
        b'exceeds eight tokens","answer":"a"}\n'
    )
    ds = client.post(
        "/api/v1/datasets/upload",
        data={"project_id": pid, "name": "DS", "format": "jsonl"},
        files={"file": ("d.jsonl", jsonl, "application/x-ndjson")},
    ).json()
    exp = client.post(
        "/api/v1/experiments/",
        json={
            "project_id": pid,
            "name": "E",
            "dataset_id": ds["id"],
            "benchmark_id": b["id"],
            "prompt_id": pr["id"],
            "model_id": model["id"],
        },
    ).json()

    asyncio.run(run_experiment(exp["id"]))

    async def _inspect():
        async with AsyncSessionLocal() as session:
            e = await ExperimentRepository(session).get(exp["id"])
            results = await ExperimentResultRepository(session).list_by_experiment(
                exp["id"], limit=10
            )
            return e, results

    e, results = asyncio.run(_inspect())
    assert e.status == "partial", e.error
    assert len(results) == 1
    assert "context_overflow" in (results[0].error or "")
    assert e.cells_error == 1
