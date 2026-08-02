"""Format expansion: TSV, XLSX, BOM/UTF-16 encodings, magic-byte validation."""
from __future__ import annotations

import io


def _project(client, name: str) -> str:
    return client.post("/api/v1/projects/", json={"name": name}).json()["id"]


def _upload_bytes(client, pid: str, name: str, filename: str, data: bytes, extra: dict | None = None) -> dict:
    form = {"project_id": pid, "name": name}
    if extra:
        form.update(extra)
    return client.post(
        "/api/v1/datasets/upload",
        data=form,
        files={"file": (filename, data, "application/octet-stream")},
    )


def test_tsv_upload_with_explicit_format(client) -> None:
    pid = _project(client, "FmtTsv")
    r = _upload_bytes(
        client,
        pid,
        "tsv",
        "data.tsv",
        b"question\tanswer\nq1\ta1\n",
        extra={"format": "tsv"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["row_count"] == 1
    assert r.json()["format"] == "tsv"


def test_tsv_extension_inferred(client) -> None:
    pid = _project(client, "FmtTsvInfer")
    r = _upload_bytes(client, pid, "tsv-infer", "data.tsv", b"question\tanswer\nq1\ta1\n")
    assert r.status_code == 200, r.text
    assert r.json()["format"] == "tsv"


def test_xlsx_upload(client) -> None:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.append(["question", "answer"])
    ws.append(["q1", "a1"])
    ws.append(["q2", "a2"])
    buf = io.BytesIO()
    wb.save(buf)

    pid = _project(client, "FmtXlsx")
    r = _upload_bytes(
        client,
        pid,
        "xlsx",
        "data.xlsx",
        buf.getvalue(),
    )
    assert r.status_code == 200, r.text
    ds = r.json()
    assert ds["format"] == "xlsx"
    assert ds["row_count"] == 2
    assert ds["column_schema"] == ["question", "answer"]


def test_utf8_bom_is_stripped(client) -> None:
    pid = _project(client, "FmtBom")
    data = "\ufeff{\"question\":\"q\",\"answer\":\"a\"}\n".encode("utf-8")
    r = _upload_bytes(client, pid, "bom", "data.jsonl", data, extra={"format": "jsonl"})
    assert r.status_code == 200, r.text
    assert r.json()["column_schema"] == ["question", "answer"]
    assert not any(c.startswith("\ufeff") for c in r.json()["column_schema"])


def test_utf16_jsonl_upload(client) -> None:
    pid = _project(client, "FmtUtf16")
    data = '{"question":"q","answer":"a"}\n'.encode("utf-16")
    r = _upload_bytes(client, pid, "utf16", "data.jsonl", data, extra={"format": "jsonl"})
    assert r.status_code == 200, r.text
    assert r.json()["row_count"] == 1


def test_undecodable_bytes_return_validation_error(client) -> None:
    pid = _project(client, "FmtBadEncoding")
    r = _upload_bytes(
        client,
        pid,
        "badenc",
        "data.jsonl",
        b"\xff\xfe\xfa\x00\x01",
        extra={"format": "jsonl"},
    )
    assert r.status_code == 422
    assert "decode" in r.json()["error"]["message"].lower()


def test_json_magic_mismatch_rejected(client) -> None:
    pid = _project(client, "FmtMagicJson")
    r = _upload_bytes(
        client,
        pid,
        "fake-json",
        "data.json",
        b"question,answer\nq1,a1\n",
        extra={"format": "json"},
    )
    assert r.status_code == 422
    assert "must start" in r.json()["error"]["message"]


def test_xlsx_magic_mismatch_rejected(client) -> None:
    pid = _project(client, "FmtMagicXlsx")
    r = _upload_bytes(
        client,
        pid,
        "fake-xlsx",
        "data.xlsx",
        b"not a zip file",
        extra={"format": "xlsx"},
    )
    assert r.status_code == 422
    assert "xlsx" in r.json()["error"]["message"].lower()
