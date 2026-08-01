"""Tests for row-level scoring diagnostics and historical score recomputation."""
from __future__ import annotations

import asyncio

import pytest

from app.core.database import AsyncSessionLocal
from app.evaluation.runner import run_experiment
from app.models.experiment import ExperimentResult
from app.models.model import Model
from app.providers.base import CompletionRequest, CompletionResult, LLMProvider
from app.repositories.experiment import ExperimentRepository


class _NoisyAnswerProvider(LLMProvider):
    name = "noisy"

    async def complete(self, request: CompletionRequest) -> CompletionResult:
        return CompletionResult(
            text="答案：亚洲",
            prompt_tokens=1,
            completion_tokens=1,
            latency_ms=5,
        )


@pytest.fixture()
def noisy_provider(monkeypatch):
    monkeypatch.setattr(
        "app.evaluation.runner.get_provider", lambda name=None: _NoisyAnswerProvider()
    )
    yield


def _create_short_answer_experiment(client, answer: str = "亚洲") -> str:
    assert client.post("/api/v1/models/seed").status_code in (200, 201)
    model_pk = client.get("/api/v1/models/").json()["items"][0]["id"]
    pid = client.post("/api/v1/projects/", json={"name": "diagnostics"}).json()["id"]
    benchmark = client.post(
        "/api/v1/benchmarks/",
        json={
            "project_id": pid,
            "name": "Short QA",
            "type": "qa",
            "metric": "exact_match_ci",
        },
    ).json()
    prompt = client.post(
        "/api/v1/prompts/",
        json={"project_id": pid, "name": "P", "template": "{question}"},
    ).json()
    jsonl = f'{{"question":"七大洲中面积最大的是？","answer":"{answer}"}}\n'.encode()
    dataset = client.post(
        "/api/v1/datasets/upload",
        data={"project_id": pid, "name": "DS", "format": "jsonl"},
        files={"file": ("d.jsonl", jsonl, "application/x-ndjson")},
    ).json()
    experiment = client.post(
        "/api/v1/experiments/",
        json={
            "project_id": pid,
            "name": "E",
            "dataset_id": dataset["id"],
            "benchmark_id": benchmark["id"],
            "prompt_id": prompt["id"],
            "model_id": model_pk,
        },
    ).json()
    return experiment["id"]


def test_results_include_score_diagnostics(client, noisy_provider):
    eid = _create_short_answer_experiment(client)
    asyncio.run(run_experiment(eid))

    results = client.get(f"/api/v1/experiments/{eid}/results").json()

    assert results[0]["score"] == 1.0
    assert results[0]["cleaned_prediction"] == "亚洲"
    assert results[0]["expected_canonical"] == "亚洲"
    assert "exact_match_ci" in results[0]["score_reason"]


def test_recompute_scores_reports_stored_vs_recomputed_differences(client):
    eid = _create_short_answer_experiment(client)

    async def _seed_legacy_bad_score():
        async with AsyncSessionLocal() as session:
            exp = await ExperimentRepository(session).get(eid)
            await ExperimentRepository(session).update(
                exp,
                {
                    "status": "completed",
                    "metrics": {
                        "metric": "exact_match_ci",
                        "accuracy": 0.0,
                        "rows_total": 1,
                        "rows_scored": 1,
                    },
                    "accuracy": 0.0,
                    "rows_total": 1,
                    "cells_done": 1,
                },
            )
            session.add(
                ExperimentResult(
                    experiment_id=eid,
                    row_idx=0,
                    input={"question": "七大洲中面积最大的是？"},
                    expected={"answer": "亚洲"},
                    output="答案：亚洲",
                    score=0.0,
                )
            )
            await session.commit()

    asyncio.run(_seed_legacy_bad_score())

    report = client.post(f"/api/v1/experiments/{eid}/recompute-scores").json()

    assert report["metric"] == "exact_match_ci"
    assert report["rows_total"] == 1
    assert report["stored_accuracy"] == 0.0
    assert report["recomputed_accuracy"] == 1.0
    assert report["changed_rows"] == 1
    assert report["differences"][0]["row_idx"] == 0
    assert report["differences"][0]["stored_score"] == 0.0
    assert report["differences"][0]["recomputed_score"] == 1.0
    assert report["differences"][0]["cleaned_prediction"] == "亚洲"
    assert report["differences"][0]["expected_canonical"] == "亚洲"


def test_recompute_scores_uses_scored_rows_for_accuracy(client):
    eid = _create_short_answer_experiment(client)

    async def _seed_partial_results():
        async with AsyncSessionLocal() as session:
            exp = await ExperimentRepository(session).get(eid)
            await ExperimentRepository(session).update(
                exp,
                {
                    "status": "partial",
                    "metrics": {
                        "metric": "exact_match_ci",
                        "accuracy": 1.0,
                        "rows_total": 2,
                        "rows_scored": 1,
                        "rows_failed": 1,
                    },
                    "accuracy": 1.0,
                    "rows_total": 2,
                    "cells_done": 1,
                    "cells_error": 1,
                },
            )
            session.add_all(
                [
                    ExperimentResult(
                        experiment_id=eid,
                        row_idx=0,
                        input={"question": "七大洲中面积最大的是？"},
                        expected={"answer": "亚洲"},
                        output="答案：亚洲",
                        score=1.0,
                    ),
                    ExperimentResult(
                        experiment_id=eid,
                        row_idx=1,
                        input={"question": "ignored"},
                        expected={"answer": "欧洲"},
                        output="",
                        score=0.0,
                        error="provider exploded",
                    ),
                ]
            )
            await session.commit()

    asyncio.run(_seed_partial_results())

    report = client.post(f"/api/v1/experiments/{eid}/recompute-scores").json()

    assert report["rows_total"] == 2
    assert report["rows_scored"] == 1
    assert report["rows_failed"] == 1
    assert report["coverage"] == pytest.approx(0.5)
    assert report["failure_rate"] == pytest.approx(0.5)
    assert report["stored_accuracy"] == 1.0
    assert report["recomputed_accuracy"] == 1.0
    assert report["changed_rows"] == 0


def test_recompute_scores_falls_back_to_current_model_for_legacy_experiment(client, monkeypatch):
    eid = _create_short_answer_experiment(client)
    captured: dict[str, str] = {}

    def recording_metric(prediction, expected, **kwargs):  # noqa: ANN001
        captured["model_id"] = kwargs["model_id"]
        captured["provider"] = kwargs["provider"]
        return 1.0

    monkeypatch.setattr(
        "app.services.experiment_service.get_metric",
        lambda name: recording_metric,
    )

    async def _clear_snapshot_and_read_model():
        async with AsyncSessionLocal() as session:
            exp = await ExperimentRepository(session).get(eid)
            model = await session.get(Model, exp.model_id)
            exp.model_snapshot = None
            session.add(
                ExperimentResult(
                    experiment_id=eid,
                    row_idx=0,
                    input={"question": "q"},
                    expected={"answer": "answer"},
                    output="answer",
                    score=0.0,
                )
            )
            await session.commit()
            return model.model_id, model.provider

    model_id, provider = asyncio.run(_clear_snapshot_and_read_model())
    client.post(f"/api/v1/experiments/{eid}/recompute-scores")

    assert captured == {"model_id": model_id, "provider": provider}
