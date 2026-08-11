"""进阶链路 C：多租户端到端、prep 工作台、压力/边界、审计日志。

用法：python scripts/run_advanced_c.py [--base http://localhost:8000/api/v1]
"""
from __future__ import annotations

import argparse
import json
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


def req(method: str, path: str, *, body=None, files=None, token=None):
    url = BASE + path
    headers = {"User-Agent": "run-advanced-c"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = None
    if files is not None:
        boundary = "----advc"
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
        with urllib.request.urlopen(request, timeout=240) as resp:
            raw = resp.read()
            return resp.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")[:400]
    except urllib.error.URLError as e:
        raise SystemExit(f"Cannot reach {url}: {e}") from e


def wait_done(experiment_id: str) -> dict:
    for _ in range(300):
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
    args = parser.parse_args()
    BASE = args.base
    suffix = uuid.uuid4().hex[:6]

    # ---------- C1 多租户端到端 ----------
    st, org_a = req("POST", "/organizations/", body={"name": f"租户A {suffix}"})
    check("创建组织 A", st == 201)
    key_a = org_a["api_key"]["key"]
    org_a_id = org_a["organization"]["id"]
    st, org_b = req("POST", "/organizations/", body={"name": f"租户B {suffix}"})
    key_b = org_b["api_key"]["key"]
    check("创建组织 B", st == 201)

    st, project_a = req("POST", "/projects/", body={"name": f"A 项目 {suffix}"}, token=key_a)
    check("A 创建项目", st == 201)
    pid_a = project_a["id"]
    st, ds_a = req(
        "POST", "/datasets/upload",
        body={"project_id": pid_a, "name": "A数据", "format": "jsonl", "task_type": "qa",
              "input_fields": '["question"]', "expected_fields": '["answer"]', "metadata_fields": '["category"]'},
        files={"file": ("a.jsonl", _qa_payload(5))},
        token=key_a,
    )
    check("A 上传数据集", st in (200, 201))

    st, list_b = req("GET", "/projects/", token=key_b)
    check("B 看不到 A 的项目", st == 200 and all(p["id"] != pid_a for p in list_b["items"]))
    st, get_b = req("GET", f"/projects/{pid_a}", token=key_b)
    check("B 跨组织读项目返回 404", st == 404)
    st, patch_b = req("PATCH", f"/projects/{pid_a}", body={"name": "hack"}, token=key_b)
    check("B 跨组织改项目被拒", st == 404)

    st, viewer = req("POST", f"/organizations/{org_a_id}/api-keys", body={"name": "ro", "role": "viewer"}, token=key_a)
    check("A 创建 viewer Key", st == 201)
    key_viewer = viewer["key"]
    st, write_viewer = req("POST", "/projects/", body={"name": "x"}, token=key_viewer)
    check("viewer 写操作被拒 403", st == 403)
    st, read_viewer = req("GET", "/projects/", token=key_viewer)
    check("viewer 读自己组织正常", st == 200)

    st, project_b = req("POST", "/projects/", body={"name": f"B 项目 {suffix}"}, token=key_b)
    check("B 创建自己的项目", st == 201)

    # ---------- C2 prep 工作台 ----------
    prep_rows = _qa_payload(4)
    st, analyze = req(
        "POST", "/prep/analyze",
        body={"format": "jsonl"},
        files={"file": ("raw.jsonl", prep_rows)},
    )
    check("prep/analyze 分析文件", st == 200 and "columns" in str(analyze))

    config = {
        "task_type": "qa",
        "input_fields": ["question"],
        "expected_fields": ["answer"],
        "metadata_fields": ["category"],
    }
    st, transform = req(
        "POST", "/prep/transform",
        body={"format": "jsonl", "config": json.dumps(config, ensure_ascii=False)},
        files={"file": ("raw.jsonl", prep_rows)},
    )
    check("prep/transform 转换预览", st == 200 and "rows" in str(transform))

    st, model = req("POST", "/models/", body={
        "name": f"C Mock {suffix}", "provider": "mock", "model_id": f"advc-mock-{suffix}",
        "context_length": 8192, "pricing": {"input_per_1k": 0.0, "output_per_1k": 0.0}, "capabilities": ["qa"],
    })
    model_id = model["id"]
    dry_rows = [json.loads(line) for line in prep_rows.decode().splitlines() if line.strip()]
    st, dry = req("POST", "/prep/dry-run", body={
        "rows": dry_rows,
        "contract": {"task_type": "qa", "input_fields": ["question"], "expected_fields": ["answer"]},
        "template": "问题：{question}\n答案：",
        "benchmark_type": "qa",
        "metric": "exact_match_ci",
        "model_id": model_id,
        "provider": "mock",
    })
    check("prep/dry-run 内存评分", st == 200 and "score" in str(dry) or st == 200 and "rows" in str(dry), f"st={st}")

    # ---------- C3 压力与边界 ----------
    st, ds_200 = req(
        "POST", "/datasets/upload",
        body={"project_id": pid_a, "name": "200行压力", "format": "jsonl", "task_type": "qa",
              "input_fields": '["question"]', "expected_fields": '["answer"]', "metadata_fields": '["category"]'},
        files={"file": ("big.jsonl", _qa_payload(200))},
        token=key_a,
    )
    check("上传 200 行数据集", st in (200, 201) and ds_200.get("row_count") == 200)
    st, bench = req("POST", "/benchmarks/", body={"project_id": pid_a, "name": "QA", "type": "qa", "metric": "exact_match_ci"}, token=key_a)
    st, prompt = req("POST", "/prompts/", body={"project_id": pid_a, "name": "P", "template": "问题：{question}\n答案："}, token=key_a)
    st, exp_200 = req("POST", "/experiments/", body={
        "project_id": pid_a, "name": "200行实验", "dataset_id": ds_200["id"],
        "benchmark_id": bench["id"], "prompt_id": prompt["id"], "model_id": model_id,
    }, token=key_a)
    req("POST", f"/experiments/{exp_200['id']}/run", body={}, token=key_a)
    done = wait_done(exp_200["id"])
    check("200 行实验完成", done.get("status") in ("completed", "partial") and done.get("cells_done") == 200,
          f"status={done.get('status')} cells={done.get('cells_done')}")

    # 边界：空文件 / 无效 JSONL / 超大文件
    st, empty = req(
        "POST", "/datasets/upload",
        body={"project_id": pid_a, "name": "空", "format": "jsonl"},
        files={"file": ("empty.jsonl", b"")},
        token=key_a,
    )
    check("空文件被拒绝", st == 422)
    st, bad = req(
        "POST", "/datasets/upload",
        body={"project_id": pid_a, "name": "坏", "format": "jsonl"},
        files={"file": ("bad.jsonl", b'{"question": "x"\nnot-json\n')},
        token=key_a,
    )
    check("无效 JSONL 被拒绝", st == 422)
    big_blob = b'{"question": "q", "answer": "a"}\n' * 400000  # ~13MB, 低于 50MB 上限
    st, big = req(
        "POST", "/datasets/upload",
        body={"project_id": pid_a, "name": "大", "format": "jsonl"},
        files={"file": ("big2.jsonl", big_blob)},
        token=key_a,
    )
    check("40 万行超行数上限被拒绝", st == 422, f"st={st}")

    # 上下文溢出：小 context 模型 + 长 question
    st, model_tiny = req("POST", "/models/", body={
        "name": f"Tiny {suffix}", "provider": "mock", "model_id": f"advc-tiny-{suffix}",
        "context_length": 20, "pricing": {"input_per_1k": 0.0, "output_per_1k": 0.0}, "capabilities": ["qa"],
    })
    long_rows = [{"question": "这是一个非常长的测试问题" * 20, "answer": "4", "category": "c"}]
    long_payload = "\n".join(json.dumps(r, ensure_ascii=False) for r in long_rows).encode()
    st, ds_long = req(
        "POST", "/datasets/upload",
        body={"project_id": pid_a, "name": "超长", "format": "jsonl", "task_type": "qa",
              "input_fields": '["question"]', "expected_fields": '["answer"]', "metadata_fields": '["category"]'},
        files={"file": ("long.jsonl", long_payload)},
        token=key_a,
    )
    st, exp_long = req("POST", "/experiments/", body={
        "project_id": pid_a, "name": "溢出实验", "dataset_id": ds_long["id"],
        "benchmark_id": bench["id"], "prompt_id": prompt["id"], "model_id": model_tiny["id"],
    }, token=key_a)
    req("POST", f"/experiments/{exp_long['id']}/run", body={}, token=key_a)
    done_long = wait_done(exp_long["id"])
    st, long_rows_out = req("GET", f"/experiments/{exp_long['id']}/results")
    long_list = long_rows_out or []
    overflow_marked = any(
        r.get("error") and "context" in str(r.get("error")).lower()
        for r in long_list
    )
    check("上下文溢出被标记", done_long.get("status") in ("completed", "partial") and overflow_marked,
          f"status={done_long.get('status')} errors={[r.get('error') for r in long_list[:1]]}")

    # ---------- C4 审计日志 ----------
    st, audit = req("GET", f"/datasets/{ds_a['id']}/audit", token=key_a)
    events = audit if isinstance(audit, list) else []
    check("数据集审计事件存在", st == 200 and len(events) >= 1, f"events={len(events)}")
    check("审计事件含 create", any(e.get("action") == "create" for e in events), f"actions={[e.get('action') for e in events]}")

    req("DELETE", f"/models/{model_id}")
    req("DELETE", f"/models/{model_tiny['id']}")
    print()
    print(f"PASSED: {len(passed)}  FAILED: {len(failed)}")
    if failed:
        print("Failed:", *failed, sep="\n  - ")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
