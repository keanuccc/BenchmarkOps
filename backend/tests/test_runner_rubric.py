"""End-to-end runner test for the dimension-based rubric judge metric."""
from __future__ import annotations

import asyncio
import json

import pytest

from app.core.database import AsyncSessionLocal
from app.evaluation.runner import run_experiment
from app.providers.base import CompletionRequest, CompletionResult, LLMProvider
from app.repositories.experiment import ExperimentRepository, ExperimentResultRepository


class _RubricProvider(LLMProvider):
    """Deterministic fake judge: correctness 5/5, completeness 3/5."""

    name = "rubric"

    async def complete(self, request: CompletionRequest) -> CompletionResult:
        return CompletionResult(
            text=json.dumps({"scores": {"correctness": 5, "completeness": 3}}),
            prompt_tokens=100,
            completion_tokens=20,
            latency_ms=5,
        )


def test_runner_stores_fractional_rubric_score(client, monkeypatch):
    monkeypatch.setattr(
        "app.evaluation.runner.get_provider", lambda name=None: _RubricProvider()
    )
    # Judge metrics resolve providers via the registry at call time, so both
    # the runner's reference and the registry must point at the fake provider.
    monkeypatch.setattr(
        "app.providers.registry.get_provider", lambda name=None: _RubricProvider()
    )
    assert client.post("/api/v1/models/seed").status_code in (200, 201)
    models = client.get("/api/v1/models/").json()["items"]
    model_pk = models[0]["id"]
    pid = client.post("/api/v1/projects/", json={"name": "RUBRIC"}).json()["id"]
    b = client.post(
        "/api/v1/benchmarks/",
        json={
            "project_id": pid,
            "name": "摘要rubric",
            "type": "generation",
            "metric": "llm_judge_rubric",
            "metric_config": {
                "dimensions": [
                    {"name": "correctness", "weight": 1},
                    {"name": "completeness", "weight": 1},
                ],
                "scale": 5,
            },
        },
    ).json()
    pr = client.post(
        "/api/v1/prompts/",
        json={"project_id": pid, "name": "P", "template": "文章：{article}"},
    ).json()
    jsonl = (
        '{"article": "城市发布人才引进政策。", '
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

    asyncio.run(run_experiment(exp["id"]))

    async def _inspect():
        async with AsyncSessionLocal() as session:
            experiment = await ExperimentRepository(session).get(exp["id"])
            results = await ExperimentResultRepository(session).list_by_experiment(
                exp["id"], limit=10_000
            )
            return experiment, results

    experiment, results = asyncio.run(_inspect())
    assert experiment is not None
    assert experiment.status == "completed", experiment.error
    assert len(results) == 1
    # (5/5 + 3/5) / 2 = 0.8 — a fractional score, not a binary 0/1.
    assert results[0].score == pytest.approx(0.8)
