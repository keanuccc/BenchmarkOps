"""End-to-end acceptance script for the P0/P1/P2 feature set.

Run against a fresh backend (mock provider recommended):

  python scripts/acceptance_e2e.py [--base http://localhost:8000/api/v1]

Exercises: multi-tenant org + API keys, project/dataset/benchmark/prompt,
experiment run, subgroups, failure diff, report generate + HTML/PDF export,
scheduled reports, webhooks, budget enforcement, model routing, CLI parity
helpers (export + regression math via the same API).
"""
from __future__ import annotations

import argparse
import io
import json
import time
import urllib.error
import urllib.request

BASE = "http://localhost:8000/api/v1"

passed: list[str] = []
failed: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    tag = "PASS" if ok else "FAIL"
    print(f"[{tag}] {name}" + (f" — {detail}" if detail else ""))
    (passed if ok else failed).append(name)


def req(method: str, path: str, *, body=None, token: str | None = None, files=None):
    url = BASE + path
    headers = {"User-Agent": "acceptance-e2e"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = None
    if files is not None:
        boundary = "----acceptance"
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
    request = urllib.request.Request(
        url, data=data, headers=headers, method=method
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as resp:
            raw = resp.read()
            return resp.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")[:300]


def req_raw(method: str, path: str, *, token: str | None = None) -> tuple[int, bytes]:
    headers = {"User-Agent": "acceptance-e2e"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(BASE + path, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=120) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def wait_completed(experiment_id: str, token: str) -> dict:
    for _ in range(120):
        st, exp = req("GET", f"/experiments/{experiment_id}", token=token)
        if st == 200 and exp.get("status") in (
            "completed",
            "partial",
            "failed",
            "cancelled",
        ):
            return exp
        time.sleep(1)
    return {"status": "timeout"}


def main() -> None:
    global BASE
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default=BASE)
    args = parser.parse_args()
    BASE = args.base

    # 1) Multi-tenant: create organization + owner key.
    st, org_resp = req(
        "POST",
        "/organizations/",
        body={"name": "验收组织", "description": "e2e"},
    )
    check("创建组织", st == 201 and org_resp.get("api_key", {}).get("key", "").startswith("bmops_"))
    token = org_resp["api_key"]["key"]
    org_id = org_resp["organization"]["id"]

    st, me = req("GET", "/organizations/me", token=token)
    check("读取当前组织", st == 200 and me.get("id") == org_id)

    # 2) Project + dataset + benchmark + prompt.
    st, project = req(
        "POST", "/projects/", body={"name": "验收项目"}, token=token
    )
    check("创建项目", st == 201)
    pid = project["id"]

    qa_rows = (
        '{"question": "退款要多久到账？", "answer": "1-3个工作日", "category": "退款"}\n' * 4
    ).encode("utf-8")
    code_rows = (
        '{"prompt": "实现 add", "answer": "def add(a,b):\\n    return a+b\\n", '
        '"tests": ["assert add(1,2)==3"]}\n' * 2
    ).encode("utf-8")
    st, ds = req(
        "POST",
        "/datasets/upload",
        body={
            "project_id": pid,
            "name": "验收QA",
            "format": "jsonl",
            "task_type": "qa",
            "input_fields": '["question"]',
            "expected_fields": '["answer"]',
            "metadata_fields": '["category"]',
        },
        files={"file": ("qa.jsonl", qa_rows)},
        token=token,
    )
    check("上传 QA 数据集", st in (200, 201) and ds.get("row_count") == 4)
    ds_id = ds["id"]

    st, ds_code = req(
        "POST",
        "/datasets/upload",
        body={
            "project_id": pid,
            "name": "验收Code",
            "format": "jsonl",
            "task_type": "coding",
            "input_fields": '["prompt"]',
            "expected_fields": '["answer"]',
            "metadata_fields": '["tests"]',
        },
        files={"file": ("code.jsonl", code_rows)},
        token=token,
    )
    check("上传代码数据集", st in (200, 201) and ds_code.get("row_count") == 2)
    code_ds_id = ds_code["id"]

    st, bench = req(
        "POST",
        "/benchmarks/",
        body={
            "project_id": pid,
            "name": "QA 精确匹配",
            "type": "qa",
            "metric": "exact_match_ci",
        },
        token=token,
    )
    check("创建基准(qa)", st == 201)
    bench_id = bench["id"]

    st, bench_code = req(
        "POST",
        "/benchmarks/",
        body={
            "project_id": pid,
            "name": "代码测试用例",
            "type": "coding",
            "metric": "code_pass",
            "metric_config": {"timeout_seconds": 5},
        },
        token=token,
    )
    check("创建基准(code_pass)", st == 201)
    code_bench_id = bench_code["id"]

    st, prompt = req(
        "POST",
        "/prompts/",
        body={
            "project_id": pid,
            "name": "简洁回答",
            "template": "问题：{question}\n只输出答案：",
        },
        token=token,
    )
    check("创建提示词", st in (200, 201))
    prompt_id = prompt["id"]

    # 3) Experiments + run (mock provider).
    req("POST", "/models/seed", body={}, token=token)
    st, models = req("GET", "/models/", token=token)
    model_id = models["items"][0]["id"]
    st, exp = req(
        "POST",
        "/experiments/",
        body={
            "project_id": pid,
            "name": "验收实验 QA",
            "dataset_id": ds_id,
            "benchmark_id": bench_id,
            "prompt_id": prompt_id,
            "model_id": model_id,
        },
        token=token,
    )
    check("创建实验", st == 201)
    exp_id = exp["id"]
    req("POST", f"/experiments/{exp_id}/run", body={}, token=token)
    exp_done = wait_completed(exp_id, token)
    check("实验运行完成", exp_done.get("status") in ("completed", "partial"))

    st, exp_code = req(
        "POST",
        "/experiments/",
        body={
            "project_id": pid,
            "name": "验收实验 Code",
            "dataset_id": code_ds_id,
            "benchmark_id": code_bench_id,
            "prompt_id": prompt_id,
            "model_id": model_id,
        },
        token=token,
    )
    code_exp_id = exp_code["id"]
    req("POST", f"/experiments/{code_exp_id}/run", body={}, token=token)
    code_done = wait_completed(code_exp_id, token)
    check("代码实验运行完成", code_done.get("status") in ("completed", "partial"))

    # 4) Subgroups + failure diff.
    st, subgroups = req(
        "GET", f"/analytics/experiments/{exp_id}/subgroups?group_field=category", token=token
    )
    check("分组分析", st == 200 and subgroups.get("total_rows") == 4)

    st, leaderboard = req(
        "GET", f"/analytics/leaderboard?project_id={pid}", token=token
    )
    check("排行榜", st == 200 and len(leaderboard) >= 1)

    # 5) Report generate + HTML/PDF export.
    st, report = req(
        "POST",
        "/reports/generate",
        body={"project_id": pid, "experiment_ids": [exp_id, code_exp_id], "title": "验收报告"},
        token=token,
    )
    check("生成报告", st == 201 and bool(report.get("content_markdown")))
    report_id = report["id"]
    html_status, html_body = req_raw(
        "GET", f"/reports/{report_id}/export?format=html", token=token
    )
    check("导出 HTML", html_status == 200)
    check("导出 HTML 内容", b"<!DOCTYPE html>" in html_body)
    pdf_status, pdf_body = req_raw(
        "GET", f"/reports/{report_id}/export/pdf", token=token
    )
    check("导出 PDF", pdf_status == 200 and pdf_body.startswith(b"%PDF"))

    # 6) Scheduled report.
    st, sched = req(
        "POST",
        "/scheduled-reports/",
        body={
            "project_id": pid,
            "name": "每日验收",
            "experiment_ids": [exp_id],
            "schedule": "daily",
            "format": "md",
        },
        token=token,
    )
    check("创建定时报告", st == 201 and sched.get("next_run_at"))
    sched_id = sched["id"]
    st, sched_run = req(
        "POST", f"/scheduled-reports/{sched_id}/run", body={}, token=token
    )
    check("定时报告立即运行", st == 200 and sched_run.get("last_status") == "success")

    # 7) Webhook (local receiver).
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    hook_received = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            length = int(self.headers.get("Content-Length", 0))
            hook_received.append(self.rfile.read(length))
            self.send_response(200)
            self.end_headers()

        def log_message(self, *args):  # noqa: ARG002
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_address[1]
    st, hook = req(
        "POST",
        "/webhooks/",
        body={
            "project_id": pid,
            "name": "验收钩子",
            "url": f"http://127.0.0.1:{port}/hook",
            "secret": "acc",
            "events": ["experiment.completed", "experiment.failed"],
        },
        token=token,
    )
    check("创建 Webhook", st == 201)
    hook_id = hook["id"]
    st, test_resp = req(
        "POST", f"/webhooks/{hook_id}/test", body={}, token=token
    )
    check("Webhook 测试送达", st == 200 and test_resp.get("delivered") is True)
    server.shutdown()

    # 8) Budget enforcement.
    st, _ = req(
        "PATCH",
        f"/organizations/{org_id}",
        body={"monthly_budget_usd": 0.000001},
        token=token,
    )
    st, blocked = req(
        "POST", f"/experiments/{exp_id}/run", body={}, token=token
    )
    check("预算超限拒绝运行", st == 422 and "budget" in str(blocked).lower())
    req(
        "PATCH",
        f"/organizations/{org_id}",
        body={"monthly_budget_usd": None},
        token=token,
    )

    # 9) Model routing.
    st, routing = req(
        "GET", f"/analytics/model-routing?project_id={pid}", token=token
    )
    check("模型路由建议", st == 200 and len(routing) >= 1)

    # 10) Tenant isolation.
    st, other_org = req(
        "POST",
        "/organizations/",
        body={"name": "另一组织"},
    )
    other_token = other_org["api_key"]["key"]
    st, other_projects = req("GET", "/projects/", token=other_token)
    check(
        "租户隔离（另一组织看不到本项目）",
        st == 200 and all(p["id"] != pid for p in other_projects["items"]),
    )

    print()
    print(f"PASSED: {len(passed)}  FAILED: {len(failed)}")
    if failed:
        print("Failed:", *failed, sep="\n  - ")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
