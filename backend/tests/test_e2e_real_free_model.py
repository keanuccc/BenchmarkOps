"""End-to-end E2E suite exercising every module, using a REAL free OpenRouter model.

Targets `tencent/hy3:free` (no paid quota consumed). The suite builds a
throwaway project through the real API surface, runs one evaluation on the free
model, then verifies compare / analytics / report.

This test hits the network (OpenRouter) and consumes the daily *free* quota, so
it is marked `e2e` + `network` and skipped automatically when no API key is
configured (Mock provider). Run it explicitly with:

    uv run pytest tests/test_e2e_real_free_model.py -m e2e

Design notes:
- Uses the session `client` fixture from conftest (temp SQLite DB), so it never
  touches the dev database.
- Arithmetic dataset: hy3 returns the correct number, so exact_match scores 1.0.
- A single run is issued to keep free-quota usage minimal.
"""
from __future__ import annotations

import json
import time

import pytest

from app.core.config import settings

FREE_MODEL = "tencent/hy3:free"
FREE_MODEL_NAME = "Tencent HY3 (free)"

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.network,
    pytest.mark.skipif(
        not settings.provider_enabled,
        reason="OPENROUTER_API_KEY not set — Mock provider has no free-model path; "
        "skipping the real-free-model E2E suite.",
    ),
]


@pytest.fixture()
def free_model(client):
    r = client.post(
        "/api/v1/models/",
        json={
            "name": FREE_MODEL_NAME,
            "provider": "tencent",
            "model_id": FREE_MODEL,
            "context_length": 32000,
            "pricing": {"input_per_1k": 0.0, "output_per_1k": 0.0},
            "capabilities": ["chat"],
            "is_active": True,
        },
    )
    assert r.status_code in (200, 201), r.text
    yield r.json()["id"]


@pytest.fixture()
def project_and_parts(client):
    """Create project + dataset + benchmark + prompt, return their ids."""
    pid = client.post("/api/v1/projects/", json={"name": "E2E free-model"}).json()["id"]

    jsonl = "\n".join(
        json.dumps(q)
        for q in [
            {"question": "Compute 2 + 2.", "answer": "4"},
            {"question": "Compute 10 - 3.", "answer": "7"},
            {"question": "Compute 6 * 7.", "answer": "42"},
            {"question": "Compute 20 / 4.", "answer": "5"},
            {"question": "Compute 100 + 25.", "answer": "125"},
        ]
    ).encode("utf-8")
    ds = client.post(
        "/api/v1/datasets/upload",
        data={"project_id": pid, "name": "Arithmetic", "format": "jsonl"},
        files={"file": ("a.jsonl", jsonl, "application/x-ndjson")},
    ).json()
    assert ds["row_count"] == 5

    bm = client.post(
        "/api/v1/benchmarks/",
        json={"project_id": pid, "name": "QA EM", "type": "qa", "metric": "exact_match"},
    ).json()
    assert bm["metric"] == "exact_match"

    pr = client.post(
        "/api/v1/prompts/",
        json={
            "project_id": pid,
            "name": "Answer directly",
            "template": "Question: {question}\nGive only the final number.",
        },
    ).json()
    assert pr["variables"] == ["question"]

    return {"project_id": pid, "dataset_id": ds["id"], "benchmark_id": bm["id"], "prompt_id": pr["id"]}


def _wait_completed(client, exp_id: str, label: str, timeout: int = 90) -> dict:
    final = None
    for _ in range(timeout * 2):
        time.sleep(0.5)
        final = client.get(f"/api/v1/experiments/{exp_id}").json()
        if final["status"] in ("completed", "failed", "partial"):
            break
    assert final is not None and final["status"] in ("completed", "partial"), f"{label}: {final}"
    return final


# ----------------------------- Health -----------------------------
def test_health_reports_openrouter_mode(client):
    j = client.get("/api/v1/health").json()
    assert j["status"] == "ok"
    assert j["database"] == "ok"
    assert j["provider_mode"] == "openrouter"


