"""Regression tests for keyword search on list endpoints."""
from __future__ import annotations


def test_datasets_search_filters_by_name_and_total(client):
    pid = client.post("/api/v1/projects/", json={"name": "SearchProj"}).json()["id"]
    for name in ("Alpha DS", "Beta DS"):
        client.post(
            "/api/v1/datasets/upload",
            data={"project_id": pid, "name": name, "format": "jsonl"},
            files={
                "file": ("d.jsonl", b'{"question":"q","answer":"a"}\n', "application/x-ndjson")
            },
        )

    r = client.get("/api/v1/datasets/", params={"project_id": pid, "q": "alpha"})
    body = r.json()
    assert len(body["items"]) == 1
    assert body["items"][0]["name"] == "Alpha DS"
    assert body["total"] == 1

    r_all = client.get("/api/v1/datasets/", params={"project_id": pid})
    assert r_all.json()["total"] == 2


def test_experiments_search_filters_by_name(client):
    assert client.post("/api/v1/models/seed").status_code in (200, 201)
    model_pk = client.get("/api/v1/models/").json()["items"][0]["id"]
    pid = client.post("/api/v1/projects/", json={"name": "SearchExp"}).json()["id"]
    b = client.post(
        "/api/v1/benchmarks/",
        json={"project_id": pid, "name": "QA", "type": "qa", "metric": "exact_match_ci"},
    ).json()
    pr = client.post(
        "/api/v1/prompts/",
        json={"project_id": pid, "name": "P", "template": "{question}"},
    ).json()
    ds = client.post(
        "/api/v1/datasets/upload",
        data={"project_id": pid, "name": "DS", "format": "jsonl"},
        files={"file": ("d.jsonl", b'{"question":"q","answer":"a"}\n', "application/x-ndjson")},
    ).json()

    for name in ("Run Alpha", "Run Beta"):
        client.post(
            "/api/v1/experiments/",
            json={
                "project_id": pid,
                "name": name,
                "dataset_id": ds["id"],
                "benchmark_id": b["id"],
                "prompt_id": pr["id"],
                "model_id": model_pk,
            },
        )

    r = client.get("/api/v1/experiments/", params={"project_id": pid, "q": "alpha"})
    body = r.json()
    assert len(body["items"]) == 1
    assert body["items"][0]["name"] == "Run Alpha"
