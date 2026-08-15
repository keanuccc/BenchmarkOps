"""Runner must persist scored rows incrementally (bounded memory) and honour
an in-memory cancellation signal without a per-row DB round trip."""
from __future__ import annotations

import asyncio

import pytest

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.evaluation.cancellation import clear_cancelled, request_cancel
from app.evaluation.runner import run_experiment
from app.providers.base import CompletionRequest, CompletionResult, LLMProvider
from app.repositories.experiment import ExperimentRepository, ExperimentResultRepository


class _SlowOkProvider(LLMProvider):
    """Every row succeeds after a short sleep so the run stays 'running' long
    enough to observe intermediate persistence / cancellation."""

    name = "slow_ok"

    async def complete(self, request: CompletionRequest) -> CompletionResult:
        await asyncio.sleep(0.03)
        return CompletionResult(text="yes", prompt_tokens=1, completion_tokens=1, latency_ms=30)


@pytest.fixture()
def patched_slow(monkeypatch):
    monkeypatch.setattr(
        "app.evaluation.runner.get_provider", lambda _name=None: _SlowOkProvider()
    )
    yield


def _build_experiment(client, n: int = 10) -> str:
    assert client.post("/api/v1/models/seed").status_code in (200, 201)
    models = client.get("/api/v1/models/").json()["items"]
    model_pk = models[0]["id"]
    pid = client.post("/api/v1/projects/", json={"name": "INC"}).json()["id"]
    b = client.post(
        "/api/v1/benchmarks/",
        json={"project_id": pid, "name": "QA", "type": "qa", "metric": "exact_match_ci"},
    ).json()
    pr = client.post(
        "/api/v1/prompts/", json={"project_id": pid, "name": "P", "template": "{question}"}
    ).json()
    rows = "\n".join(f'{{"question":"q{i}?","answer":"yes"}}' for i in range(n)).encode()
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


async def _experiment_state(eid: str):
    async with AsyncSessionLocal() as session:
        exp = await ExperimentRepository(session).get(eid)
        rows = await ExperimentResultRepository(session).list_by_experiment(
            eid, limit=100_000
        )
    return exp, rows


def test_results_persisted_incrementally_before_run_finishes(
    client, patched_slow, monkeypatch
):
    """With a small result batch size, scored rows must appear in the DB while
    the experiment is still 'running' — proving the runner no longer buffers
    every row in memory until the end."""
    monkeypatch.setattr(settings, "eval_result_batch_size", 3)
    eid = _build_experiment(client, n=12)

    async def _drive():
        task = asyncio.create_task(run_experiment(eid))
        saw_intermediate = False
        for _ in range(300):
            exp, rows = await _experiment_state(eid)
            if exp is not None and exp.status == "running" and len(rows) >= 3:
                saw_intermediate = True
                break
            await asyncio.sleep(0.02)
        assert saw_intermediate, "no intermediate result batch observed while running"
        await asyncio.wait_for(task, timeout=30)
        exp, rows = await _experiment_state(eid)
        return exp, rows

    exp, rows = asyncio.run(_drive())
    assert exp is not None and exp.status == "completed"
    assert len(rows) == 12


def test_in_memory_cancel_stops_run_and_cleans_results(
    client, patched_slow, monkeypatch
):
    """request_cancel() must stop the runner at the next row boundary (no
    per-row DB poll needed) and must not leave partial result rows behind."""
    monkeypatch.setattr(settings, "eval_result_batch_size", 3)
    eid = _build_experiment(client, n=20)
    clear_cancelled(eid)

    async def _drive():
        task = asyncio.create_task(run_experiment(eid))
        for _ in range(200):
            exp, _rows = await _experiment_state(eid)
            if exp is not None and exp.status == "running":
                break
            await asyncio.sleep(0.02)
        request_cancel(eid)
        await asyncio.wait_for(task, timeout=10)
        exp, rows = await _experiment_state(eid)
        return exp, rows

    exp, rows = asyncio.run(_drive())
    assert exp is not None and exp.status == "cancelled"
    assert len(rows) == 0, "cancelled run must not leave partial result rows"


def test_versioned_dataset_uses_pinned_version_for_totals(client, patched_slow):
    """The runner must count rows for the experiment's pinned dataset version,
    not every row ever stored across all versions of the dataset."""
    assert client.post("/api/v1/models/seed").status_code in (200, 201)
    model_pk = client.get("/api/v1/models/").json()["items"][0]["id"]
    pid = client.post("/api/v1/projects/", json={"name": "VER"}).json()["id"]
    benchmark = client.post(
        "/api/v1/benchmarks/",
        json={"project_id": pid, "name": "QA", "type": "qa", "metric": "exact_match_ci"},
    ).json()
    prompt = client.post(
        "/api/v1/prompts/",
        json={"project_id": pid, "name": "P", "template": "{question}"},
    ).json()

    def _rows(n: int) -> bytes:
        return "\n".join(
            f'{{"question":"q{i}?","answer":"yes"}}' for i in range(n)
        ).encode()

    dataset = client.post(
        "/api/v1/datasets/upload",
        data={"project_id": pid, "name": "DS", "format": "jsonl"},
        files={"file": ("v1.jsonl", _rows(2), "application/x-ndjson")},
    ).json()

    version = client.post(
        f"/api/v1/datasets/{dataset['id']}/versions",
        data={"mode": "append", "format": "jsonl"},
        files={"file": ("v2.jsonl", _rows(2), "application/x-ndjson")},
    ).json()
    assert version["version"] == 2

    experiment = client.post(
        "/api/v1/experiments/",
        json={
            "project_id": pid,
            "name": "E",
            "dataset_id": dataset["id"],
            "benchmark_id": benchmark["id"],
            "prompt_id": prompt["id"],
            "model_id": model_pk,
        },
    ).json()
    assert experiment["dataset_version"] == 2

    asyncio.run(run_experiment(experiment["id"]))
    fetched = client.get(f"/api/v1/experiments/{experiment['id']}").json()

    assert fetched["status"] == "completed"
    assert fetched["rows_total"] == 4
    assert fetched["metrics"]["dataset_rows_total"] == 4
    assert fetched["metrics"]["rows_scored"] == 4
    assert fetched["metrics"]["coverage"] == 1.0
