"""Regression test: _persist_progress must accept cells_done/cells_error as
keyword-only args (matching its signature). A positional mismatch here
silently broke progress persistence for any run with >= _PROGRESS_EVERY
rows, surfacing only as a TypeError caught but not surfaced by the
small 3-row tests. We exercise the real runner over a 60-row dataset
with a slow provider so the intermediate 'running' state (progress
0 -> 50 -> 60, cells_done tracked) is observable and persisted."""

from __future__ import annotations

import asyncio

import pytest

from app.core.database import AsyncSessionLocal
from app.evaluation.runner import run_experiment, _PROGRESS_EVERY
from app.models.experiment import Experiment
from app.providers.base import CompletionRequest, CompletionResult, LLMProvider
from app.repositories.experiment import ExperimentRepository

import sqlalchemy as sa


class _SlowOkProvider(LLMProvider):
    """Every row succeeds after a short sleep so the run stays 'running' long
    enough to observe intermediate progress persistence."""

    name = "slow_ok"

    async def complete(self, request: CompletionRequest) -> CompletionResult:
        await asyncio.sleep(0.05)
        return CompletionResult(text="yes", prompt_tokens=1, completion_tokens=1, latency_ms=50)


@pytest.fixture()
def patched_slow(monkeypatch):
    monkeypatch.setattr(
        "app.evaluation.runner.get_provider", lambda _name=None: _SlowOkProvider()
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
    n = _PROGRESS_EVERY * 2 + 10  # > 2 * _PROGRESS_EVERY so >=2 progress writes
    rows = "\n".join(
        f'{{"question":"q{i}?","answer":"yes"}}' for i in range(n)
    ).encode()
    ds = client.post(
        "/api/v1/datasets/upload",
        data={"project_id": pid, "name": "DS", "format": "jsonl"},
        files={"file": ("d.jsonl", rows, "application/x-ndjson")},
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


async def _poll_intermediate(eid: str) -> list[tuple]:
    """Drive the run and capture the (status, progress, cells_done) tuples seen
    while it is in flight."""
    task = asyncio.create_task(run_experiment(eid))
    seen: list[tuple] = []
    last = None
    for _ in range(80):
        async with AsyncSessionLocal() as session:
            row = (
                await session.execute(
                    sa.text(
                        "SELECT status, progress, cells_done, cells_error, rows_total "
                        "FROM experiments WHERE id=:i"
                    ),
                    {"i": eid},
                )
            ).fetchone()
            tup = (row[0], row[1], row[2], row[3], row[4])
        seen.append(tup)
        if tup[0] in ("completed", "failed", "partial"):
            break
        await asyncio.sleep(0.1)
    await task
    return seen


def test_progress_persists_during_run(client, patched_slow):
    """A multi-row run must persist increasing progress + cells_done while 'running',
    proving the frontend progress bar is driven by real intermediate data
    (not just the final completed row)."""
    eid = _build_experiment(client)
    seen = asyncio.run(_poll_intermediate(eid))

    running_states = [s for s in seen if s[0] == "running"]
    assert running_states, "never observed an intermediate 'running' state"

    # progress must advance past the first _PROGRESS_EVERY checkpoint.
    max_progress = max(s[1] for s in seen)
    assert max_progress >= _PROGRESS_EVERY, (
        f"progress never reached a persist checkpoint: {max_progress}"
    )

    # cells_done must track progress (every row succeeded here).
    advanced = [
        s for s in running_states if s[1] and s[2] == s[1]
    ]
    assert advanced, "cells_done not kept in sync with progress during run"

    async def _final():
        async with AsyncSessionLocal() as session:
            return await ExperimentRepository(session).get(eid)

    exp = asyncio.run(_final())
    assert exp.status == "completed", exp.error
    assert exp.cells_done == exp.progress == exp.rows_total
    assert exp.cells_error == 0
