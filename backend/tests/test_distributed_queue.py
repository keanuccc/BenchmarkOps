"""Distributed evaluation queue (ARQ + Redis) tests.

These tests exercise the real ARQ worker against a local Redis instance
(logical DB 15, see conftest). They are skipped automatically when Redis is
unreachable, so CI without a Redis service stays green. The default
``asyncio`` backend is untouched and keeps its own test coverage.
"""
from __future__ import annotations

import asyncio
import uuid

import pytest
from arq import Retry
from arq.connections import RedisSettings, create_pool
from arq.constants import (
    abort_jobs_ss,
    default_queue_name,
    in_progress_key_prefix,
    job_key_prefix,
    result_key_prefix,
    retry_key_prefix,
)
from arq.worker import Worker, func
from sqlalchemy.exc import OperationalError

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.evaluation.errors import RetryableTaskError
from app.evaluation.task_queue import ArqTaskQueue
from app.providers.base import ProviderQuotaExhaustedError
from app.providers.mock import MockProvider
from app.repositories.experiment import ExperimentRepository, ExperimentResultRepository


pytestmark = pytest.mark.redis


@pytest.fixture(autouse=True)
def force_mock_provider(monkeypatch):
    """Keep end-to-end runs offline with the deterministic Mock provider."""
    monkeypatch.setattr(
        "app.evaluation.runner.get_provider", lambda _name=None: MockProvider()
    )


@pytest.fixture(scope="session")
def redis_available() -> bool:
    from redis.asyncio import from_url

    try:
        async def _ping() -> None:
            client = from_url(settings.redis_dsn, socket_connect_timeout=1)
            try:
                await client.ping()
            finally:
                await client.aclose()

        asyncio.run(_ping())
    except Exception:
        return False
    return True


@pytest.fixture()
def redis_queue(redis_available):
    """Skip when Redis is unavailable; clean up ARQ keys for tracked job ids."""
    if not redis_available:
        pytest.skip("Redis is not available; skipping distributed queue tests")
    job_ids: list[str] = []
    yield job_ids

    async def _cleanup() -> None:
        pool = await create_pool(RedisSettings.from_dsn(settings.redis_dsn))
        try:
            for job_id in job_ids:
                await pool.delete(
                    job_key_prefix + job_id,
                    result_key_prefix + job_id,
                    in_progress_key_prefix + job_id,
                    retry_key_prefix + job_id,
                )
                await pool.zrem(default_queue_name, job_id)
        finally:
            await pool.aclose(close_connection_pool=True)

    asyncio.run(_cleanup())


def _make_experiment(client) -> str:
    """Seed a project/dataset/benchmark/prompt/model and return an experiment id."""
    assert client.post("/api/v1/models/seed").status_code in (200, 201)
    models = client.get("/api/v1/models/").json()["items"]
    model_pk = models[0]["id"]
    pid = client.post("/api/v1/projects/", json={"name": "DQ"}).json()["id"]
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


async def _list_tasks(experiment_id: str) -> list:
    from app.repositories.task import TaskRepository

    async with AsyncSessionLocal() as session:
        return await TaskRepository(session).list(
            filters={"experiment_id": experiment_id}
        )


def _make_worker(*, burst: bool = True, poll_delay: float = 0.05, **kwargs) -> Worker:
    from app.worker import run_experiment_task

    return Worker(
        functions=[func(run_experiment_task, name="run_experiment", max_tries=2)],
        redis_settings=RedisSettings.from_dsn(settings.redis_dsn),
        burst=burst,
        max_burst_jobs=1,
        allow_abort_jobs=True,
        handle_signals=True,
        poll_delay=poll_delay,
        **kwargs,
    )


# --- Queue API (ArqTaskQueue) ------------------------------------------------


async def test_arq_submit_enqueues_persistent_job(redis_queue):
    eid = f"exp-{uuid.uuid4().hex}"
    redis_queue.append(eid)
    queue = ArqTaskQueue(redis_dsn=settings.redis_dsn)
    queue.submit(lambda: None, experiment_id=eid)
    # A duplicate submission must be a no-op: the job id is the experiment id.
    queue.submit(lambda: None, experiment_id=eid)

    pool = await create_pool(RedisSettings.from_dsn(settings.redis_dsn))
    try:
        jobs = await pool.queued_jobs()
    finally:
        await pool.aclose(close_connection_pool=True)
    matching = [j for j in jobs if j.job_id == eid]
    assert len(matching) == 1
    assert matching[0].function == "run_experiment"
    assert matching[0].args == (eid,)


async def test_arq_submit_requires_experiment_id():
    queue = ArqTaskQueue(redis_dsn=settings.redis_dsn)
    with pytest.raises(ValueError):
        queue.submit(lambda: None)