# ----------------------------- Models -----------------------------
def test_models_presets_and_catalog(client):
    presets = client.get("/api/v1/models/presets").json()
    assert len(presets) == 8
    catalog = client.get("/api/v1/models/openrouter").json()
    assert len(catalog) > 0


def test_models_seed_list_get_update(client):
    seeded = client.post("/api/v1/models/seed").json()["seeded"]
    assert seeded == 8
    models = client.get("/api/v1/models/").json()
    assert len(models) >= 8
    assert client.get(f"/api/v1/models/{models[0]['id']}").status_code == 200

    mid = client.post(
        "/api/v1/models/",
        json={
            "name": "tmp", "provider": "p", "model_id": "p/m:free",
            "context_length": 1, "pricing": {"input_per_1k": 0, "output_per_1k": 0},
            "capabilities": ["chat"], "is_active": True,
        },
    ).json()["id"]
    upd = client.patch(f"/api/v1/models/{mid}", json={"name": "tmp-edited"}).json()
    assert upd["name"] == "tmp-edited"
    client.delete(f"/api/v1/models/{mid}")


def test_models_provider_filter(client, free_model):
    ten = client.get("/api/v1/models/", params={"provider": "tencent"}).json()
    assert any(m["model_id"] == FREE_MODEL for m in ten)


# ----------------------------- Projects -----------------------------
def test_projects_crud(client):
    pid = client.post("/api/v1/projects/", json={"name": "P"}).json()["id"]
    assert any(p["id"] == pid for p in client.get("/api/v1/projects/").json())
    assert client.get(f"/api/v1/projects/{pid}").status_code == 200
    assert client.patch(f"/api/v1/projects/{pid}", json={"description": "d"}).json()["description"] == "d"
    arch = client.post(f"/api/v1/projects/{pid}/archive").json()
    assert arch["status"] == "archived"
    client.delete(f"/api/v1/projects/{pid}")
    assert client.get(f"/api/v1/projects/{pid}").status_code == 404


# ----------------------------- Datasets -----------------------------
def test_datasets_upload_and_reads(client, project_and_parts):
    pid = project_and_parts["project_id"]
    did = project_and_parts["dataset_id"]
    assert client.get("/api/v1/datasets/", params={"project_id": pid}).status_code == 200
    assert client.get(f"/api/v1/datasets/{did}").status_code == 200
    prev = client.get(f"/api/v1/datasets/{did}/preview", params={"limit": 3}).json()
    assert len(prev) == 3
    assert "row_count" in client.get(f"/api/v1/datasets/{did}/stats").json()
    assert client.post(f"/api/v1/datasets/{did}/validate").json().get("valid") is True
    assert client.patch(f"/api/v1/datasets/{did}", json={"description": "e"}).status_code == 200


# ----------------------------- Prompts -----------------------------
def test_prompts_crud_and_render(client, project_and_parts):
    pid = project_and_parts["project_id"]
    prid = project_and_parts["prompt_id"]
    assert client.get("/api/v1/prompts/", params={"project_id": pid}).status_code == 200
    assert client.get(f"/api/v1/prompts/{prid}").status_code == 200
    rendered = client.post(
        f"/api/v1/prompts/{prid}/render", json={"variables": {"question": "Compute 2+2."}}
    ).json()["rendered"]
    assert "Compute 2+2." in rendered
    assert client.patch(f"/api/v1/prompts/{prid}", json={"template": "x"}).status_code == 200


# ----------------------------- Benchmarks -----------------------------
def test_benchmarks_crud(client, project_and_parts):
    pid = project_and_parts["project_id"]
    assert "metrics" in client.get("/api/v1/benchmarks/metrics/available").json()
    bmid = project_and_parts["benchmark_id"]
    assert any(b["id"] == bmid for b in client.get("/api/v1/benchmarks/", params={"project_id": pid}).json())
    assert client.get(f"/api/v1/benchmarks/{bmid}").status_code == 200
    assert client.patch(f"/api/v1/benchmarks/{bmid}", json={"description": "e"}).status_code == 200


