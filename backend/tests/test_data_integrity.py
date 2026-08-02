"""Tests for the data-model integrity fixes.

Covers: unique/CHECK constraints, materialized-metric backfill, model dedupe,
dangling-reference repair, delete markers on evaluation_tasks, archive
endpoints, UTC timestamp round-tripping, and the integrity-check endpoint.
"""
from __future__ import annotations

import os
import tempfile
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.database import AsyncSessionLocal
from app.models.dataset import Dataset, DatasetRow
from app.models.experiment import Experiment
from app.models.project import Project
from app.models.task import EvaluationTask


def _scratch_engine():
    path = os.path.join(
        tempfile.gettempdir(), f"benchmarkops_integrity_{uuid.uuid4().hex}.db"
    )
    return create_async_engine(f"sqlite+aiosqlite:///{path}", future=True), path


def test_seed_defaults_is_idempotent(client):
    client.post("/api/v1/models/seed")
    r = client.post("/api/v1/models/seed")
    assert r.status_code == 200
    assert r.json()["seeded"] == 0


def test_duplicate_model_rejected(client):
    payload = {
        "name": "Dup model",
        "provider": "openai",
        "model_id": "openai/gpt-dupe-test",
    }
    r1 = client.post("/api/v1/models/", json=payload)
    assert r1.status_code in (200, 201)
    r2 = client.post("/api/v1/models/", json=payload)
    assert r2.status_code == 409


def test_model_update_to_duplicate_provider_model_rejected(client):
    r1 = client.post(
        "/api/v1/models/",
        json={
            "name": "Update dup A",
            "provider": "openai",
            "model_id": "openai/update-dup-a",
        },
    )
    r2 = client.post(
        "/api/v1/models/",
        json={
            "name": "Update dup B",
            "provider": "openai",
            "model_id": "openai/update-dup-b",
        },
    )
    assert r1.status_code in (200, 201)
    assert r2.status_code in (200, 201)

    r3 = client.patch(
        f"/api/v1/models/{r2.json()['id']}",
        json={"model_id": "openai/update-dup-a"},
    )
    assert r3.status_code == 409


def test_duplicate_prompt_name_rejected(client):
    pid = client.post("/api/v1/projects/", json={"name": "DupPrompt"}).json()["id"]
    payload = {"project_id": pid, "name": "P", "template": "{question}"}
    r1 = client.post("/api/v1/prompts/", json=payload)
    assert r1.status_code in (200, 201)
    r2 = client.post("/api/v1/prompts/", json=payload)
    assert r2.status_code == 409


def test_duplicate_benchmark_name_rejected(client):
    pid = client.post("/api/v1/projects/", json={"name": "DupBench"}).json()["id"]
    payload = {
        "project_id": pid,
        "name": "B",
        "type": "qa",
        "metric": "exact_match_ci",
    }
    r1 = client.post("/api/v1/benchmarks/", json=payload)
    assert r1.status_code in (200, 201)
    r2 = client.post("/api/v1/benchmarks/", json=payload)
    assert r2.status_code == 409


def test_duplicate_dataset_name_rejected(client):
    pid = client.post("/api/v1/projects/", json={"name": "DupDS"}).json()["id"]
    data = {"project_id": pid, "name": "D", "format": "jsonl"}
    files = {
        "file": ("d.jsonl", b'{"question":"q","answer":"a"}\n', "application/x-ndjson")
    }
    r1 = client.post("/api/v1/datasets/upload", data=data, files=files)
    assert r1.status_code in (200, 201)
    r2 = client.post("/api/v1/datasets/upload", data=data, files=files)
    assert r2.status_code == 409


def test_duplicate_rename_rejected(client):
    suffix = uuid.uuid4().hex[:8]
    pid = client.post(
        "/api/v1/projects/", json={"name": f"RenameDup-{suffix}"}
    ).json()["id"]
    client.post(
        "/api/v1/prompts/",
        json={"project_id": pid, "name": "p-one", "template": "{question}"},
    )
    p2 = client.post(
        "/api/v1/prompts/",
        json={"project_id": pid, "name": "p-two", "template": "{question}"},
    ).json()
    r = client.patch(f"/api/v1/prompts/{p2['id']}", json={"name": "p-one"})
    assert r.status_code == 409