async def test_arq_cancel_removes_queued_job(redis_queue):
    eid = f"exp-{uuid.uuid4().hex}"
    redis_queue.append(eid)
    queue = ArqTaskQueue(redis_dsn=settings.redis_dsn)
    queue.submit(lambda: None, experiment_id=eid)

    assert queue.cancel_task(eid) is True
    pool = await create_pool(RedisSettings.from_dsn(settings.redis_dsn))
    try:
        jobs = await pool.queued_jobs()
    finally:
        await pool.aclose(close_connection_pool=True)
    assert all(j.job_id != eid for j in jobs)

    assert queue.cancel_task("no-such-experiment") is False


async def test_arq_get_running_tasks(redis_queue):
    eid = f"exp-{uuid.uuid4().hex}"
    redis_queue.append(eid)
    pool = await create_pool(RedisSettings.from_dsn(settings.redis_dsn))
    try:
        await pool.set(in_progress_key_prefix + eid, "1", px=10000)
    finally:
        await pool.aclose(close_connection_pool=True)

    queue = ArqTaskQueue(redis_dsn=settings.redis_dsn)
    assert queue.get_running_tasks() == [eid]


async def test_arq_resubmit_clears_stale_finished_job_state(redis_queue):
    """A retried experiment must be enqueueable even when the previous job left
    ARQ state behind (retained result key, job key, cancellation marker)."""
    eid = f"exp-{uuid.uuid4().hex}"
    redis_queue.append(eid)
    pool = await create_pool(RedisSettings.from_dsn(settings.redis_dsn))
    try:
        # Simulate a finished job (ARQ retains the result for keep_result) and
        # a cancellation marker from an earlier cancelled run.
        await pool.set(result_key_prefix + eid, b"old-result", px=60000)
        await pool.set(job_key_prefix + eid, b"old-job", px=60000)
        await pool.zadd(abort_jobs_ss, {eid: 1})
    finally:
        await pool.aclose(close_connection_pool=True)

    queue = ArqTaskQueue(redis_dsn=settings.redis_dsn)
    queue.submit(lambda: None, experiment_id=eid)

    pool = await create_pool(RedisSettings.from_dsn(settings.redis_dsn))
    try:
        jobs = await pool.queued_jobs()
        assert any(j.job_id == eid for j in jobs)
        assert await pool.zscore(abort_jobs_ss, eid) is None
    finally:
        await pool.aclose(close_connection_pool=True)


# --- Worker task function / retry policy -------------------------------------


async def test_worker_task_retries_only_transient_error(monkeypatch):
    from app.worker import run_experiment_task

    async def _no_reset(_experiment_id):
        return None

    monkeypatch.setattr("app.worker._reset_stale_running", _no_reset)

    async def _transient(_experiment_id):
        raise RetryableTaskError("database is locked")

    monkeypatch.setattr("app.worker.run_experiment", _transient)
    with pytest.raises(Retry):
        await run_experiment_task({}, "e1")


async def test_reset_stale_running_converts_lock_to_retryable(monkeypatch):
    """A lock error while resetting a stale 'running' status must be retryable,
    not terminal: it happens before any billable provider call."""
    from app.worker import _reset_stale_running

    async def _locked(_operation):
        raise OperationalError("statement", {}, Exception("database is locked"))

    monkeypatch.setattr("app.worker.with_retry_on_lock", _locked)
    with pytest.raises(RetryableTaskError):
        await _reset_stale_running("e1")


async def test_worker_task_does_not_retry_quota_error(monkeypatch):
    from app.worker import run_experiment_task

    async def _no_reset(_experiment_id):
        return None

    monkeypatch.setattr("app.worker._reset_stale_running", _no_reset)

    async def _quota(_experiment_id):
        raise ProviderQuotaExhaustedError("free tier quota exhausted")

    monkeypatch.setattr("app.worker.run_experiment", _quota)
    with pytest.raises(ProviderQuotaExhaustedError):
        await run_experiment_task({}, "e1")


def test_worker_settings_wire_arq_configuration():
    from app.worker import WorkerSettings

    assert WorkerSettings.allow_abort_jobs is True
    assert any(f.name == "run_experiment" for f in WorkerSettings.functions)
    assert isinstance(WorkerSettings.redis_settings.database, int)


# --- Runner behaviour shared by both backends --------------------------------


async def test_run_experiment_skips_cancelled_experiment(client):
    from app.evaluation.runner import run_experiment
    from app.evaluation.task_records import create_task

    eid = _make_experiment(client)
    async with AsyncSessionLocal() as session:
        repo = ExperimentRepository(session)
        exp = await repo.get(eid)
        await repo.update(exp, {"status": "cancelled"})
        await session.commit()
    await create_task(eid)

    await run_experiment(eid)

    assert client.get(f"/api/v1/experiments/{eid}").json()["status"] == "cancelled"
    tasks = await _list_tasks(eid)
    assert tasks[-1].status == "cancelled"


