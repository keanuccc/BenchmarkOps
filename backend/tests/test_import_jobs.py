"""Async dataset import jobs: lifecycle, idempotency, row-level errors."""
from __future__ import annotations

import time

import pytest


def _wait_job(client, job_id: str, timeout: float = 10.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = client.get(f"/api/v1/datasets/imports/{job_id}").json()
        if job["status"] in ("succeeded", "failed", "cancelled"):
            return job
        time.sleep(0.05)
    raise AssertionError(f"import job {job_id} did not finish in {timeout}s")


def _start_import(
    client,
    pid: str,
    name: str,
    rows: bytes,
    *,
    idempotency_key: str | None = None,
    extra: dict | None = None,
) -> dict:
    data = {"project_id": pid, "name": name, "format": "jsonl"}
    if idempotency_key:
        data["idempotency_key"] = idempotency_key
    if extra:
        data.update(extra)
    r = client.post(
        "/api/v1/datasets/import",
        data=data,
        files={"file": (f"{name}.jsonl", rows, "application/x-ndjson")},
    )
    assert r.status_code == 202, r.text
    return r.json()


def test_import_creates_dataset_and_reports_job(client) -> None:
    pid = client.post("/api/v1/projects/", json={"name": "ImportBasic"}).json()["id"]
    job = _start_import(
        client, pid, "basic", b'{"question":"q1","answer":"a1"}\n'
    )

    finished = _wait_job(client, job["id"])
    assert finished["status"] == "succeeded"
    assert finished["total_rows"] == 1
    assert finished["dataset_id"]

    ds = client.get(f"/api/v1/datasets/{finished['dataset_id']}").json()
    assert ds["name"] == "basic"
    assert ds["version"] == 1
    assert finished["content_hash"] == ds["content_hash"]


def test_import_idempotency_key_reuses_job(client) -> None:
    pid = client.post("/api/v1/projects/", json={"name": "ImportIdem"}).json()["id"]
    first = _start_import(
        client,
        pid,
        "idem",
        b'{"question":"q1","answer":"a1"}\n',
        idempotency_key="same-key",
    )
    second = _start_import(
        client,
        pid,
        "idem",
        b'{"question":"q1","answer":"a1"}\n',
        idempotency_key="same-key",
    )

    assert first["id"] == second["id"]
    _wait_job(client, first["id"])
    jobs = client.get(f"/api/v1/datasets/imports?project_id={pid}").json()
    assert len(jobs["items"]) == 1


def test_import_records_row_level_errors(client) -> None:
    pid = client.post("/api/v1/projects/", json={"name": "ImportErrors"}).json()["id"]
    job = _start_import(
        client,
        pid,
        "bad",
        b'{"answer":"a1"}\n{"answer":"a2"}\n',
        extra={"input_fields": '["question"]', "required_fields": '["question"]'},
    )

    finished = _wait_job(client, job["id"])
    assert finished["status"] == "failed"
    assert "question" in finished["error"]
    assert finished["error_rows"] and "question" in finished["error_rows"][0]["message"]


def test_import_duplicate_name_fails_job(client) -> None:
    pid = client.post("/api/v1/projects/", json={"name": "ImportDup"}).json()["id"]
    first = _start_import(
        client, pid, "dup", b'{"question":"q1","answer":"a1"}\n'
    )
    _wait_job(client, first["id"])
    second = _start_import(
        client, pid, "dup", b'{"question":"q2","answer":"a2"}\n'
    )
    finished = _wait_job(client, second["id"])
    assert finished["status"] == "failed"
    assert "already exists" in finished["error"]


def test_import_job_missing_returns_404(client) -> None:
    assert client.get("/api/v1/datasets/imports/does-not-exist").status_code == 404


@pytest.mark.asyncio
async def test_create_from_upload_reports_row_progress() -> None:
    from app.core.database import AsyncSessionLocal
    from app.services.dataset_service import DatasetService

    calls: list[tuple[int, int]] = []

    async def on_progress(done: int, total: int) -> None:
        calls.append((done, total))

    async with AsyncSessionLocal() as session:
        service = DatasetService(session)
        dataset = await service.create_from_upload(
            project_id="progress-p",
            name="progress",
            description=None,
            tags=None,
            fmt="jsonl",
            raw_bytes=b'{"question":"q1","answer":"a1"}\n{"question":"q2","answer":"a2"}\n',
            on_progress=on_progress,
        )
        await service.delete(dataset.id)
        await session.commit()

    assert calls, "progress callback must be invoked"
    assert calls[0] == (0, 2)
    assert calls[-1] == (2, 2)
    assert [done for done, _ in calls] == sorted(done for done, _ in calls)
