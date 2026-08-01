"""BenchmarkSpec snapshots and minimal MetricSuite behavior."""
from __future__ import annotations

import asyncio
import time

import pytest

from app.providers.mock import MockProvider


@pytest.fixture(autouse=True)
def force_mock_provider(monkeypatch):
    monkeypatch.setattr(
        "app.evaluation.runner.get_provider", lambda name=None: MockProvider()
    )


def _create_project_model(client) -> tuple[str, str]:
    assert client.post("/api/v1/models/seed").status_code in (200, 201)
    model_id = client.get("/api/v1/models/").json()["items"][0]["id"]
    project_id = client.post("/api/v1/projects/", json={"name": "BenchmarkSpec"}).json()["id"]
    return project_id, model_id


def _create_dataset(client, project_id: str, *, answer: str = "4") -> str:
    jsonl = f'{{"question":"2+2?","answer":"{answer}"}}\n'.encode()
    return client.post(
        "/api/v1/datasets/upload",
        data={"project_id": project_id, "name": "DS", "format": "jsonl"},
        files={"file": ("d.jsonl", jsonl, "application/x-ndjson")},
    ).json()["id"]


def _create_prompt(client, project_id: str, template: str = "{question}") -> str:
    return client.post(
        "/api/v1/prompts/",
        json={"project_id": project_id, "name": "Prompt", "template": template},
    ).json()["id"]


def _create_experiment(
    client,
    *,
    project_id: str,
    dataset_id: str,
    benchmark_id: str,
    prompt_id: str,
    model_id: str,
    name: str = "Experiment",
) -> str:
    return client.post(
        "/api/v1/experiments/",
        json={
            "project_id": project_id,
            "name": name,
            "dataset_id": dataset_id,
            "benchmark_id": benchmark_id,
            "prompt_id": prompt_id,
            "model_id": model_id,
        },
    ).json()["id"]


def _get_experiment(experiment_id: str):
    async def _fetch():
        from app.core.database import AsyncSessionLocal
        from app.models.experiment import Experiment

        async with AsyncSessionLocal() as session:
            return await session.get(Experiment, experiment_id)

    return asyncio.run(_fetch())


def test_benchmark_snapshot_captures_type_name_version_and_spec(client):
    project_id, model_id = _create_project_model(client)
    dataset_id = _create_dataset(client, project_id)
    prompt_id = _create_prompt(client, project_id)
    benchmark = client.post(
        "/api/v1/benchmarks/",
        json={
            "project_id": project_id,
            "name": "Spec QA",
            "type": "qa",
            "metric": "exact_match_ci",
            "metric_config": {
                "version": 7,
                "metric_suite": [
                    {"name": "exact_match_ci", "weight": 1.0, "config": {}}
                ],
            },
        },
    ).json()

    experiment_id = _create_experiment(
        client,
        project_id=project_id,
        dataset_id=dataset_id,
        benchmark_id=benchmark["id"],
        prompt_id=prompt_id,
        model_id=model_id,
    )

    snapshot = _get_experiment(experiment_id).benchmark_snapshot
    assert snapshot["type"] == "qa"
    assert snapshot["name"] == "Spec QA"
    assert snapshot["version"] == 7
    assert snapshot["spec"]["version"] == 7
    assert snapshot["spec"]["task_type"] == "qa"
    assert snapshot["spec"]["metric_suite"] == [
        {"name": "exact_match_ci", "weight": 1.0, "config": {}}
    ]


def test_duplicate_experiment_preserves_original_benchmark_snapshot(client):
    project_id, model_id = _create_project_model(client)
    dataset_id = _create_dataset(client, project_id)
    prompt_id = _create_prompt(client, project_id)
    benchmark = client.post(
        "/api/v1/benchmarks/",
        json={
            "project_id": project_id,
            "name": "Original QA",
            "type": "qa",
            "metric": "exact_match",
            "metric_config": {"version": 1},
        },
    ).json()
    experiment_id = _create_experiment(
        client,
        project_id=project_id,
        dataset_id=dataset_id,
        benchmark_id=benchmark["id"],
        prompt_id=prompt_id,
        model_id=model_id,
    )

    client.patch(
        f"/api/v1/benchmarks/{benchmark['id']}",
        json={
            "name": "Live QA",
            "metric": "contains",
            "metric_config": {"version": 2},
        },
    )
    duplicate = client.post(
        f"/api/v1/experiments/{experiment_id}/duplicate",
        json={"name": "Copy"},
    ).json()

    source_snapshot = _get_experiment(experiment_id).benchmark_snapshot
    clone_snapshot = _get_experiment(duplicate["id"]).benchmark_snapshot
    assert clone_snapshot == source_snapshot
    assert clone_snapshot["name"] == "Original QA"
    assert clone_snapshot["metric"] == "exact_match"
    assert clone_snapshot["version"] == 1


