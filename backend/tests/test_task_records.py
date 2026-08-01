"""Regression tests for persistent evaluation task records."""
from __future__ import annotations

import asyncio
import time

import pytest

from app.core.database import AsyncSessionLocal
from app.evaluation.task_records import (
    create_task,
    mark_done,
    mark_failed_after_restart,
    mark_running,
)
from app.models.task import EvaluationTask
from app.providers.mock import MockProvider
from app.repositories.experiment import ExperimentRepository
from app.repositories.task import TaskRepository


@pytest.fixture(autouse=True)
def force_mock_provider(monkeypatch):
    """Keep end-to-end runs offline with the deterministic Mock provider."""
    monkeypatch.setattr(
        "app.evaluation.runner.get_provider", lambda name=None: MockProvider()
    )


async def _list_tasks(experiment_id: str) -> list[EvaluationTask]:
    async with AsyncSessionLocal() as session:
        return await TaskRepository(session).list(
            filters={"experiment_id": experiment_id}
        )


def test_task_lifecycle_queued_running_done(client):
    """create_task -> mark_running -> mark_done must transition the record."""
    assert client.post("/api/v1/models/seed").status_code in (200, 201)
    model_pk = client.get("/api/v1/models/").json()["items"][0]["id"]
    pid = client.post("/api/v1/projects/", json={"name": "TaskLifecycle"}).json()["id"]
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
        files={"file": ("d.jsonl", b'{"question":"q","answer":"a"}\n', "application/x-ndjson")},
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

    created = asyncio.run(create_task(exp["id"]))
    assert created is not None and created.status == "queued"

    asyncio.run(mark_running(exp["id"]))
    tasks = asyncio.run(_list_tasks(exp["id"]))
    assert len(tasks) == 1
    assert tasks[0].status == "running"
    assert tasks[0].started_at is not None

    asyncio.run(mark_done(exp["id"], status="succeeded"))
    tasks = asyncio.run(_list_tasks(exp["id"]))
    assert tasks[0].status == "succeeded"
    assert tasks[0].finished_at is not None


def test_full_run_persists_succeeded_task(client):
    """A complete evaluation run must end with a 'succeeded' task record."""
    assert client.post("/api/v1/models/seed").status_code in (200, 201)
    model_pk = client.get("/api/v1/models/").json()["items"][0]["id"]
    pid = client.post("/api/v1/projects/", json={"name": "TaskRun"}).json()["id"]
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
        files={"file": ("d.jsonl", b'{"question":"q","answer":"a"}\n', "application/x-ndjson")},
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

    client.post(f"/api/v1/experiments/{exp['id']}/run")
    for _ in range(50):
        status = client.get(f"/api/v1/experiments/{exp['id']}").json()["status"]
        if status in ("completed", "failed", "partial", "cancelled"):
            break
        time.sleep(0.1)

    tasks = asyncio.run(_list_tasks(exp["id"]))
    assert len(tasks) == 1
    assert tasks[0].status == "succeeded"
    assert tasks[0].started_at is not None
    assert tasks[0].finished_at is not None


def test_startup_recovery_marks_experiment_and_task_failed(client):
    """Stale running/queued experiments and their tasks become failed."""
    assert client.post("/api/v1/models/seed").status_code in (200, 201)
    model_pk = client.get("/api/v1/models/").json()["items"][0]["id"]
    pid = client.post("/api/v1/projects/", json={"name": "TaskRecover"}).json()["id"]
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
        files={"file": ("d.jsonl", b'{"question":"q","answer":"a"}\n', "application/x-ndjson")},
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

    async def _stale():
        async with AsyncSessionLocal() as session:
            repo = ExperimentRepository(session)
            e = await repo.get(exp["id"])
            await repo.update(e, {"status": "running"})
            await session.commit()
        await create_task(exp["id"])
        await mark_running(exp["id"])

    asyncio.run(_stale())

    from app.main import _recover_stale_experiments

    asyncio.run(_recover_stale_experiments())

    exp_now = client.get(f"/api/v1/experiments/{exp['id']}").json()
    assert exp_now["status"] == "failed"
    tasks = asyncio.run(_list_tasks(exp["id"]))
    assert len(tasks) == 1
    assert tasks[0].status == "failed"
    assert "Server shutdown" in (tasks[0].error or "")


def test_running_endpoint_includes_queued(client):
    assert client.post("/api/v1/models/seed").status_code in (200, 201)
    model_pk = client.get("/api/v1/models/").json()["items"][0]["id"]
    pid = client.post("/api/v1/projects/", json={"name": "TaskQueued"}).json()["id"]
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
        files={"file": ("d.jsonl", b'{"question":"q","answer":"a"}\n', "application/x-ndjson")},
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

    async def _set_queued():
        async with AsyncSessionLocal() as session:
            repo = ExperimentRepository(session)
            e = await repo.get(exp["id"])
            await repo.update(e, {"status": "queued"})
            await session.commit()

    asyncio.run(_set_queued())

    body = client.get("/api/v1/experiments/running").json()
    assert any(t["experiment_id"] == exp["id"] and t["status"] == "queued" for t in body)
