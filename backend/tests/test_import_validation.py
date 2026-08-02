"""Import-time validation: field types, whitespace blanks, case-insensitive keys."""
from __future__ import annotations

import time


def _wait_job(client, job_id: str, timeout: float = 10.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = client.get(f"/api/v1/datasets/imports/{job_id}").json()
        if job["status"] in ("succeeded", "failed", "cancelled"):
            return job
        time.sleep(0.05)
    raise AssertionError(f"import job {job_id} did not finish in {timeout}s")


def _upload(client, pid: str, name: str, rows: bytes, extra: dict | None = None) -> dict:
    data = {"project_id": pid, "name": name, "format": "jsonl"}
    if extra:
        data.update(extra)
    r = client.post(
        "/api/v1/datasets/upload",
        data=data,
        files={"file": (f"{name}.jsonl", rows, "application/x-ndjson")},
    )
    return r


def _project(client, name: str) -> str:
    return client.post("/api/v1/projects/", json={"name": name}).json()["id"]


def test_field_types_rejects_mismatched_value(client) -> None:
    pid = _project(client, "TypeMismatch")
    r = _upload(
        client,
        pid,
        "typed",
        b'{"question":"q","score":"abc"}\n',
        extra={"field_types": '{"score": "number"}'},
    )
    assert r.status_code == 422
    assert "score" in r.json()["error"]["message"]


def test_field_types_accepts_matching_values(client) -> None:
    pid = _project(client, "TypeMatch")
    r = _upload(
        client,
        pid,
        "typed-ok",
        b'{"question":"q","score":42,"rate":"3.5","ok":true}\n',
        extra={
            "field_types": (
                '{"score": "integer", "rate": "number", "ok": "boolean"}'
            )
        },
    )
    assert r.status_code == 200, r.text


def test_whitespace_only_required_field_rejected(client) -> None:
    pid = _project(client, "WhitespaceRequired")
    r = _upload(
        client,
        pid,
        "blank",
        b'{"question":"   ","answer":"a"}\n',
        extra={"required_fields": '["question"]'},
    )
    assert r.status_code == 422
    assert "missing required field: question" in r.json()["error"]["message"]


def test_whitespace_only_counts_as_null_in_stats(client) -> None:
    pid = _project(client, "WhitespaceStats")
    ds = _upload(
        client,
        pid,
        "spaces",
        b'{"question":"   ","answer":"a"}\n{"question":"q2","answer":"a"}\n',
    ).json()
    assert ds["stats"]["null_counts"]["question"] == 1


def test_expected_key_detection_is_case_insensitive(client) -> None:
    pid = _project(client, "CaseInsensitive")
    ds = _upload(
        client,
        pid,
        "cases",
        b'{"Question":"What?","Answer":"42"}\n',
    ).json()
    assert ds["field_mapping"]["expected_fields"] == ["Answer"]
    assert ds["field_mapping"]["input_fields"] == ["Question"]


def test_expected_key_detection_prefers_exact_lowercase(client) -> None:
    pid = _project(client, "CasePreferLower")
    ds = _upload(
        client,
        pid,
        "mixed",
        b'{"Answer":"upper","answer":"lower"}\n',
    ).json()
    assert ds["field_mapping"]["expected_fields"] == ["answer"]
    assert ds["field_mapping"]["input_fields"] == ["Answer"]


def test_import_job_reports_type_error_rows(client) -> None:
    pid = _project(client, "TypeErrorRows")
    r = client.post(
        "/api/v1/datasets/import",
        data={
            "project_id": pid,
            "name": "typed-bad",
            "format": "jsonl",
            "field_types": '{"score": "number"}',
        },
        files={"file": ("typed-bad.jsonl", b'{"question":"q","score":"abc"}\n', "application/x-ndjson")},
    )
    assert r.status_code == 202
    job = _wait_job(client, r.json()["id"])
    assert job["status"] == "failed"
    assert job["error_rows"]
    assert job["error_rows"][0]["row"] == 0
    assert "score" in job["error_rows"][0]["message"]


def test_upload_rejects_empty_dataset(client) -> None:
    pid = _project(client, "EmptyReject")
    r = _upload(client, pid, "empty", b"")
    assert r.status_code == 422
    assert "empty" in r.json()["error"]["message"].lower()


def test_version_replace_rejects_empty_file(client) -> None:
    pid = _project(client, "EmptyVersion")
    ds = _upload(client, pid, "base", b'{"question":"q","answer":"a"}\n').json()
    r = client.post(
        f"/api/v1/datasets/{ds['id']}/versions",
        data={"mode": "replace"},
        files={"file": ("empty.jsonl", b"", "application/x-ndjson")},
    )
    assert r.status_code == 422
    assert "empty" in r.json()["error"]["message"].lower()


def test_import_job_fails_on_empty_dataset(client) -> None:
    pid = _project(client, "EmptyImport")
    r = client.post(
        "/api/v1/datasets/import",
        data={"project_id": pid, "name": "empty", "format": "jsonl"},
        files={"file": ("empty.jsonl", b"", "application/x-ndjson")},
    )
    assert r.status_code == 202
    job = _wait_job(client, r.json()["id"])
    assert job["status"] == "failed"
    assert "empty" in (job["error"] or "").lower()