# --- Distributed queue integration ------------------------------------------


async def test_worker_takeover_after_stale_running(client, redis_queue):
    """A job claimed by a dead worker (experiment stuck 'running') is reset to
    queued by the new worker and executed exactly once."""
    from app.evaluation.runner import run_experiment
    from app.evaluation.task_records import create_task, mark_running

    eid = _make_experiment(client)
    redis_queue.append(eid)
    async with AsyncSessionLocal() as session:
        repo = ExperimentRepository(session)
        exp = await repo.get(eid)
        await repo.update(exp, {"status": "running"})
        await session.commit()
    await create_task(eid)
    await mark_running(eid)

    queue = ArqTaskQueue(redis_dsn=settings.redis_dsn)
    queue.submit(lambda: run_experiment(eid), experiment_id=eid)

    worker = _make_worker()
    await worker.async_run()
    await worker.close()

    status = client.get(f"/api/v1/experiments/{eid}").json()["status"]
    assert status == "completed"
    tasks = await _list_tasks(eid)
    assert tasks[-1].status == "succeeded"


async def test_two_workers_consume_same_job_only_once(client, redis_queue):
    from app.evaluation.runner import run_experiment

    eid = _make_experiment(client)
    redis_queue.append(eid)
    queue = ArqTaskQueue(redis_dsn=settings.redis_dsn)
    queue.submit(lambda: run_experiment(eid), experiment_id=eid)

    worker_a = _make_worker()
    worker_b = _make_worker()
    await asyncio.gather(worker_a.async_run(), worker_b.async_run())
    await worker_a.close()
    await worker_b.close()

    async with AsyncSessionLocal() as session:
        rows = await ExperimentResultRepository(session).list_by_experiment(
            eid, limit=10_000
        )
    assert len(rows) == 2, f"expected 2 result rows, got {len(rows)}"
    status = client.get(f"/api/v1/experiments/{eid}").json()["status"]
    assert status == "completed"


async def test_worker_restart_runs_job_left_in_queue(client, redis_queue):
    """Enqueue a job, kill the polling worker while it is still queued, then a
    fresh worker must pick the job up and complete it."""
    from app.evaluation.task_records import create_task

    eid = _make_experiment(client)
    redis_queue.append(eid)
    pool = await create_pool(RedisSettings.from_dsn(settings.redis_dsn))
    try:
        enqueued = await pool.enqueue_job(
            "run_experiment", eid, _job_id=eid, _defer_by=1
        )
        assert enqueued is not None
    finally:
        await pool.aclose(close_connection_pool=True)
    await create_task(eid)

    # Worker A polls while the job is deferred, then "dies" (main loop killed).
    worker_a = _make_worker(burst=False)
    run_a = asyncio.create_task(worker_a.async_run())
    await asyncio.sleep(0.3)
    worker_a.main_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await run_a
    await worker_a.close()

    await asyncio.sleep(1.0)
    worker_b = _make_worker()
    await worker_b.async_run()
    await worker_b.close()

    status = client.get(f"/api/v1/experiments/{eid}").json()["status"]
    assert status == "completed"
    tasks = await _list_tasks(eid)
    assert tasks[-1].status == "succeeded"


def test_recovery_skipped_when_arq_backend(client, monkeypatch):
    """With ARQ, startup recovery must not fail queued/running experiments:
    the workers own the run lifecycle."""
    from app.main import _recover_stale_experiments

    eid_running = _make_experiment(client)
    eid_queued = _make_experiment(client)

    async def _prep():
        async with AsyncSessionLocal() as session:
            repo = ExperimentRepository(session)
            for eid, status in ((eid_running, "running"), (eid_queued, "queued")):
                exp = await repo.get(eid)
                await repo.update(exp, {"status": status})
            await session.commit()

    asyncio.run(_prep())
    monkeypatch.setattr(settings, "task_queue_backend", "arq")
    asyncio.run(_recover_stale_experiments())

    assert client.get(f"/api/v1/experiments/{eid_running}").json()["status"] == "running"
    assert client.get(f"/api/v1/experiments/{eid_queued}").json()["status"] == "queued"


def test_run_marks_failed_when_submit_raises(client, monkeypatch):
    """If enqueueing fails, the experiment must not stay 'queued' forever."""
    from app.evaluation.task_queue import task_queue

    eid = _make_experiment(client)

    def _boom(*_args, **_kwargs):
        raise RuntimeError("redis down")

    monkeypatch.setattr(task_queue, "submit", _boom)
    with pytest.raises(RuntimeError):
        client.post(f"/api/v1/experiments/{eid}/run")

    assert client.get(f"/api/v1/experiments/{eid}").json()["status"] == "failed"
