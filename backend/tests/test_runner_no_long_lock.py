"""Runner must not hold a long DB write lock across network calls.

The key invariant: during run_experiment the compute phase (provider.complete +
scoring) must not keep a writable transaction open. A second independent session
must be able to write a *different* table concurrently without being blocked for
the full busy_timeout. We assert: the run completes correctly AND a concurrent
write to an unrelated row succeeds quickly.
"""
from __future__ import annotations

import asyncio
import time

import pytest

from app.core.database import AsyncSessionLocal
from app.evaluation.runner import run_experiment
from app.models.project import Project
from app.providers.base import CompletionRequest, CompletionResult, LLMProvider
from app.repositories.experiment import ExperimentRepository, ExperimentResultRepository


class _FixedProvider(LLMProvider):
    """Deterministic fake provider: answers 'yes' for every prompt."""

    name = "fixed"

    async def complete(self, request: CompletionRequest) -> CompletionResult:
        return CompletionResult(
            text="yes",
            prompt_tokens=1,
            completion_tokens=1,
            latency_ms=10,
        )


@pytest.fixture()
def patched_provider(monkeypatch):
    monkeypatch.setattr(
        "app.evaluation.runner.get_provider", lambda: _FixedProvider()
    )
    yield


def _build_experiment(client):
    assert client.post("/api/v1/models/seed").status_code in (200, 201)
    models = client.get("/api/v1/models/").json()
    model_pk = models[0]["id"]
    pid = client.post("/api/v1/projects/", json={"name": "NL"}).json()["id"]
    b = client.post(
        "/api/v1/benchmarks/",
        json={"project_id": pid, "name": "QA", "type": "qa", "metric": "exact_match_ci"},
    ).json()
    pr = client.post(
        "/api/v1/prompts/",
        json={"project_id": pid, "name": "P", "template": "{question}"},
    ).json()
    jsonl = b'{"question":"q1?","answer":"yes"}\n{"question":"q2?","answer":"yes"}\n{"question":"q3?","answer":"yes"}\n'
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
    return exp["id"], pid


async def _concurrent_writer(project_id: str) -> float:
    """Open an independent short session and UPDATE an unrelated row (the owning
    project) while the run is computing. Returns how long the write took, to
    confirm it was not blocked long by a held lock."""
    start = time.perf_counter()
    async with AsyncSessionLocal() as session:
        proj = await session.get(Project, project_id)
        proj.name = "concurrent-update-ok"
        await session.commit()
    return time.perf_counter() - start


async def _drive(eid: str, project_id: str):
    run_task = asyncio.create_task(run_experiment(eid))
    write_dur = await _concurrent_writer(project_id)
    await run_task
    return write_dur


def test_runner_no_long_lock(client, patched_provider):
    eid, pid = _build_experiment(client)

    write_dur = asyncio.run(_drive(eid, pid))
    # With busy_timeout lowered to 5s, a concurrent write that must wait should
    # still win quickly; the key invariant is the run terminates and the DB
    # reflects success, with no long 'database is locked' wait.
    assert write_dur < 5.0, f"concurrent write blocked too long: {write_dur}s"

    async def _inspect():
        async with AsyncSessionLocal() as session:
            exp = await ExperimentRepository(session).get(eid)
            results = await ExperimentResultRepository(session).list_by_experiment(
                eid, limit=10_000_000
            )
            return exp, results

    exp, results = asyncio.run(_inspect())
    assert exp is not None
    assert exp.status == "completed", exp.error
    assert exp.error is None
    assert len(results) == 3
    # All answers are 'yes' and expected 'yes' -> exact match, accuracy 1.0.
    assert exp.metrics.get("accuracy") == 1.0
    assert exp.metrics.get("rows_total") == 3


def test_concurrent_runs_do_not_double_execute(client, monkeypatch):
    """P0 regression: two concurrent run_experiment() on the SAME experiment must
    not both execute. The 'running' CAS is committed in the load phase, so the
    loser bails and results are written exactly once (never doubled).

    Uses a slow provider so both runners overlap in time, maximizing the race.
    """
    # Slow provider: each row takes ~50ms, so a 3-row run stays 'running' long
    # enough for a second runner to attempt the CAS mid-flight.
    class _SlowProvider(LLMProvider):
        name = "slow"

        async def complete(self, request: CompletionRequest) -> CompletionResult:
            await asyncio.sleep(0.05)
            return CompletionResult(text="yes", prompt_tokens=1, completion_tokens=1, latency_ms=50)

    monkeypatch.setattr("app.evaluation.runner.get_provider", lambda: _SlowProvider())

    eid, _ = _build_experiment(client)

    async def _race():
        # Fire both runners concurrently on the same experiment id.
        await asyncio.gather(run_experiment(eid), run_experiment(eid))

    asyncio.run(_race())

    async def _inspect():
        async with AsyncSessionLocal() as session:
            exp = await ExperimentRepository(session).get(eid)
            results = await ExperimentResultRepository(session).list_by_experiment(
                eid, limit=10_000_000
            )
            return exp, results

    exp, results = asyncio.run(_inspect())
    assert exp is not None
    assert exp.status == "completed", exp.error
    # The dataset has exactly 3 rows. Exactly 3 result rows must exist — a
    # double-run would produce 6 (or a mix from two overlapping persists).
    assert len(results) == 3, f"double-run wrote {len(results)} rows (expected 3)"
    assert exp.metrics.get("rows_total") == 3


def test_runner_row_provider_errors_become_partial(client, patched_provider, monkeypatch):
    """Per-row provider failures are tolerated (partial), each row records error —
    they are NOT silently swallowed and they do NOT crash the whole run."""
    eid, _ = _build_experiment(client)

    def _boom_factory():
        class _Boom(LLMProvider):
            name = "boom"

            async def complete(self, request: CompletionRequest) -> CompletionResult:
                raise RuntimeError("provider exploded")

        return _Boom()

    monkeypatch.setattr("app.evaluation.runner.get_provider", _boom_factory)

    asyncio.run(run_experiment(eid))

    async def _inspect():
        async with AsyncSessionLocal() as session:
            exp = await ExperimentRepository(session).get(eid)
            results = await ExperimentResultRepository(session).list_by_experiment(
                eid, limit=10_000_000
            )
            return exp, results

    exp, results = asyncio.run(_inspect())
    # Tolerated per-row errors -> partial, with every row carrying the error.
    assert exp.status == "partial"
    assert len(results) == 3
    assert all(r.error and "provider exploded" in r.error for r in results)


def test_runner_marks_failed_when_persist_errors(client, patched_provider, monkeypatch):
    """A hard failure during the persist phase must surface as 'failed', not be
    swallowed by the task-queue guard."""
    eid, _ = _build_experiment(client)

    from app.repositories.experiment import ExperimentResultRepository as _ERR

    async def _boom_delete(self, experiment_id):  # noqa: ANN001
        raise RuntimeError("disk vanished")

    monkeypatch.setattr(_ERR, "delete_by_experiment", _boom_delete)

    asyncio.run(run_experiment(eid))

    async def _inspect():
        async with AsyncSessionLocal() as session:
            return await ExperimentRepository(session).get(eid)

    exp = asyncio.run(_inspect())
    assert exp.status == "failed"
    assert exp.error and "disk vanished" in exp.error