def test_model_snapshot_preserves_provider_for_reproducible_routing(client):
    project_id = client.post("/api/v1/projects/", json={"name": "ProviderSnapshot"}).json()["id"]
    model = client.post(
        "/api/v1/models/",
        json={
            "name": "OpenRouter model",
            "provider": "openrouter",
            "model_id": "openai/gpt-4o-mini",
            "pricing": {},
        },
    ).json()
    dataset_id = _create_dataset(client, project_id)
    prompt_id = _create_prompt(client, project_id)
    benchmark = client.post(
        "/api/v1/benchmarks/",
        json={"project_id": project_id, "name": "QA", "type": "qa"},
    ).json()

    experiment_id = _create_experiment(
        client,
        project_id=project_id,
        dataset_id=dataset_id,
        benchmark_id=benchmark["id"],
        prompt_id=prompt_id,
        model_id=model["id"],
    )

    snapshot = _get_experiment(experiment_id).model_snapshot
    assert snapshot["provider"] == "openrouter"


def test_dataset_answer_policy_is_snapshotted_for_reproducible_scoring(client):
    project_id, model_id = _create_project_model(client)
    dataset = client.post(
        "/api/v1/datasets/upload",
        data={
            "project_id": project_id,
            "name": "Policy DS",
            "format": "jsonl",
            "answer_policy": '{"aliases": ["Beijing"], "multi_answer": "all"}',
        },
        files={"file": ("d.jsonl", b'{"question":"capital?","answer":"Beijing"}\n', "application/x-ndjson")},
    ).json()
    prompt_id = _create_prompt(client, project_id, "{question}")
    benchmark_id = client.post(
        "/api/v1/benchmarks/",
        json={"project_id": project_id, "name": "Policy QA", "type": "qa"},
    ).json()["id"]
    experiment_id = _create_experiment(
        client,
        project_id=project_id,
        dataset_id=dataset["id"],
        benchmark_id=benchmark_id,
        prompt_id=prompt_id,
        model_id=model_id,
    )

    snapshot = _get_experiment(experiment_id).dataset_snapshot
    assert snapshot["answer_policy"] == {"aliases": ["Beijing"], "multi_answer": "all"}


def test_experiment_rejects_components_from_another_project(client):
    project_a, model_id = _create_project_model(client)
    project_b = client.post("/api/v1/projects/", json={"name": "OtherProject"}).json()["id"]
    dataset_id = _create_dataset(client, project_a)
    prompt_id = _create_prompt(client, project_a)
    benchmark = client.post(
        "/api/v1/benchmarks/",
        json={"project_id": project_a, "name": "QA", "type": "qa"},
    ).json()

    response = client.post(
        "/api/v1/experiments/",
        json={
            "project_id": project_b,
            "name": "Cross-project",
            "dataset_id": dataset_id,
            "benchmark_id": benchmark["id"],
            "prompt_id": prompt_id,
            "model_id": model_id,
        },
    )
    assert response.status_code == 422


def test_metric_suite_runs_multiple_metrics_and_persists_weighted_primary_score(client):
    project_id, model_id = _create_project_model(client)
    dataset_id = _create_dataset(client, project_id, answer="Paris France")
    prompt_id = _create_prompt(client, project_id, "What is the capital of France?")
    benchmark = client.post(
        "/api/v1/benchmarks/",
        json={
            "project_id": project_id,
            "name": "Suite QA",
            "type": "qa",
            "metric": "exact_match",
            "metric_config": {
                "version": 3,
                "metric_suite": [
                    {"name": "exact_match", "weight": 0.25, "config": {}},
                    {"name": "f1_token", "weight": 0.75, "config": {}},
                ],
            },
        },
    ).json()
    experiment_id = _create_experiment(
        client,
        project_id=project_id,
        dataset_id=dataset_id,
        benchmark_id=benchmark["id"],
        prompt_id=prompt_id,
        model_id=model_id,
    )

    client.post(f"/api/v1/experiments/{experiment_id}/run")
    final = None
    for _ in range(50):
        time.sleep(0.1)
        final = client.get(f"/api/v1/experiments/{experiment_id}").json()
        if final["status"] in ("completed", "failed"):
            break

    assert final is not None and final["status"] == "completed", final
    metrics = final["metrics"]
    assert metrics["metric"] == "metric_suite"
    assert metrics["metrics_by_name"]["exact_match"] == 0.0
    assert metrics["metrics_by_name"]["f1_token"] == pytest.approx(2 / 3)
    assert metrics["primary_score"] == pytest.approx(0.5)
    assert metrics["accuracy"] == pytest.approx(metrics["primary_score"])

    report = client.post(f"/api/v1/experiments/{experiment_id}/recompute-scores").json()
    assert report["metric"] == "metric_suite"
    assert report["recomputed_accuracy"] == pytest.approx(metrics["primary_score"])
