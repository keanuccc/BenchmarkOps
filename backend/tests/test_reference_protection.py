"""Regression tests for delete reference protection + project cascade."""
from __future__ import annotations

import json


def _build_components(client):
    """Create a project with model/dataset/benchmark/prompt/experiment."""
    assert client.post("/api/v1/models/seed").status_code in (200, 201)
    models = client.get("/api/v1/models/").json()["items"]
    model_pk = models[0]["id"]

    pid = client.post("/api/v1/projects/", json={"name": "RefGuard"}).json()["id"]

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
    ds = client.post(
        "/api/v1/datasets/upload",
        data={"project_id": pid, "name": "DS", "format": "jsonl"},
        files={"file": ("d.jsonl", b'{"question":"2+2?","answer":"4"}\n', "application/x-ndjson")},
    ).json()

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
    return {
        "project_id": pid,
        "model_id": model_pk,
        "dataset_id": ds["id"],
        "benchmark_id": b["id"],
        "prompt_id": pr["id"],
        "experiment_id": exp["id"],
    }


def test_referenced_model_cannot_be_deleted(client):
    c = _build_components(client)
    r = client.delete(f"/api/v1/models/{c['model_id']}")
    assert r.status_code == 409
    assert "referenced" in r.json()["error"]["message"]
    assert "Model '" in r.json()["error"]["message"]


def test_bulk_delete_referenced_model_reports_name(client):
    c = _build_components(client)
    r = client.request("DELETE", "/api/v1/models/bulk", json={"ids": [c["model_id"]]})
    assert r.status_code == 409
    assert "Model '" in r.json()["error"]["message"]


def test_referenced_dataset_cannot_be_deleted(client):
    c = _build_components(client)
    r = client.delete(f"/api/v1/datasets/{c['dataset_id']}")
    assert r.status_code == 409


def test_referenced_benchmark_cannot_be_deleted(client):
    c = _build_components(client)
    r = client.delete(f"/api/v1/benchmarks/{c['benchmark_id']}")
    assert r.status_code == 409


def test_referenced_prompt_cannot_be_deleted(client):
    c = _build_components(client)
    r = client.delete(f"/api/v1/prompts/{c['prompt_id']}")
    assert r.status_code == 409


def test_bulk_delete_rejects_referenced_models(client):
    c = _build_components(client)
    r = client.request(
        "DELETE",
        "/api/v1/models/bulk",
        content=json.dumps({"ids": [c["model_id"]]}),
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code == 409


def test_unreferenced_model_can_be_deleted(client):
    # Seeding is idempotent now, so create a dedicated unreferenced model
    # instead of assuming a seeded model has no experiment references.
    created = client.post(
        "/api/v1/models/",
        json={
            "name": "Unreferenced probe",
            "provider": "openai",
            "model_id": "openai/unreferenced-probe",
        },
    )
    assert created.status_code in (200, 201)
    other = created.json()["id"]
    r = client.delete(f"/api/v1/models/{other}")
    assert r.status_code == 204


def test_project_delete_cascades_to_children(client):
    c = _build_components(client)
    pid = c["project_id"]
    r = client.delete(f"/api/v1/projects/{pid}")
    assert r.status_code == 204

    assert client.get(f"/api/v1/projects/{pid}").status_code == 404
    assert client.get("/api/v1/datasets/", params={"project_id": pid}).json()["items"] == []
    assert client.get("/api/v1/benchmarks/", params={"project_id": pid}).json()["items"] == []
    assert client.get("/api/v1/prompts/", params={"project_id": pid}).json()["items"] == []
    assert client.get("/api/v1/experiments/", params={"project_id": pid}).json()["items"] == []

    # Models are global and survive a project delete.
    assert client.get(f"/api/v1/models/{c['model_id']}").status_code == 200
