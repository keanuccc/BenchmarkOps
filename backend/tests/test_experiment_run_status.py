"""ExperimentService.run() returns 'queued' and refuses duplicate submissions.

Also: service.run() must not set status back to 'pending' (the UI must reflect
the received state immediately). retry() shares the same guard.
"""
from __future__ import annotations

import asyncio

import pytest

from app.core.database import AsyncSessionLocal
from app.core.exceptions import ConflictError
from app.repositories.experiment import ExperimentRepository
from app.services.experiment_service import ExperimentService


def _build_experiment(client):
    assert client.post("/api/v1/models/seed").status_code in (200, 201)
    models = client.get("/api/v1/models/").json()
    model_pk = models[0]["id"]
    pid = client.post("/api/v1/projects/", json={"name": "RS"}).json()["id"]
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


def test_run_sets_queued_status(client):
    eid = _build_experiment(client)

    async def _go():
        async with AsyncSessionLocal() as session:
            svc = ExperimentService(session)
            return await svc.run(eid)

    exp = asyncio.run(_go())
    assert exp.status == "queued"
    assert exp.status != "pending"


def test_run_conflicts_when_running(client):
    eid = _build_experiment(client)

    async def _mark_running():
        async with AsyncSessionLocal() as session:
            repo = ExperimentRepository(session)
            exp = await repo.get(eid)
            await repo.update(exp, {"status": "running"})
            await session.commit()

    async def _try_run():
        async with AsyncSessionLocal() as session:
            svc = ExperimentService(session)
            return await svc.run(eid)

    asyncio.run(_mark_running())
    with pytest.raises(ConflictError):
        asyncio.run(_try_run())


def test_run_conflicts_when_queued(client):
    eid = _build_experiment(client)

    async def _mark_queued():
        async with AsyncSessionLocal() as session:
            repo = ExperimentRepository(session)
            exp = await repo.get(eid)
            await repo.update(exp, {"status": "queued"})
            await session.commit()

    async def _try_run():
        async with AsyncSessionLocal() as session:
            svc = ExperimentService(session)
            return await svc.run(eid)

    asyncio.run(_mark_queued())
    with pytest.raises(ConflictError):
        asyncio.run(_try_run())