def test_rename_benchmark_to_duplicate_name_rejected(client):
    suffix = uuid.uuid4().hex[:8]
    pid = client.post(
        "/api/v1/projects/", json={"name": f"RenameBench-{suffix}"}
    ).json()["id"]
    b1 = client.post(
        "/api/v1/benchmarks/",
        json={
            "project_id": pid,
            "name": "b-one",
            "type": "qa",
            "metric": "exact_match_ci",
        },
    ).json()
    client.post(
        "/api/v1/benchmarks/",
        json={
            "project_id": pid,
            "name": "b-two",
            "type": "qa",
            "metric": "exact_match_ci",
        },
    ).json()
    r = client.patch(f"/api/v1/benchmarks/{b1['id']}", json={"name": "b-two"})
    assert r.status_code == 409


def test_rename_dataset_to_duplicate_name_rejected(client):
    suffix = uuid.uuid4().hex[:8]
    pid = client.post(
        "/api/v1/projects/", json={"name": f"RenameDS-{suffix}"}
    ).json()["id"]
    files = {
        "file": ("d.jsonl", b'{"question":"q","answer":"a"}\n', "application/x-ndjson")
    }
    d1 = client.post(
        "/api/v1/datasets/upload",
        data={"project_id": pid, "name": "d-one", "format": "jsonl"},
        files=files,
    ).json()
    client.post(
        "/api/v1/datasets/upload",
        data={"project_id": pid, "name": "d-two", "format": "jsonl"},
        files=files,
    ).json()
    r = client.patch(f"/api/v1/datasets/{d1['id']}", json={"name": "d-two"})
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_duplicate_dataset_row_idx_rejected() -> None:
    async with AsyncSessionLocal() as session:
        try:
            session.add(DatasetRow(dataset_id="dup-ds", idx=0, input={}, expected=None))
            await session.flush()
            session.add(DatasetRow(dataset_id="dup-ds", idx=0, input={}, expected=None))
            with pytest.raises(IntegrityError):
                await session.flush()
        finally:
            await session.rollback()


@pytest.mark.asyncio
async def test_invalid_experiment_status_rejected() -> None:
    async with AsyncSessionLocal() as session:
        try:
            session.add(
                Experiment(
                    project_id="chk",
                    name="bad-status",
                    dataset_id="d",
                    benchmark_id="b",
                    prompt_id="p",
                    model_id="m",
                    status="bogus",
                )
            )
            with pytest.raises(IntegrityError):
                await session.flush()
        finally:
            await session.rollback()


async def _build_experiment(client, project_name: str) -> dict:
    pid = client.post("/api/v1/projects/", json={"name": project_name}).json()["id"]
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
        files={
            "file": (
                "d.jsonl",
                b'{"question":"q","answer":"a"}\n',
                "application/x-ndjson",
            )
        },
    ).json()
    client.post("/api/v1/models/seed")
    model_pk = client.get("/api/v1/models/").json()["items"][0]["id"]
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
    return {"project_id": pid, "experiment_id": exp["id"]}


async def _insert_task(experiment_id: str, *, deleted: bool = False) -> None:
    async with AsyncSessionLocal() as session:
        session.add(
            EvaluationTask(
                experiment_id=experiment_id,
                action="run",
                status="queued",
                attempts=1,
                experiment_deleted_at=(
                    datetime.now(timezone.utc) if deleted else None
                ),
            )
        )
        await session.commit()


async def _task_rows(experiment_id: str) -> list[EvaluationTask]:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            sa.select(EvaluationTask).where(
                EvaluationTask.experiment_id == experiment_id
            )
        )
        return list(result.scalars().all())


