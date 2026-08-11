"""进阶链路 D：删除完整性、错误响应一致性、500 行压力、PDF 中文端到端。

用法：python scripts/run_advanced_d.py [--base http://localhost:8000/api/v1] [--db <sqlite路径>]
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import time
import urllib.error
import urllib.request
import uuid

BASE = "http://localhost:8000/api/v1"
passed: list[str] = []
failed: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    tag = "PASS" if ok else "FAIL"
    print(f"[{tag}] {name}" + (f" — {detail}" if detail else ""))
    (passed if ok else failed).append(name)


def req(method: str, path: str, *, body=None, files=None):
    url = BASE + path
    headers = {"User-Agent": "run-advanced-d"}
    data = None
    if files is not None:
        boundary = "----advd"
        parts = []
        for field, val in body.items():
            parts.append(
                f'--{boundary}\r\nContent-Disposition: form-data; name="{field}"\r\n\r\n{val}\r\n'.encode()
            )
        for fld, (fname, fbytes) in files.items():
            parts.append(
                f'--{boundary}\r\nContent-Disposition: form-data; name="{fld}"; filename="{fname}"\r\n'
                f"Content-Type: application/jsonl\r\n\r\n".encode() + fbytes + b"\r\n"
            )
        parts.append(f"--{boundary}--\r\n".encode())
        data = b"".join(parts)
        headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
    elif body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=300) as resp:
            raw = resp.read()
            return resp.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")[:400]
    except urllib.error.URLError as e:
        raise SystemExit(f"Cannot reach {url}: {e}") from e


def req_raw(path: str) -> tuple[int, bytes]:
    request = urllib.request.Request(BASE + path, headers={"User-Agent": "run-advanced-d"})
    try:
        with urllib.request.urlopen(request, timeout=180) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def wait_done(experiment_id: str) -> dict:
    for _ in range(600):
        st, exp = req("GET", f"/experiments/{experiment_id}")
        if st == 200 and exp.get("status") in ("completed", "partial", "failed", "cancelled"):
            return exp
        time.sleep(1)
    return {"status": "timeout"}


def _qa_payload(rows: int) -> bytes:
    lines = [
        json.dumps({"question": "计算 2+2", "answer": "4", "category": "c"}, ensure_ascii=False)
        for _ in range(rows)
    ]
    return ("\n".join(lines) + "\n").encode("utf-8")


def main() -> None:
    global BASE
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default=BASE)
    parser.add_argument("--db", default=r"D:\code\benchmarkv1\backend\benchmarkops.db")
    args = parser.parse_args()
    BASE = args.base
    suffix = uuid.uuid4().hex[:6]

    # ---------- D1 删除完整性 ----------
    st, project = req("POST", "/projects/", body={"name": f"删除完整性 {suffix}"})
    pid = project["id"]
    st, ds = req(
        "POST", "/datasets/upload",
        body={"project_id": pid, "name": "D数据", "format": "jsonl", "task_type": "qa",
              "input_fields": '["question"]', "expected_fields": '["answer"]', "metadata_fields": '["category"]'},
        files={"file": ("d.jsonl", _qa_payload(5))},
    )
    ds_id = ds["id"]
    st, bench = req("POST", "/benchmarks/", body={"project_id": pid, "name": "B", "type": "qa", "metric": "exact_match_ci"})
    bench_id = bench["id"]
    st, prompt = req("POST", "/prompts/", body={"project_id": pid, "name": "P", "template": "问题：{question}\n答案："})
    prompt_id = prompt["id"]
    st, model = req("POST", "/models/", body={
        "name": f"D Mock {suffix}", "provider": "mock", "model_id": f"advd-mock-{suffix}",
        "context_length": 8192, "pricing": {"input_per_1k": 0.0, "output_per_1k": 0.0}, "capabilities": ["qa"],
    })
    model_id = model["id"]
    st, exp = req("POST", "/experiments/", body={
        "project_id": pid, "name": "E", "dataset_id": ds_id,
        "benchmark_id": bench_id, "prompt_id": prompt_id, "model_id": model_id,
    })
    exp_id = exp["id"]
    req("POST", f"/experiments/{exp_id}/run", body={})
    wait_done(exp_id)
    st, report = req("POST", "/reports/generate", body={
        "project_id": pid, "experiment_ids": [exp_id], "title": "D报告",
    })
    report_id = report["id"]

    st, _ = req("DELETE", f"/projects/{pid}")
    check("删除项目", st in (200, 204))
    st, _ = req("GET", f"/projects/{pid}")
    check("项目已不存在", st == 404)
    st, _ = req("GET", f"/datasets/{ds_id}")
    check("数据集已不存在", st == 404)
    st, _ = req("GET", f"/experiments/{exp_id}")
    check("实验已不存在", st == 404)
    st, _ = req("GET", f"/reports/{report_id}")
    check("报告已不存在", st == 404)

    conn = sqlite3.connect(args.db)
    orphan_count = 0
    for table, cond in (
        ("datasets", "project_id = ?"),
        ("datasets_rows", "dataset_id IN (SELECT id FROM datasets WHERE project_id = ?)"),
        ("benchmarks", "project_id = ?"),
        ("prompts", "project_id = ?"),
        ("experiments", "project_id = ?"),
        ("experiment_results", "experiment_id IN (SELECT id FROM experiments WHERE project_id = ?)"),
        ("reports", "project_id = ?"),
        ("import_jobs", "project_id = ?"),
    ):
        try:
            orphan_count += conn.execute(f"SELECT COUNT(*) FROM {table} WHERE {cond}", (pid,)).fetchone()[0]
        except sqlite3.OperationalError:
            pass
    conn.close()
    check("无孤儿数据行", orphan_count == 0, f"orphans={orphan_count}")

    # ---------- D2 错误响应一致性 ----------
    st, notfound = req("GET", "/projects/does-not-exist")
    notfound_obj = json.loads(notfound) if isinstance(notfound, str) else (notfound or {})
    check("404 响应格式统一", st == 404 and isinstance(notfound_obj, dict) and notfound_obj.get("error", {}).get("code") == "not_found",
          f"body={str(notfound)[:100]}")
    st, bad = req(
        "POST", "/datasets/upload",
        body={"project_id": pid, "name": "bad", "format": "jsonl"},
        files={"file": ("bad.jsonl", b"not json")},
    )
    bad_obj = json.loads(bad) if isinstance(bad, str) else (bad or {})
    check("422 响应格式统一", st == 422 and isinstance(bad_obj, dict) and bad_obj.get("error", {}).get("code") == "validation_error",
          f"body={str(bad)[:100]}")
    r = urllib.request.Request(
        BASE + "/projects/", data=b"{}",
        headers={"Authorization": "Bearer wrong-key", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        urllib.request.urlopen(r, timeout=30)
        st_auth = 200
        auth_body = {}
    except urllib.error.HTTPError as e:
        st_auth = e.code
        auth_body = json.loads(e.read().decode() or "{}")
    check("错误 Key 返回 401", st_auth == 401 and auth_body.get("error", {}).get("code") == "unauthorized",
          f"st={st_auth} body={str(auth_body)[:100]}")

    # ---------- D3 500 行压力 ----------
    st, project2 = req("POST", "/projects/", body={"name": f"压力 {suffix}"})
    pid2 = project2["id"]
    st, ds2 = req(
        "POST", "/datasets/upload",
        body={"project_id": pid2, "name": "500行", "format": "jsonl", "task_type": "qa",
              "input_fields": '["question"]', "expected_fields": '["answer"]', "metadata_fields": '["category"]'},
        files={"file": ("p500.jsonl", _qa_payload(500))},
    )
    check("上传 500 行", st in (200, 201) and ds2.get("row_count") == 500)
    st, bench2 = req("POST", "/benchmarks/", body={"project_id": pid2, "name": "B", "type": "qa", "metric": "exact_match_ci"})
    st, prompt2 = req("POST", "/prompts/", body={"project_id": pid2, "name": "P", "template": "问题：{question}\n答案："})
    st, exp2 = req("POST", "/experiments/", body={
        "project_id": pid2, "name": "500行实验", "dataset_id": ds2["id"],
        "benchmark_id": bench2["id"], "prompt_id": prompt2["id"], "model_id": model_id,
    })
    t0 = time.time()
    req("POST", f"/experiments/{exp2['id']}/run", body={})
    done2 = wait_done(exp2["id"])
    elapsed = time.time() - t0
    st, rows2 = req("GET", f"/experiments/{exp2['id']}/results")
    row_count = len(rows2) if isinstance(rows2, list) else 0
    check("500 行实验完成", done2.get("status") in ("completed", "partial") and row_count == 500,
          f"status={done2.get('status')} rows={row_count} elapsed={elapsed:.1f}s")

    # ---------- D4 PDF 中文端到端 ----------
    st, report2 = req("POST", "/reports/generate", body={
        "project_id": pid2, "experiment_ids": [exp2["id"]], "title": "压力报告-中文",
    })
    report2_id = report2["id"]
    st, pdf_bytes = req_raw(f"/reports/{report2_id}/export/pdf")
    import io

    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(pdf_bytes))
    pdf_text = "".join(page.extract_text() or "" for page in reader.pages)
    has_cjk = any("\u4e00" <= ch <= "\u9fff" for ch in pdf_text)
    check("PDF 中文端到端渲染", st == 200 and has_cjk and "■" not in pdf_text,
          f"st={st} pages={len(reader.pages)}")

    req("DELETE", f"/models/{model_id}")
    print()
    print(f"PASSED: {len(passed)}  FAILED: {len(failed)}")
    if failed:
        print("Failed:", *failed, sep="\n  - ")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
