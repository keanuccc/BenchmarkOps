"""Dataset audit events and sensitive-field preview redaction."""
from __future__ import annotations

import time


def _project(client, name: str) -> str:
    return client.post("/api/v1/projects/", json={"name": name}).json()["id"]


def _upload(client, pid: str, name: str, rows: bytes, extra: dict | None = None) -> dict:
    data = {"project_id": pid, "name": name, "format": "jsonl"}
    if extra:
        data.update(extra)
    r = client.post(
        "/api/v1/datasets/upload",
        data=data,
        files={"file": (f"{name}.jsonl", rows, "application/x-ndjson")},
    )
    assert r.status_code == 200, r.text
    return r.json()


def test_audit_events_recorded_for_dataset_actions(client) -> None:
    pid = _project(client, "AuditActions")
    ds = _upload(client, pid, "audited", b'{"question":"q","answer":"a"}\n')

    client.post(
        f"/api/v1/datasets/{ds['id']}/versions",
        data={"mode": "replace"},
        files={"file": ("v.jsonl", b'{"question":"q2","answer":"a2"}\n', "application/x-ndjson")},
    )
    client.post(f"/api/v1/datasets/{ds['id']}/versions/1/activate")
    client.post(f"/api/v1/datasets/{ds['id']}/archive")

    events = client.get(f"/api/v1/datasets/{ds['id']}/audit").json()
    actions = [e["action"] for e in events]
    assert "create" in actions
    assert "version.create" in actions
    assert "version.activate" in actions
    assert "archive" in actions


def test_sensitive_fields_redacted_in_previews(client) -> None:
    pid = _project(client, "Sensitive")
    ds = _upload(
        client,
        pid,
        "private",
        b'{"question":"q","email":"a@b.com","answer":"a"}\n',
        extra={"sensitive_fields": '["email"]'},
    )

    raw = client.get(f"/api/v1/datasets/{ds['id']}/preview/raw").json()
    assert raw["rows"][0]["email"] == "[REDACTED]"
    assert raw["rows"][0]["question"] == "q"

    rows = client.get(f"/api/v1/datasets/{ds['id']}/preview").json()
    assert rows[0]["input"]["email"] == "[REDACTED]"
    assert rows[0]["input"]["question"] == "q"


def test_import_job_records_audit_event(client) -> None:
    pid = _project(client, "AuditImport")
    r = client.post(
        "/api/v1/datasets/import",
        data={"project_id": pid, "name": "imported", "format": "jsonl"},
        files={"file": ("imported.jsonl", b'{"question":"q","answer":"a"}\n', "application/x-ndjson")},
    )
    assert r.status_code == 202
    deadline = time.monotonic() + 10
    ds_id = None
    while time.monotonic() < deadline:
        job = client.get(f"/api/v1/datasets/imports/{r.json()['id']}").json()
        if job["status"] == "succeeded":
            ds_id = job["dataset_id"]
            break
        time.sleep(0.05)
    assert ds_id is not None

    events = client.get(f"/api/v1/datasets/{ds_id}/audit").json()
    assert any(e["action"] == "import" for e in events)


def test_sensitive_redaction_follows_version_contract(client) -> None:
    pid = _project(client, "SensitivePerVersion")
    ds = _upload(
        client,
        pid,
        "priv",
        b'{"question":"q","email":"a@b.com","answer":"a"}\n',
    )
    v2 = client.post(
        f"/api/v1/datasets/{ds['id']}/versions",
        data={"mode": "replace", "sensitive_fields": '["email"]'},
        files={"file": ("v.jsonl", b'{"question":"q2","email":"b@c.com","answer":"a"}\n', "application/x-ndjson")},
    ).json()
    assert v2["version"] == 2

    current_raw = client.get(f"/api/v1/datasets/{ds['id']}/preview/raw").json()
    assert current_raw["rows"][0]["email"] == "[REDACTED]"
    old_raw = client.get(f"/api/v1/datasets/{ds['id']}/preview/raw?version=1").json()
    assert old_raw["rows"][0]["email"] == "a@b.com"