@pytest.mark.asyncio
async def test_delete_experiment_marks_task_not_deletes(client) -> None:
    ids = await _build_experiment(client, "TaskMark")
    await _insert_task(ids["experiment_id"])

    r = client.delete(f"/api/v1/experiments/{ids['experiment_id']}")
    assert r.status_code == 204

    tasks = await _task_rows(ids["experiment_id"])
    assert len(tasks) == 1
    assert tasks[0].experiment_deleted_at is not None


@pytest.mark.asyncio
async def test_project_delete_marks_tasks_not_deletes(client) -> None:
    ids = await _build_experiment(client, "TaskMarkProj")
    await _insert_task(ids["experiment_id"])

    r = client.delete(f"/api/v1/projects/{ids['project_id']}")
    assert r.status_code == 204

    tasks = await _task_rows(ids["experiment_id"])
    assert len(tasks) == 1
    assert tasks[0].experiment_deleted_at is not None


@pytest.mark.asyncio
async def test_task_repo_ignores_tasks_for_deleted_experiments() -> None:
    from app.repositories.task import TaskRepository

    async with AsyncSessionLocal() as session:
        try:
            now = datetime.now(timezone.utc)
            session.add(
                EvaluationTask(
                    experiment_id="taskexp-1",
                    action="run",
                    status="queued",
                    attempts=1,
                    created_at=now - timedelta(minutes=1),
                )
            )
            session.add(
                EvaluationTask(
                    experiment_id="taskexp-1",
                    action="run",
                    status="queued",
                    attempts=1,
                    created_at=now,
                    experiment_deleted_at=now,
                )
            )
            await session.flush()
            active = await TaskRepository(session).get_latest_active("taskexp-1")
            assert active is not None
            assert active.experiment_deleted_at is None
        finally:
            await session.rollback()


@pytest.mark.asyncio
async def test_migration_16_backfills_materialized_metrics() -> None:
    from app.migrations import MIGRATIONS

    engine, path = _scratch_engine()
    try:
        async with engine.begin() as conn:
            await conn.execute(
                sa.text(
                    """
                    CREATE TABLE experiments (
                        id VARCHAR(36) PRIMARY KEY,
                        metrics JSON,
                        accuracy FLOAT NOT NULL DEFAULT 0.0,
                        avg_latency_ms FLOAT NOT NULL DEFAULT 0.0
                    )
                    """
                )
            )
            await conn.execute(
                sa.text(
                    """
                    INSERT INTO experiments (id, metrics, accuracy, avg_latency_ms)
                    VALUES ('e1', '{"accuracy": 0.75, "avg_latency_ms": 123.4}', 0.0, 0.0)
                    """
                )
            )
            await MIGRATIONS[16](conn)
            row = (
                await conn.execute(
                    sa.text(
                        "SELECT accuracy, avg_latency_ms FROM experiments WHERE id='e1'"
                    )
                )
            ).first()
        assert row is not None
        assert abs(row[0] - 0.75) < 1e-9
        assert abs(row[1] - 123.4) < 1e-9
    finally:
        await engine.dispose()
        if os.path.exists(path):
            os.remove(path)


