"""End-to-end smoke test: full workflow chain + one evaluation run with Mock provider."""
from __future__ import annotations

import time

import pytest

from app.providers.mock import MockProvider


@pytest.fixture(autouse=True)
def force_mock_provider(monkeypatch):
    """Keep this an offline smoke test: never hit the real OpenRouter API."""
    monkeypatch.setattr(
        "app.evaluation.runner.get_provider", lambda name=None: MockProvider()
    )


def test_health(client):
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_full_evaluation_chain(client):
    # Seed models
    assert client.post("/api/v1/models/seed").status_code in (200, 201)
    models = client.get("/api/v1/models/").json()
    assert models, "expected seeded models"
    model_pk = models[0]["id"]

    # Project
    pid = client.post("/api/v1/projects/", json={"name": "T"}).json()["id"]

    # Benchmark (auto default metric) + Prompt (auto var extraction)
    b = client.post(
        "/api/v1/benchmarks/",
        json={"project_id": pid, "name": "QA", "type": "qa", "metric": "exact_match_ci"},
    ).json()
    pr = client.post(
        "/api/v1/prompts/",
        json={"project_id": pid, "name": "P", "template": "{question}"},
    ).json()
    assert pr["variables"] == ["question"]

    # Dataset upload (JSONL)
    jsonl = b'{"question":"2+2?","answer":"4"}\n{"question":"3*3?","answer":"9"}\n'
    ds = client.post(
        "/api/v1/datasets/upload",
        data={"project_id": pid, "name": "DS", "format": "jsonl"},
        files={"file": ("d.jsonl", jsonl, "application/x-ndjson")},
    ).json()
    assert ds["row_count"] == 2

    # Experiment + run
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
    assert final["metrics"]["accuracy"] == 1.0  # mock solves arithmetic

    results = client.get(f"/api/v1/experiments/{eid}/results").json()
    assert len(results) == 2
    assert all(r["score"] == 1.0 for r in results)


def test_experiment_rejects_missing_component(client):
    pid = client.post("/api/v1/projects/", json={"name": "T2"}).json()["id"]
    r = client.post(
        "/api/v1/experiments/",
        json={
            "project_id": pid,
            "name": "bad",
            "dataset_id": "nope",
            "benchmark_id": "nope",
            "prompt_id": "nope",
            "model_id": "nope",
        },
    )
    assert r.status_code == 422


def test_upload_rejects_oversized_file(client):
    """A payload above max_upload_bytes must be rejected (422 + error envelope)."""
    from app.core.config import settings

    pid = client.post("/api/v1/projects/", json={"name": "T3"}).json()["id"]
    # One byte over the limit, as a single JSONL line repeated to exceed the cap.
    oversized = b'{"question":"x","answer":"y"}\n' * (
        (settings.max_upload_bytes // 30) + 2
    )
    r = client.post(
        "/api/v1/datasets/upload",
        data={"project_id": pid, "name": "BIG", "format": "jsonl"},
        files={"file": ("big.jsonl", oversized, "application/x-ndjson")},
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "validation_error"
    assert "exceeds limit" in r.json()["error"]["message"]


def test_upload_rejects_too_many_rows(client):
    """A valid file whose row count exceeds max_dataset_rows must be rejected."""
    from app.core.config import settings

    pid = client.post("/api/v1/projects/", json={"name": "T4"}).json()["id"]
    line = '{"question":"x","answer":"y"}\n'
    rows = (settings.max_dataset_rows + 1) * line
    r = client.post(
        "/api/v1/datasets/upload",
        data={"project_id": pid, "name": "MANY", "format": "jsonl"},
        files={"file": ("many.jsonl", rows, "application/x-ndjson")},
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "validation_error"
    assert "rows exceeds limit" in r.json()["error"]["message"]

