#!/usr/bin/env python3
"""Live business-data verification of the online BenchmarkOps deployment.

Realistic e-commerce after-sales ticket data (50 rows):
  - Experiment C: intent classification (classification / exact_match_ci)
  - Experiment D: support-reply quality (qa / llm_judge_rubric)
"""

from __future__ import annotations

import json
import sys
import time
from collections import Counter

import httpx

BASE = "http://127.0.0.1:8000/api/v1"
ENV = "/opt/benchmark/backend/.env"
DATA_DIR = "/tmp/live_data"


def load_token() -> str:
    with open(ENV, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line.startswith("API_TOKEN="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("API_TOKEN not found in " + ENV)


TOKEN = load_token()
client = httpx.Client(base_url=BASE, timeout=120)


def call(method: str, path: str, *, expected=(200, 201, 202), **kw):
    headers = {"Authorization": "Bearer " + TOKEN}
    if kw.get("json") is not None:
        headers["Content-Type"] = "application/json"
    r = client.request(method, path, headers=headers, **kw)
    if r.status_code not in expected:
        print("ERROR", method, path, r.status_code, r.text[:1200])
        sys.exit(2)
    if r.status_code == 204 or not r.content:
        return None
    return r.json()


def run_with_retry(eid: str, tries: int = 5) -> dict:
    for attempt in range(1, tries + 1):
        try:
            return call("POST", f"/experiments/{eid}/run")
        except SystemExit:
            print(f"  run attempt {attempt} failed, retrying...")
            time.sleep(3)
    raise SystemExit("run failed after retries")


def wait_experiment(eid: str, timeout: int = 900) -> dict:
    start = time.time()
    while time.time() - start < timeout:
        exp = call("GET", "/experiments/" + eid)
        done = exp.get("cells_done")
        total = exp.get("rows_total")
        print(f"  status: {exp.get('status')} | cells: {done}/{total or '?'}")
        if exp.get("status") in ("completed", "failed", "cancelled"):
            return exp
        time.sleep(5)
    raise SystemExit("experiment did not finish in time")


def upload_dataset(pid: str, fname: str, name: str, task_type: str, expected_field: str) -> dict:
    path = f"{DATA_DIR}/{fname}"
    with open(path, "rb") as f:
        raw = f.read()
    return call(
        "POST",
        "/datasets/upload",
        data={
            "project_id": pid,
            "name": name,
            "format": "csv",
            "description": "真实电商售后工单（模拟原始业务数据）",
            "task_type": task_type,
            "input_fields": '["question"]',
            "expected_fields": json.dumps([expected_field]),
        },
        files={"file": (fname, raw, "text/csv")},
    )


def main() -> None:
    ts = time.strftime("%Y%m%d-%H%M%S")

    # 1. Project
    project = call(
        "POST",
        "/projects/",
        json={
            "name": f"线上验证-电商售后工单-{ts}",
            "description": "真实业务场景：50条电商售后客服工单（意图分类+答复质量）",
        },
    )
    pid = project["id"]
    print("project:", pid, project["name"])

    # 2. Datasets
    ds_c = upload_dataset(pid, "intent_classify.csv", "工单意图分类-50条", "classification", "label")
    ds_d = upload_dataset(pid, "service_reply.csv", "客服答复口径-50条", "qa", "answer")
    print("dataset C:", ds_c["id"], "| rows:", ds_c.get("row_count"))
    print("dataset D:", ds_d["id"], "| rows:", ds_d.get("row_count"))

    # 3. Model (reuse the global Qiniu free model if it already exists)
    target_model_id = "deepseek/deepseek-v4-flash:free"
    existing = call("GET", "/models/?provider=qiniu")
    mid = None
    for m in existing.get("items", []):
        if m.get("model_id") == target_model_id:
            mid = m["id"]
            break
    if mid is None:
        model = call(
            "POST",
            "/models/",
            json={
                "name": "DeepSeek V4 Flash (Qiniu :free)",
                "provider": "qiniu",
                "model_id": target_model_id,
                "context_length": 128000,
                "pricing": {},
                "capabilities": ["chat"],
            },
        )
        mid = model["id"]
    print("model:", mid, target_model_id)

    # 4. Prompt C (classification)
    prompt_c = call(
        "POST",
        "/prompts/",
        json={
            "project_id": pid,
            "name": "工单分类-标签输出",
            "template": (
                "你是电商平台的工单分类专员。请阅读用户留言，从以下类别中选出最合适的一个："
                "退款、换货、物流、发票、优惠券、商品咨询、投诉、账号问题。\n"
                "规则：\n1. 最后一行必须以“答案：”开头。\n"
                "2. “答案：”后只输出类别名，不写解释。\n"
                "用户留言：{question}"
            ),
        },
    )
    pcid = prompt_c["id"]

    # 5. Prompt D (reply quality)
    prompt_d = call(
        "POST",
        "/prompts/",
        json={
            "project_id": pid,
            "name": "客服答复-标准口径",
            "template": (
                "你是电商平台的售后客服。请阅读用户留言，用一句礼貌、专业的话给出客服回复，"
                "说明处理方式或时效。\n规则：\n1. 最后一行必须以“答案：”开头。\n"
                "2. “答案：”后只输出回复内容。\n用户留言：{question}"
            ),
        },
    )
    pdid = prompt_d["id"]

    # 6. Benchmark C + Experiment C
    bench_c = call(
        "POST",
        "/benchmarks/",
        json={
            "project_id": pid,
            "name": "工单意图分类-精确匹配",
            "type": "classification",
            "metric": "exact_match_ci",
            "metric_config": {},
        },
    )
    exp_c = call(
        "POST",
        "/experiments/",
        json={
            "project_id": pid,
            "name": "验证C-工单意图分类",
            "dataset_id": ds_c["id"],
            "benchmark_id": bench_c["id"],
            "prompt_id": pcid,
            "model_id": mid,
        },
    )
    ecid = exp_c["id"]
    print("experiment C:", ecid, "-> run")
    run_with_retry(ecid)
    exp_c_done = wait_experiment(ecid)
    print(
        "C final:",
        json.dumps(
            {k: exp_c_done.get(k) for k in ("status", "metrics", "accuracy", "total_cost", "total_tokens", "runtime_ms", "error")},
            ensure_ascii=False,
        ),
    )
    rows_c = call("GET", f"/experiments/{ecid}/results")
    wrong = []
    label_ok = Counter()
    for row in rows_c:
        exp_label = (row.get("expected") or {}).get("label")
        pred = (row.get("cleaned_prediction") or "").strip()
        score = row.get("score")
        label_ok[(exp_label, pred == exp_label)] += 1
        if score != 1.0:
            wrong.append({"row": row.get("row_idx"), "q": str(row.get("input", {}).get("question"))[:40],
                          "expected": exp_label, "pred": pred, "score": score, "reason": row.get("score_reason")})
    print("C wrong rows:", len(wrong))
    for w in wrong:
        print("  ", json.dumps(w, ensure_ascii=False))
    print("C label breakdown (label, correct/total):")
    per_label = {}
    for (label, ok), cnt in label_ok.items():
        per_label.setdefault(label, [0, 0])[1 if ok else 0] += cnt
    print("  ", json.dumps({k: {"correct": v[1], "total": v[0] + v[1]} for k, v in per_label.items()}, ensure_ascii=False))

    # 7. Benchmark D + Experiment D
    bench_d = call(
        "POST",
        "/benchmarks/",
        json={
            "project_id": pid,
            "name": "客服答复质量-Rubric",
            "type": "qa",
            "metric": "llm_judge_rubric",
            "metric_config": {
                "judge_provider": "qiniu",
                "judge_model": "deepseek/deepseek-v4-flash:free",
                "dimensions": [
                    {"name": "correctness", "description": "处理方式与事实是否正确", "weight": 2},
                    {"name": "completeness", "description": "是否说明关键处理信息（操作路径/时效）", "weight": 1},
                    {"name": "tone", "description": "语气是否礼貌专业", "weight": 1},
                ],
                "scale": 5,
                "rationale": False,
            },
        },
    )
    exp_d = call(
        "POST",
        "/experiments/",
        json={
            "project_id": pid,
            "name": "验证D-客服答复质量",
            "dataset_id": ds_d["id"],
            "benchmark_id": bench_d["id"],
            "prompt_id": pdid,
            "model_id": mid,
        },
    )
    edid = exp_d["id"]
    print("experiment D:", edid, "-> run")
    run_with_retry(edid)
    exp_d_done = wait_experiment(edid)
    print(
        "D final:",
        json.dumps(
            {k: exp_d_done.get(k) for k in ("status", "metrics", "accuracy", "total_cost", "total_tokens", "runtime_ms", "error")},
            ensure_ascii=False,
        ),
    )
    rows_d = call("GET", f"/experiments/{edid}/results")
    scores = [r.get("score") for r in rows_d]
    print("D scores:", json.dumps({"min": min(scores), "max": max(scores), "avg": round(sum(scores) / len(scores), 4), "n": len(scores)}, ensure_ascii=False))
    for row in sorted(rows_d, key=lambda r: r.get("score"))[:5]:
        print(
            "  D low:",
            json.dumps(
                {
                    "row": row.get("row_idx"),
                    "q": str(row.get("input", {}).get("question"))[:36],
                    "score": row.get("score"),
                    "reason": row.get("score_reason"),
                },
                ensure_ascii=False,
            ),
        )

    print(
        "\nRESULT:",
        json.dumps(
            {
                "project_id": pid,
                "experiment_c": ecid,
                "experiment_d": edid,
                "exp_c_status": exp_c_done.get("status"),
                "exp_c_accuracy": exp_c_done.get("accuracy"),
                "exp_d_status": exp_d_done.get("status"),
                "exp_d_primary_score": (exp_d_done.get("metrics") or {}).get("primary_score"),
                "exp_d_avg_score": round(sum(scores) / len(scores), 4),
            },
            ensure_ascii=False,
        ),
    )


if __name__ == "__main__":
    main()
