"""Tests for one-click batch experiment creation."""
from __future__ import annotations


def _seed_components(client) -> dict:
    assert client.post("/api/v1/models/seed").status_code in (200, 201)
    models = client.get("/api/v1/models/").json()["items"]
    model_ids = [models[0]["id"], models[1]["id"]]
    project_id = client.post("/api/v1/projects/", json={"name": "batch"}).json()["id"]
    benchmark = client.post(
        "/api/v1/benchmarks/",
        json={
            "project_id": project_id,
            "name": "QA",
            "type": "qa",
            "metric": "exact_match_ci",
        },
    ).json()
    prompt = client.post(
        "/api/v1/prompts/",
        json={"project_id": project_id, "name": "P", "template": "{question}"},
    ).json()
    dataset = client.post(
        "/api/v1/datasets/upload",
        data={"project_id": project_id, "name": "DS", "format": "jsonl"},
        files={
            "file": (
                "d.jsonl",
                b'{"question":"2+2=?","answer":"4"}\n',
                "application/x-ndjson",
            )
        },
    ).json()
    return {
        "project_id": project_id,
        "model_ids": model_ids,
        "benchmark_id": benchmark["id"],
        "prompt_id": prompt["id"],
        "dataset_id": dataset["id"],
    }


def test_batch_creates_one_experiment_per_model(client):
    c = _seed_components(client)
    response = client.post(
        "/api/v1/experiments/batch",
        json={
            "project_id": c["project_id"],
            "name": "A/B batch",
            "dataset_id": c["dataset_id"],
            "benchmark_id": c["benchmark_id"],
            "prompt_id": c["prompt_id"],
            "model_ids": c["model_ids"],
        },
    )
    assert response.status_code == 201
    experiments = response.json()
    assert len(experiments) == 2
    assert {e["model_id"] for e in experiments} == set(c["model_ids"])
    assert {e["name"] for e in experiments} == {"A/B batch"}
    assert all(e["dataset_version"] == 1 for e in experiments)
