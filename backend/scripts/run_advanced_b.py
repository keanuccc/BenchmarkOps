"""进阶链路 B：并发实验、取消运行、Webhook 真实触发、定时报告调度、llm_judge_rubric。

用法：python scripts/run_advanced_b.py [--base http://localhost:8000/api/v1]
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import threading
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

BASE = "http://localhost:8000/api/v1"
passed: list[str] = []
failed: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    tag = "PASS" if ok else "FAIL"
    print(f"[{tag}] {name}" + (f" — {detail}" if detail else ""))
    (passed if ok else failed).append(name)


def req(method: str, path: str, *, body=None, files=None):
    url = BASE + path
    headers = {"User-Agent": "run-advanced-b"}
    data = None
    if files is not None:
        boundary = "----advb"
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
        with urllib.request.urlopen(request, timeout=180) as resp:
            raw = resp.read()
            return resp.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")[:500]
    except urllib.error.URLError as e:
        raise SystemExit(f"Cannot reach {url}: {e}") from e


def wait_status(experiment_id: str, terminal=("completed", "partial", "failed", "cancelled"), timeout=180) -> dict:
    for _ in range(timeout):
        st, exp = req("GET", f"/experiments/{experiment_id}")
        if st == 200 and exp.get("status") in terminal:
            return exp
        time.sleep(1)
    return {"status": "timeout"}


def main() -> None:
    global BASE
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default=BASE)
    parser.add_argument("--db", default=r"D:\code\benchmarkv1\backend\benchmarkops.db")
    args = parser.parse_args()
    BASE = args.base
    suffix = uuid.uuid4().hex[:6]

    st, project = req("POST", "/projects/", body={"name": f"进阶链路B {suffix}", "description": "并发/取消/webhook/调度/judge"})
    check("创建项目", st == 201)
    pid = project["id"]

    st, bench = req("POST", "/benchmarks/", body={"project_id": pid, "name": "QA精确", "type": "qa", "metric": "exact_match_ci"})
    bench_id = bench["id"]
    st, prompt = req("POST", "/prompts/", body={"project_id": pid, "name": "模板", "template": "问题：{question}\n答案："})
    prompt_id = prompt["id"]
    st, prompt_code = req("POST", "/prompts/", body={"project_id": pid, "name": "代码模板", "template": "{prompt}"})
    prompt_code_id = prompt_code["id"]
    st, model = req("POST", "/models/", body={
        "name": f"AdvB Mock {suffix}", "provider": "mock", "model_id": f"advb-mock-{suffix}",
        "context_length": 8192, "pricing": {"input_per_1k": 0.0, "output_per_1k": 0.0}, "capabilities": ["qa", "coding"],
    })
    model_id = model["id"]

    qa_rows = [{"question": f"计算 2+2", "answer": "4", "category": "c"} for _ in range(20)]
    payload = "\n".join(json.dumps(r, ensure_ascii=False) for r in qa_rows).encode("utf-8")
    st, ds = req("POST", "/datasets/upload", body={
        "project_id": pid, "name": "并发QA", "format": "jsonl", "task_type": "qa",
        "input_fields": '["question"]', "expected_fields": '["answer"]', "metadata_fields": '["category"]',
    }, files={"file": ("qa.jsonl", payload)})
    ds_id = ds["id"]

    # 1) 并发实验：同时提交 3 个，全部应完成且无 DB 锁错误
    exp_ids = []
    for i in range(3):
        st, exp = req("POST", "/experiments/", body={
            "project_id": pid, "name": f"并发实验{i}", "dataset_id": ds_id,
            "benchmark_id": bench_id, "prompt_id": prompt_id, "model_id": model_id,
        })
        if st != 201:
            print(f"    [DBG] 实验创建失败 st={st} body={str(exp)[:200]}")
            raise SystemExit(f"实验创建失败: {exp}")
        exp_ids.append(exp["id"])
    t0 = time.time()
    for eid in exp_ids:
        req("POST", f"/experiments/{eid}/run", body={})
    results = [wait_status(eid) for eid in exp_ids]
    elapsed = time.time() - t0
    all_ok = all(r.get("status") in ("completed", "partial") for r in results)
    check("并发 3 实验全部完成", all_ok, f"elapsed={elapsed:.1f}s statuses={[r.get('status') for r in results]}")
    rows_err = 0
    for eid in exp_ids:
        st, rows = req("GET", f"/experiments/{eid}/results")
        rows_err += sum(1 for r in (rows or []) if r.get("error") and "database is locked" in str(r.get("error")))
    check("并发无数据库锁错误", rows_err == 0, f"locked_errors={rows_err}")

    # 2) 取消运行：用慢速 code_pass 数据
    slow_rows = [
        {
            "prompt": "def f(): import time; time.sleep(2); return 1",
            "answer": "def f(): import time; time.sleep(2); return 1",
            "tests": ["assert f() == 1"],
        }
        for _ in range(8)
    ]
    slow_payload = "\n".join(json.dumps(r, ensure_ascii=False) for r in slow_rows).encode("utf-8")
    st, ds_slow = req("POST", "/datasets/upload", body={
        "project_id": pid, "name": "慢速代码", "format": "jsonl", "task_type": "coding",
        "input_fields": '["prompt"]', "expected_fields": '["answer","tests"]', "metadata_fields": '[]',
    }, files={"file": ("slow.jsonl", slow_payload)})
    st, bench_slow = req("POST", "/benchmarks/", body={
        "project_id": pid, "name": "慢速code_pass", "type": "coding", "metric": "code_pass",
        "metric_config": {"timeout_seconds": 6},
    })
    st, exp_cancel = req("POST", "/experiments/", body={
        "project_id": pid, "name": "取消测试", "dataset_id": ds_slow["id"],
        "benchmark_id": bench_slow["id"], "prompt_id": prompt_code_id, "model_id": model_id,
    })
    cancel_id = exp_cancel["id"]
    req("POST", f"/experiments/{cancel_id}/run", body={})
    time.sleep(1.5)
    st, cancelled = req("POST", f"/experiments/{cancel_id}/cancel", body={})
    check("发起取消", st == 200)
    done_c = wait_status(cancel_id, terminal=("cancelled", "completed", "partial", "failed"))
    check("取消生效（状态为 cancelled）", done_c.get("status") == "cancelled", f"status={done_c.get('status')}")
    st, cancel_rows = req("GET", f"/experiments/{cancel_id}/results")
    check("取消后无残留结果", (cancel_rows or []) == [], f"rows={len(cancel_rows or [])}")

    # 3) Webhook 真实触发
    received: list[dict] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            try:
                received.append(json.loads(body))
            except json.JSONDecodeError:
                pass
            self.send_response(200)
            self.end_headers()

        def log_message(self, *args):  # noqa: ARG002
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_address[1]
    st, hook = req("POST", "/webhooks/", body={
        "project_id": pid, "name": "真实触发", "url": f"http://127.0.0.1:{port}/hook",
        "secret": "advb", "events": ["experiment.completed", "experiment.failed"],
    })
    check("创建 Webhook", st == 201)
    st, exp_hook = req("POST", "/experiments/", body={
        "project_id": pid, "name": "Webhook实验", "dataset_id": ds_id,
        "benchmark_id": bench_id, "prompt_id": prompt_id, "model_id": model_id,
    })
    hook_exp_id = exp_hook["id"]
    req("POST", f"/experiments/{hook_exp_id}/run", body={})
    wait_status(hook_exp_id)
    time.sleep(2)
    server.shutdown()
    events = [e.get("event") for e in received]
    check("Webhook 收到实验完成事件", "experiment.completed" in events, f"events={events}")
    check("Webhook 载荷含准确率", bool(received) and "accuracy" in received[0])

    # 4) 定时报告真实调度（把 next_run_at 改为过去，等调度器触发）
    st, sched = req("POST", "/scheduled-reports/", body={
        "project_id": pid, "name": "调度验证", "experiment_ids": [exp_ids[0]],
        "schedule": "daily", "format": "md",
    })
    check("创建定时报告", st == 201)
    sched_id = sched["id"]
    conn = sqlite3.connect(args.db)
    now = datetime.now(timezone.utc)
    past = (now - timedelta(minutes=2)).strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        "UPDATE scheduled_reports SET next_run_at = ? WHERE id = ?",
        (past, sched_id),
    )
    conn.commit()
    conn.close()
    # 调度器每 60 秒扫一次；轮询最多 100 秒
    fired = False
    for _ in range(100):
        time.sleep(1)
        st, sched_now = req("GET", f"/scheduled-reports/{sched_id}")
        if sched_now.get("last_run_at") is not None:
            fired = True
            break
    check("定时报告被调度器自动执行", fired, f"last_status={sched_now.get('last_status') if fired else 'not fired'}")

    # 5) llm_judge_rubric（mock judge：输出非 JSON 时观察平台行为）
    st, bench_judge = req("POST", "/benchmarks/", body={
        "project_id": pid, "name": "Judge Rubric", "type": "qa", "metric": "llm_judge_rubric",
        "metric_config": {
            "dimensions": [
                {"name": "正确性", "description": "答案是否正确", "weight": 0.6},
                {"name": "完整性", "description": "是否完整", "weight": 0.4},
            ],
            "scale": 5,
        },
    })
    check("创建 llm_judge_rubric 基准", st == 201)
    st, exp_judge = req("POST", "/experiments/", body={
        "project_id": pid, "name": "Judge实验", "dataset_id": ds_id,
        "benchmark_id": bench_judge["id"], "prompt_id": prompt_id, "model_id": model_id,
    })
    req("POST", f"/experiments/{exp_judge['id']}/run", body={})
    done_j = wait_status(exp_judge["id"])
    st, judge_rows = req("GET", f"/experiments/{exp_judge['id']}/results")
    judge_list = judge_rows or []
    check("Judge 实验有终态", done_j.get("status") in ("completed", "partial", "failed"), f"status={done_j.get('status')}")
    check("Judge 实验未崩溃（有逐行结果）", len(judge_list) > 0, f"rows={len(judge_list)}")

    req("DELETE", f"/models/{model_id}")
    print()
    print(f"PASSED: {len(passed)}  FAILED: {len(failed)}")
    if failed:
        print("Failed:", *failed, sep="\n  - ")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