# ----------------------------- Experiments (real free model) -----------------------------
@pytest.fixture()
def evaluated_experiments(client, project_and_parts, free_model):
    """Create one experiment on the REAL free model, run it (acc=1.0), retry it,
    then duplicate + run the copy for comparison. Returns (eid, dup_id)."""
    eid = client.post(
        "/api/v1/experiments/",
        json={
            "project_id": project_and_parts["project_id"],
            "name": "Run: HY3 free",
            "dataset_id": project_and_parts["dataset_id"],
            "benchmark_id": project_and_parts["benchmark_id"],
            "prompt_id": project_and_parts["prompt_id"],
            "model_id": free_model,
        },
    ).json()["id"]
    assert client.get(f"/api/v1/experiments/{eid}").status_code == 200
    assert any(
        e["id"] == eid
        for e in client.get("/api/v1/experiments/", params={"project_id": project_and_parts["project_id"]}).json()
    )

    # run on the REAL free model
    assert client.post(f"/api/v1/experiments/{eid}/run").status_code == 200
    final = _wait_completed(client, eid, "run")
    # Free models are not 100% reliable; assert a high accuracy rather than a
    # perfect score, and confirm it is genuinely the free model (cost == 0).
    assert final["metrics"]["accuracy"] >= 0.6, final["metrics"]
    assert final["total_cost"] == 0.0  # free model priced at 0

    results = client.get(f"/api/v1/experiments/{eid}/results").json()
    assert len(results) == 5
    assert all(r["score"] in (0.0, 1.0) for r in results)

    # retry
    client.post(f"/api/v1/experiments/{eid}/retry")
    _wait_completed(client, eid, "retry")

    # duplicate + run for a 2-experiment comparison
    dup = client.post(
        f"/api/v1/experiments/{eid}/duplicate", json={"name": "Run: HY3 free (copy)"}
    ).json()
    assert dup["name"].endswith("(copy)")
    client.post(f"/api/v1/experiments/{dup['id']}/run")
    _wait_completed(client, dup["id"], "duplicate")

    assert client.patch(f"/api/v1/experiments/{eid}", json={"notes": "e2e"}).status_code == 200
    return eid, dup["id"]


def test_experiment_run_retry_duplicate(client, evaluated_experiments):
    """Smoke: the experiment fixture ran a real free-model evaluation correctly."""
    eid, dup_id = evaluated_experiments
    assert eid and dup_id


# ----------------------------- Analytics -----------------------------
def test_analytics_compare_and_reads(client, project_and_parts, free_model, evaluated_experiments):
    eid, dup_id = evaluated_experiments
    pid = project_and_parts["project_id"]

    cmp = client.post("/api/v1/analytics/compare", json={"experiment_ids": [eid, dup_id]}).json()
    assert "dimensions" in cmp and "experiments" in cmp

    assert len(client.get("/api/v1/analytics/leaderboard", params={"project_id": pid}).json()) >= 1
    assert client.get(f"/api/v1/analytics/experiments/{eid}/failures").status_code == 200
    assert client.get("/api/v1/analytics/trend", params={"project_id": pid}).status_code == 200
    summary = client.get(f"/api/v1/analytics/projects/{pid}/summary").json()
    assert summary["experiment_count"] >= 2


# ----------------------------- Reports -----------------------------
def test_reports_generate_list_export(client, project_and_parts, free_model, evaluated_experiments):
    eid, dup_id = evaluated_experiments
    pid = project_and_parts["project_id"]

    rep = client.post(
        "/api/v1/reports/generate",
        json={"project_id": pid, "experiment_ids": [eid, dup_id], "title": "E2E Report"},
    ).json()
    assert rep["title"] == "E2E Report"
    rid = rep["id"]

    assert any(r["id"] == rid for r in client.get("/api/v1/reports/", params={"project_id": pid}).json())
    assert client.get(f"/api/v1/reports/{rid}").status_code == 200
    exp = client.get(f"/api/v1/reports/{rid}/export")
    assert "text/markdown" in exp.headers.get("content-type", "")
    assert len(exp.text) > 0
