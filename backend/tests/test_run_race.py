"""Race-condition test for the runner's CAS guard.

Two concurrent run_experiment calls for the same experiment must resolve so that
exactly one flips status to 'running' and writes results; the loser bails out
without inserting a second (overwriting) batch of ExperimentResults.
"""
from __future__ import annotations

import asyncio
import uuid

import pytest

from app.core.database import AsyncSessionLocal
from app.evaluation.runner import run_experiment
from app.providers.mock import MockProvider
from app.repositories.experiment import ExperimentRepository, ExperimentResultRepository


@pytest.fixture(autouse=True)
def force_mock_provider(monkeypatch):
    """Keep this an offline race test: never hit the real OpenRouter API."""
    monkeypatch.setattr(
        "app.evaluation.runner.get_provider", lambda _name=None: MockProvider()
    )


def _make_client(client):
    """Seed a project/dataset/benchmark/prompt/model and return an experiment id."""
    assert client.post("/api/v1/models/seed").status_code in (200, 201)
    models = client.get("/api/v1/models/").json()
    model_pk = models[0]["id"]
    pid = client.post("/api/v1/projects/", json={"name": "RT"}).json()["id"]
    b = client.post(
        "/api/v1/benchmarks/",
        json={"project_id": pid, "name": "QA", "type": "qa", "metric": "exact_match_ci"},
    ).json()
    pr = client.post(
        "/api/v1/prompts/",
        json={"project_id": pid, "name": "P", "template": "{question}"},
    ).json()
    jsonl = b'{"question":"2+2?","answer":"4"}\n{"question":"3*3?","answer":"9"}\n'
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


def test_concurrent_run_no_double_write(client):
    eid = _make_client(client)

    # Fire two concurrent runner tasks against the same experiment.
    async def _go():
        await asyncio.gather(run_experiment(eid), run_experiment(eid))

    asyncio.run(_go())

    # Wait briefly for any in-flight work to settle.
    for _ in range(50):
        with client:
            final = client.get(f"/api/v1/experiments/{eid}").json()
        if final["status"] in ("completed", "failed"):
            break
        time_sleep()

    async def _inspect():
        async with AsyncSessionLocal() as session:
            exp_repo = ExperimentRepository(session)
            res_repo = ExperimentResultRepository(session)
            exp = await exp_repo.get(eid)
            results = await res_repo.list_by_experiment(eid, limit=10_000_000)
            return exp, results

    exp, results = asyncio.run(_inspect())
    # Exactly one batch (2 rows) was written, never doubled (4 rows).
    assert len(results) == 2, f"expected 2 result rows, got {len(results)}"
    assert exp is not None and exp.status == "completed"
    assert exp.metrics.get("rows_total") == 2


def time_sleep():
    import time

    time.sleep(0.1)