@pytest.mark.asyncio
async def test_migration_16_dedupes_models_keeping_referenced() -> None:
    from app.migrations import MIGRATIONS

    engine, path = _scratch_engine()
    try:
        async with engine.begin() as conn:
            await conn.execute(
                sa.text(
                    """
                    CREATE TABLE models (
                        id VARCHAR(36) PRIMARY KEY,
                        provider VARCHAR(50),
                        model_id VARCHAR(200),
                        created_at TIMESTAMP NOT NULL,
                        updated_at TIMESTAMP NOT NULL
                    )
                    """
                )
            )
            await conn.execute(
                sa.text(
                    """
                    CREATE TABLE experiments (
                        id VARCHAR(36) PRIMARY KEY,
                        model_id VARCHAR(36)
                    )
                    """
                )
            )
            await conn.execute(
                sa.text(
                    """
                    INSERT INTO models VALUES
                        ('a1','openai','openai/x','2026-01-01 00:00:00','2026-01-01 00:00:00'),
                        ('a2','openai','openai/x','2026-01-02 00:00:00','2026-01-02 00:00:00'),
                        ('a3','openai','openai/x','2026-01-03 00:00:00','2026-01-03 00:00:00'),
                        ('b1','qwen','qwen/y','2026-01-01 00:00:00','2026-01-01 00:00:00'),
                        ('b2','qwen','qwen/y','2026-01-02 00:00:00','2026-01-02 00:00:00'),
                        ('c1','zhipu','zhipuai/glm-4','2026-01-01 00:00:00','2026-01-01 00:00:00'),
                        ('c2','zhipu','zhipuai/glm-4','2026-01-02 00:00:00','2026-01-02 00:00:00')
                    """
                )
            )
            await conn.execute(
                sa.text(
                    "INSERT INTO experiments (id, model_id) VALUES "
                    "('e1','a2'), ('e2','c1'), ('e3','c2')"
                )
            )
            await MIGRATIONS[16](conn)
            ids = [
                r[0]
                for r in (
                    await conn.execute(sa.text("SELECT id FROM models ORDER BY id"))
                ).fetchall()
            ]
            groups = (
                await conn.execute(
                    sa.text(
                        "SELECT COUNT(*) FROM (SELECT provider, model_id FROM models "
                        "GROUP BY provider, model_id HAVING COUNT(*) > 1)"
                    )
                )
            ).scalar()
            repointed = (
                await conn.execute(
                    sa.text(
                        "SELECT model_id FROM experiments WHERE id='e3'"
                    )
                )
            ).scalar()
        assert ids == ["a2", "b1", "c1"]
        assert groups == 0
        assert repointed == "c1"
    finally:
        await engine.dispose()
        if os.path.exists(path):
            os.remove(path)


@pytest.mark.asyncio
async def test_unique_and_composite_indexes_exist(client) -> None:
    async with AsyncSessionLocal() as session:
        rows = await session.execute(
            sa.text(
                "SELECT name FROM sqlite_master WHERE type='index' "
                "AND name IN ('uq_dataset_rows_dataset_version_idx', "
                "'uq_experiment_results_experiment_row', "
                "'uq_models_provider_model_id', "
                "'uq_datasets_project_name')"
            )
        )
        names = {r[0] for r in rows.fetchall()}
    assert names == {
        "uq_dataset_rows_dataset_version_idx",
        "uq_experiment_results_experiment_row",
        "uq_models_provider_model_id",
        "uq_datasets_project_name",
    }


@pytest.mark.asyncio
async def test_integrity_endpoint_reports_dangling(client) -> None:
    async with AsyncSessionLocal() as session:
        session.add(
            Dataset(
                project_id="missing-project-x",
                name="dangling-ds",
                format="jsonl",
            )
        )
        await session.commit()

    try:
        r = client.get("/api/v1/db/integrity")
        assert r.status_code == 200
        assert r.json()["datasets_missing_project"] >= 1
    finally:
        async with AsyncSessionLocal() as session:
            await session.execute(
                sa.text(
                    "DELETE FROM datasets WHERE name='dangling-ds' "
                    "AND project_id='missing-project-x'"
                )
            )
            await session.commit()


