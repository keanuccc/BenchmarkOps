"""Dataset versioning: replace/append/activate, experiment snapshots, cleanup."""
from __future__ import annotations

from app.core.config import settings


def _upload(client, pid: str, name: str, rows: bytes, fmt: str = "jsonl") -> dict:
    return client.post(
        "/api/v1/datasets/upload",
        data={"project_id": pid, "name": name, "format": fmt},
        files={"file": (f"{name}.{fmt}", rows, "application/x-ndjson")},
    ).json()


def _version_file(client, dataset_id: str, rows: bytes, mode: str = "replace") -> dict:
    return client.post(
        f"/api/v1/datasets/{dataset_id}/versions",
        data={"mode": mode},
        files={"file": ("v.jsonl", rows, "application/x-ndjson")},
    ).json()


def _project(client, name: str) -> str:
    return client.post("/api/v1/projects/", json={"name": name}).json()["id"]


def test_upload_creates_version_1(client) -> None:
    pid = _project(client, "VersionsBase")
    ds = _upload(client, pid, "base", b'{"question":"q1","answer":"a1"}\n')

    assert ds["version"] == 1
    assert ds["current_version_id"] is not None
    assert ds["row_count"] == 1

    versions = client.get(f"/api/v1/datasets/{ds['id']}/versions").json()
    assert len(versions) == 1
    assert versions[0]["version"] == 1
    assert versions[0]["row_count"] == 1
    assert versions[0]["content_hash"] == ds["content_hash"]


def test_replace_creates_new_current_version(client) -> None:
    pid = _project(client, "VersionsReplace")
    ds = _upload(client, pid, "replace", b'{"question":"q1","answer":"a1"}\n{"question":"q2","answer":"a2"}\n')

    v2 = _version_file(client, ds["id"], b'{"question":"q3","answer":"a3"}\n')
    assert v2["version"] == 2
    assert v2["row_count"] == 1

    current = client.get(f"/api/v1/datasets/{ds['id']}").json()
    assert current["version"] == 2
    assert current["row_count"] == 1
    assert current["current_version_id"] == v2["id"]

    preview = client.get(f"/api/v1/datasets/{ds['id']}/preview").json()
    assert [r["input"]["question"] for r in preview] == ["q3"]

    old_preview = client.get(f"/api/v1/datasets/{ds['id']}/preview?version=1").json()
    assert [r["input"]["question"] for r in old_preview] == ["q1", "q2"]


def test_append_keeps_old_rows_and_continues_idx(client) -> None:
    pid = _project(client, "VersionsAppend")
    ds = _upload(client, pid, "append", b'{"question":"q1","answer":"a1"}\n')

    v2 = _version_file(client, ds["id"], b'{"question":"q2","answer":"a2"}\n', mode="append")
    assert v2["version"] == 2
    assert v2["row_count"] == 2

    current = client.get(f"/api/v1/datasets/{ds['id']}").json()
    assert current["version"] == 2
    preview = client.get(f"/api/v1/datasets/{ds['id']}/preview").json()
    assert [(r["idx"], r["input"]["question"]) for r in preview] == [(0, "q1"), (1, "q2")]


def test_activate_rolls_back_to_previous_version(client) -> None:
    pid = _project(client, "VersionsActivate")
    ds = _upload(client, pid, "rollback", b'{"question":"q1","answer":"a1"}\n')
    _version_file(client, ds["id"], b'{"question":"q2","answer":"a2"}\n')

    rolled = client.post(f"/api/v1/datasets/{ds['id']}/versions/1/activate").json()
    assert rolled["version"] == 1
    assert rolled["row_count"] == 1

    preview = client.get(f"/api/v1/datasets/{ds['id']}/preview").json()
    assert [r["input"]["question"] for r in preview] == ["q1"]


def test_experiment_snapshots_dataset_version(client) -> None:
    pid = _project(client, "VersionsExp")
    ds = _upload(client, pid, "snapshot", b'{"question":"q1","answer":"a1"}\n')
    bench = client.post(
        "/api/v1/benchmarks/",
        json={"project_id": pid, "name": "QA", "type": "qa", "metric": "exact_match_ci"},
    ).json()
    prompt = client.post(
        "/api/v1/prompts/",
        json={"project_id": pid, "name": "P", "template": "{question}"},
    ).json()
    client.post("/api/v1/models/seed")
    model_id = client.get("/api/v1/models/").json()["items"][0]["id"]

    exp = client.post(
        "/api/v1/experiments/",
        json={
            "project_id": pid,
            "name": "E",
            "dataset_id": ds["id"],
            "benchmark_id": bench["id"],
            "prompt_id": prompt["id"],
            "model_id": model_id,
        },
    ).json()
    assert exp["dataset_version"] == 1

    _version_file(client, ds["id"], b'{"question":"q2","answer":"a2"}\n')
    fetched = client.get(f"/api/v1/experiments/{exp['id']}").json()
    assert fetched["dataset_version"] == 1


def test_version_upload_enforces_row_cap(client, monkeypatch) -> None:
    monkeypatch.setattr(settings, "max_dataset_rows", 1)
    pid = _project(client, "VersionsCap")
    ds = _upload(client, pid, "cap", b'{"question":"q1","answer":"a1"}\n')

    r = client.post(
        f"/api/v1/datasets/{ds['id']}/versions",
        data={"mode": "replace"},
        files={"file": ("v.jsonl", b'{"question":"q1","answer":"a1"}\n{"question":"q2","answer":"a2"}\n', "application/x-ndjson")},
    )
    assert r.status_code == 422
    assert "rows exceeds limit" in r.json()["error"]["message"]


def test_delete_dataset_removes_versions(client) -> None:
    pid = _project(client, "VersionsDelete")
    ds = _upload(client, pid, "cleanup", b'{"question":"q1","answer":"a1"}\n')
    _version_file(client, ds["id"], b'{"question":"q2","answer":"a2"}\n')

    assert client.delete(f"/api/v1/datasets/{ds['id']}").status_code == 204
    assert client.get(f"/api/v1/datasets/{ds['id']}/versions").status_code == 404


def test_validate_uses_version_row_count(client) -> None:
    pid = _project(client, "VersionsValidate")
    ds = _upload(client, pid, "vcount", b'{"question":"q1","answer":"a1"}\n{"question":"q2","answer":"a2"}\n')
    _version_file(client, ds["id"], b'{"question":"q3","answer":"a3"}\n')

    r = client.post(f"/api/v1/datasets/{ds['id']}/validate?version=1")
    assert r.status_code == 200
    issues = r.json()["issues"]
    assert not any("Row count mismatch" in issue for issue in issues)
