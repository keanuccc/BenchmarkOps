"""Unit tests for per-cell progress reporting (optimization C).

The runner must maintain `cells_done` (rows scored successfully) and
`cells_error` (rows whose provider call failed) and persist them alongside
`progress` / `rows_total` so the frontend can render a three-segment bar
(scored vs failed vs total) instead of a single opaque counter.
"""
from __future__ import annotations

import asyncio

import pytest

from app.core.database import AsyncSessionLocal
from app.evaluation.runner import _persist_progress, run_experiment
from app.models.experiment import Experiment, ExperimentResult
from app.providers.base import CompletionRequest, CompletionResult, LLMProvider
from app.repositories.experiment import (
    ExperimentRepository,
    ExperimentResultRepository,
)


class _PartialProvider(LLMProvider):
    """Row 0 succeeds; every later row raises (simulates provider failure)."""

    name = "partial"

    async def complete(self, request: CompletionRequest) -> CompletionResult:
        # The fixed dataset has questions q1/q2/q3; fail anything not exactly "q1?".
        if "q1?" in str(request.messages[-1].content):
            return CompletionResult(
                text="yes", prompt_tokens=1, completion_tokens=1, latency_ms=5
            )
        raise RuntimeError("provider exploded")


@pytest.fixture()
def patched_partial(monkeypatch):
    monkeypatch.setattr(
        "app.evaluation.runner.get_provider", lambda name=None: _PartialProvider()
    )
    yield


def _build_experiment(client):
    assert client.post("/api/v1/models/seed").status_code in (200, 201)
    models = client.get("/api/v1/models/").json()["items"]
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
    return exp["id"]


def test_runner_reports_cells_done_and_error(client, patched_partial):
    """A partial run of 3 rows (1 ok, 2 fail) must persist cells_done=1,
    cells_error=2, progress=3, rows_total=3, and end as 'partial'."""
    eid = _build_experiment(client)
    asyncio.run(run_experiment(eid))

    async def _inspect():
        async with AsyncSessionLocal() as session:
            exp = await ExperimentRepository(session).get(eid)
            results = await ExperimentResultRepository(session).list_by_experiment(
                eid, limit=10_000_000
            )
            return exp, results

    exp, results = asyncio.run(_inspect())
    assert exp.status == "partial", exp.error
    assert exp.progress == 3
    assert exp.rows_total == 3
    assert exp.cells_done == 1
    assert exp.cells_error == 2
    assert exp.metrics["dataset_rows_total"] == 3
    assert exp.metrics["coverage"] == pytest.approx(1 / 3, abs=1e-4)
    assert exp.metrics["failure_rate"] == pytest.approx(2 / 3, abs=1e-4)
    assert len(results) == 3
    ok = [r for r in results if not r.error]
    bad = [r for r in results if r.error]
    assert len(ok) == 1 and len(bad) == 2
    assert all("provider exploded" in (r.error or "") for r in bad)


def test_runner_all_success_counts_only_cells_done(client, patched_partial, monkeypatch):
    """With a fully-successful provider, cells_done == rows_total and
    cells_error == 0 — the bar reads 100% scored, nothing failed."""

    class _OkProvider(LLMProvider):
        name = "ok"

        async def complete(self, request: CompletionRequest) -> CompletionResult:
            return CompletionResult(
                text="yes", prompt_tokens=1, completion_tokens=1, latency_ms=5
            )

    monkeypatch.setattr("app.evaluation.runner.get_provider", lambda name=None: _OkProvider())
    eid = _build_experiment(client)
    asyncio.run(run_experiment(eid))

    async def _inspect():
        async with AsyncSessionLocal() as session:
            return await ExperimentRepository(session).get(eid)

    exp = asyncio.run(_inspect())
    assert exp.status == "completed", exp.error
    assert exp.cells_done == 3
    assert exp.cells_error == 0


def test_persist_progress_merges_live_metrics(client, patched_partial):
    """Mid-run progress writes must merge live metrics (avg_ms_per_row) into the
    metrics blob so the UI's ETA is populated before the run finishes."""
    eid = _build_experiment(client)

    async def _mark_running():
        async with AsyncSessionLocal() as session:
            repo = ExperimentRepository(session)
            exp = await repo.get(eid)
            await repo.update(exp, {"status": "running"})
            await session.commit()

    asyncio.run(_mark_running())

    asyncio.run(
        _persist_progress(
            eid,
            processed=1,
            rows_total=3,
            cells_done=1,
            cells_error=0,
            metrics_update={"avg_ms_per_row": 12.5},
        )
    )

    async def _inspect():
        async with AsyncSessionLocal() as session:
            return await ExperimentRepository(session).get(eid)

    exp = asyncio.run(_inspect())
    assert exp.progress == 1
    assert exp.cells_done == 1
    assert exp.metrics.get("avg_ms_per_row") == 12.5