@pytest.mark.asyncio
async def test_repair_cleans_dangling_and_restores_models() -> None:
    from app.core.integrity import check_integrity
    from app.repair_integrity import repair_database

    async with AsyncSessionLocal() as session:
        try:
            ds = Dataset(
                project_id="missing-proj",
                name="repair-ds",
                format="jsonl",
            )
            session.add(ds)
            await session.flush()
            session.add(DatasetRow(dataset_id=ds.id, idx=0, input={}, expected=None))
            exp = Experiment(
                project_id="missing-proj2",
                name="repair-exp",
                dataset_id="x",
                benchmark_id="y",
                prompt_id="z",
                model_id="restored-model-uuid",
                status="completed",
                model_snapshot={
                    "model_id": "openai/repair-probe",
                    "name": "Repair Probe",
                    "pricing": {},
                },
            )
            session.add(exp)
            await session.flush()
            session.add(
                EvaluationTask(
                    experiment_id=exp.id,
                    action="run",
                    status="queued",
                    attempts=1,
                )
            )
            await session.flush()
            # An experiment whose snapshot model_id already exists should be
            # repointed to the existing row instead of creating a duplicate.
            project = Project(name="repair-proj", status="active")
            session.add(project)
            await session.flush()
            repoint_exp = Experiment(
                project_id=project.id,
                name="repair-repoint",
                dataset_id="x",
                benchmark_id="y",
                prompt_id="z",
                model_id="repair-repoint-uuid",
                status="completed",
                model_snapshot={
                    "model_id": "openai/gpt-4o-mini",
                    "name": "GPT-4o mini",
                    "pricing": {},
                },
            )
            session.add(repoint_exp)
            await session.flush()

            report = await repair_database(session)
            await session.flush()
            results = await check_integrity(session)

            restored = (
                await session.execute(
                    sa.text(
                        "SELECT COUNT(*) FROM models WHERE id='restored-model-uuid'"
                    )
                )
            ).scalar()
            repoint_row = (
                await session.execute(
                    sa.text(
                        "SELECT model_id FROM experiments "
                        "WHERE id=:id"
                    ),
                    {"id": repoint_exp.id},
                )
            ).scalar()
            repoint_target_exists = (
                await session.execute(
                    sa.text(
                        "SELECT COUNT(*) FROM models WHERE model_id='openai/gpt-4o-mini'"
                    )
                )
            ).scalar()
            assert report["experiments_deleted"] >= 1
            assert report["datasets_deleted"] >= 1
            assert restored == 1
            assert report["models_repointed"] >= 1
            assert repoint_row != "repair-repoint-uuid"
            assert repoint_target_exists >= 1
            assert results["datasets_missing_project"] == 0
            assert results["experiments_missing_project"] == 0
            assert results["evaluation_tasks_missing_experiment"] == 0
        finally:
            await session.rollback()


def test_archive_dataset_prompt_and_benchmark(client):
    pid = client.post("/api/v1/projects/", json={"name": "ArchProj"}).json()["id"]
    ds = client.post(
        "/api/v1/datasets/upload",
        data={"project_id": pid, "name": "ArchDS", "format": "jsonl"},
        files={
            "file": (
                "d.jsonl",
                b'{"question":"q","answer":"a"}\n',
                "application/x-ndjson",
            )
        },
    ).json()
    pr = client.post(
        "/api/v1/prompts/",
        json={"project_id": pid, "name": "ArchP", "template": "{question}"},
    ).json()
    bm = client.post(
        "/api/v1/benchmarks/",
        json={
            "project_id": pid,
            "name": "ArchB",
            "type": "qa",
            "metric": "exact_match_ci",
        },
    ).json()

    r = client.post(f"/api/v1/datasets/{ds['id']}/archive")
    assert r.status_code == 200
    assert r.json()["is_archived"] is True
    assert client.post(f"/api/v1/datasets/{ds['id']}/unarchive").json()["is_archived"] is False

    assert client.post(f"/api/v1/prompts/{pr['id']}/archive").json()["is_archived"] is True
    assert client.post(f"/api/v1/prompts/{pr['id']}/unarchive").json()["is_archived"] is False

    assert client.post(f"/api/v1/benchmarks/{bm['id']}/archive").json()["is_archived"] is True
    assert client.post(f"/api/v1/benchmarks/{bm['id']}/unarchive").json()["is_archived"] is False


@pytest.mark.asyncio
async def test_timestamps_roundtrip_as_utc_aware() -> None:
    async with AsyncSessionLocal() as session:
        try:
            original = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
            p = Project(name="utc-probe", created_at=original, updated_at=original)
            session.add(p)
            await session.flush()
            await session.refresh(p)
            assert p.created_at.tzinfo is not None
            assert p.created_at.utcoffset() == timedelta(0)
            assert abs((p.created_at - original).total_seconds()) < 1
        finally:
            await session.rollback()
