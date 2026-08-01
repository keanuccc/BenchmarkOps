# Golden E2E: answer-prefix noise from the provider does not break scoring.
from __future__ import annotations

import time

import pytest

from app.providers.base import CompletionRequest, CompletionResult, LLMProvider
from app.providers.mock import MockProvider


class PrefixNoiseMockProvider(LLMProvider):
    """A MockProvider that wraps every completion with '答案：' prefix."""

    name = "mock"

    async def complete(self, request: CompletionRequest) -> CompletionResult:
        base = MockProvider()
        result = await base.complete(request)
        return CompletionResult(
            text=f"答案：{result.text}",
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
            latency_ms=result.latency_ms,
            raw=result.raw,
        )


@pytest.fixture(autouse=True)
def force_prefix_noise_provider(monkeypatch):
    """Keep this an offline smoke test: never hit the real API."""
    monkeypatch.setattr(
        "app.evaluation.runner.get_provider", lambda name=None: PrefixNoiseMockProvider()
    )


def test_prefix_noise_does_not_break_scoring(client):
    """Even when the mock prepends prefix, the runner must still score 1.0."""
    assert client.post("/api/v1/models/seed").status_code in (200, 201)
    models = client.get("/api/v1/models/").json()["items"]
    assert models
    model_pk = models[0]["id"]

    pid = client.post("/api/v1/projects/", json={"name": "PrefixNoise"}).json()["id"]

    b = client.post(
        "/api/v1/benchmarks/",
        json={"project_id": pid, "name": "QA", "type": "qa", "metric": "exact_match_ci"},
    ).json()
    pr = client.post(
        "/api/v1/prompts/",
        json={"project_id": pid, "name": "P", "template": "{question}"},
    ).json()
    assert pr["variables"] == ["question"]

    jsonl = b'{"question":"2+2?","answer":"4"}\n{"question":"3*3?","answer":"9"}\n'
    ds = client.post(
        "/api/v1/datasets/upload",
        data={"project_id": pid, "name": "DS", "format": "jsonl"},
        files={"file": ("d.jsonl", jsonl, "application/x-ndjson")},
    ).json()
    assert ds["row_count"] == 2

    exp = client.post(
        "/api/v1/experiments/",
        json={
            "project_id": pid,
            "name": "E1",
            "dataset_id": ds["id"],
            "benchmark_id": b["id"],
            "prompt_id": pr["id"],
            "model_id": model_pk,
        },
    ).json()
    eid = exp["id"]
    assert exp["status"] == "pending"

    client.post(f"/api/v1/experiments/{eid}/run")

    final = None
    for _ in range(50):
        time.sleep(0.1)
        final = client.get(f"/api/v1/experiments/{eid}").json()
        if final["status"] in ("completed", "failed"):
            break
    assert final is not None and final["status"] == "completed", final
    assert final["metrics"]["rows_total"] == 2
    assert final["metrics"]["accuracy"] == 1.0, (
        f"Expected accuracy 1.0 but got {final['metrics']['accuracy']}"
    )

    results = client.get(f"/api/v1/experiments/{eid}/results").json()
    assert len(results) == 2
    assert all(r["score"] == 1.0 for r in results), f"Some rows scored below 1.0: {results}"
