"""Regression test: generation predictions must not be truncated at the first comma.

The answer extractor is QA-oriented: for short exact-match answers it keeps only
the first comma-separated segment (e.g. "答案：40平方米，13厘米" -> "40平方米").
That behavior is wrong for generation metrics like f1_token: a summary such as
"城市发布人才引进政策，最高200万安家补贴。" would be reduced to its first clause,
deflating the F1 score even when the model's summary is correct.
"""
from __future__ import annotations

import asyncio

from app.core.database import AsyncSessionLocal
from app.evaluation.runner import run_experiment
from app.providers.base import CompletionRequest, CompletionResult, LLMProvider
from app.repositories.experiment import ExperimentRepository, ExperimentResultRepository


class _SummaryProvider(LLMProvider):
    """Deterministic fake provider returning a full multi-clause summary."""

    name = "summary"

    async def complete(self, request: CompletionRequest) -> CompletionResult:
        return CompletionResult(
            text="城市发布人才引进政策，最高200万安家补贴。",
            prompt_tokens=10,
            completion_tokens=20,
            latency_ms=5,
        )


def _build_generation_experiment(client):
    assert client.post("/api/v1/models/seed").status_code in (200, 201)
    models = client.get("/api/v1/models/").json()["items"]
    model_pk = models[0]["id"]
    pid = client.post("/api/v1/projects/", json={"name": "GEN"}).json()["id"]
    b = client.post(
        "/api/v1/benchmarks/",
        json={"project_id": pid, "name": "摘要", "type": "generation", "metric": "f1_token"},
    ).json()
    pr = client.post(
        "/api/v1/prompts/",
        json={"project_id": pid, "name": "P", "template": "文章：{article}"},
    ).json()
    jsonl = (
        '{"article": "城市发布人才引进政策，最高200万安家补贴。", '
        '"answer": "城市发布人才引进政策，最高200万安家补贴。"}\n'
    ).encode("utf-8")
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
            "model_id": model_pk,
        },
    ).json()
    return exp["id"]


def test_generation_prediction_keeps_full_text(client, monkeypatch):
    monkeypatch.setattr(
        "app.evaluation.runner.get_provider", lambda name=None: _SummaryProvider()
    )
    eid = _build_generation_experiment(client)
    asyncio.run(run_experiment(eid))

    async def _inspect():
        async with AsyncSessionLocal() as session:
            exp = await ExperimentRepository(session).get(eid)
            results = await ExperimentResultRepository(session).list_by_experiment(
                eid, limit=10_000
            )
            return exp, results

    exp, results = asyncio.run(_inspect())
    assert exp is not None
    assert exp.status == "completed", exp.error
    assert len(results) == 1
    row = results[0]
    # The full summary survives extraction: no truncation at the first comma.
    assert row.cleaned_prediction == "城市发布人才引进政策，最高200万安家补贴"
    # Identical summary -> token F1 of 1.0.
    assert row.score == 1.0
