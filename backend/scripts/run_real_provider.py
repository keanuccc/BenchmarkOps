"""真实 Provider 链路验证：Qiniu 与 OpenRouter 各跑一个小实验。

数据为 10 条算术/常识 QA（Mock 可命中同款），真实模型应得到较高准确率。
调用会产生极少量真实费用。用法：
    python scripts/run_real_provider.py [--base http://localhost:8000/api/v1]
"""
from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
import uuid

BASE = "http://localhost:8000/api/v1"


def req(method: str, path: str, *, body=None, files=None):
    url = BASE + path
    headers = {"User-Agent": "run-real-provider"}
    data = None
    if files is not None:
        boundary = "----real"
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
        with urllib.request.urlopen(request, timeout=600) as resp:
            raw = resp.read()
            return resp.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")[:500]
    except urllib.error.URLError as e:
        raise SystemExit(f"Cannot reach {url}: {e}") from e


def wait_done(experiment_id: str, timeout=600) -> dict:
    for _ in range(timeout):
        st, exp = req("GET", f"/experiments/{experiment_id}")
        if st == 200 and exp.get("status") in ("completed", "partial", "failed", "cancelled"):
            return exp
        time.sleep(2)
    return {"status": "timeout"}


QA_ROWS = [
    {"question": "计算 2+2", "answer": "4"},
    {"question": "计算 3*4", "answer": "12"},
    {"question": "计算 10-3", "answer": "7"},
    {"question": "计算 6/2", "answer": "3"},
    {"question": "计算 7+8", "answer": "15"},
    {"question": "france 的首都是哪个城市？", "answer": "Paris"},
    {"question": "水的化学式是什么？", "answer": "H2O"},
    {"question": "一年有多少个月？", "answer": "12"},
    {"question": "光在真空中的速度约是多少？", "answer": "30万公里每秒"},
    {"question": "红楼梦的作者是谁？", "answer": "曹雪芹"},
]


def main() -> None:
    global BASE
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default=BASE)
    args = parser.parse_args()
    BASE = args.base
    suffix = uuid.uuid4().hex[:6]

    st, project = req("POST", "/projects/", body={"name": f"真实Provider验证 {suffix}", "description": "Qiniu + OpenRouter 真实链路"})
    if st != 201:
        raise SystemExit(f"创建项目失败: {project}")
    pid = project["id"]
    print(f"项目: {pid}")

    payload = "\n".join(json.dumps(r, ensure_ascii=False) for r in QA_ROWS).encode("utf-8")
    st, ds = req(
        "POST", "/datasets/upload",
        body={"project_id": pid, "name": "真实QA", "format": "jsonl", "task_type": "qa",
              "input_fields": '["question"]', "expected_fields": '["answer"]', "metadata_fields": "[]"},
        files={"file": ("real.jsonl", payload)},
    )
    ds_id = ds["id"]
    st, bench = req("POST", "/benchmarks/", body={"project_id": pid, "name": "精确匹配", "type": "qa", "metric": "exact_match_ci"})
    bench_id = bench["id"]
    st, prompt = req("POST", "/prompts/", body={
        "project_id": pid, "name": "简洁回答",
        "template": "请直接回答下面的问题，只输出答案本身，不要解释：\n{question}",
    })
    prompt_id = prompt["id"]

    providers = [
        ("qiniu", "deepseek/deepseek-v4-flash", "Qiniu DeepSeek V4 Flash"),
        ("openrouter", "openai/gpt-4o-mini", "OpenRouter GPT-4o mini"),
    ]
    model_ids = []
    for provider, model_slug, label in providers:
        st, models = req("GET", "/models/")
        existing = next(
            (m for m in models.get("items", []) if m["provider"] == provider and m["model_id"] == model_slug),
            None,
        )
        if existing is not None:
            model = existing
            print(f"[REUSE] {label}: {model['id']}")
        else:
            st, model = req("POST", "/models/", body={
                "name": f"{label} {suffix}", "provider": provider, "model_id": model_slug,
                "context_length": 32768, "pricing": {"input_per_1k": 0.0, "output_per_1k": 0.0},
                "capabilities": ["qa"],
            })
        if st not in (200, 201):
            print(f"[SKIP] 注册 {label} 失败: {model}")
            continue
        st, exp = req("POST", "/experiments/", body={
            "project_id": pid, "name": f"真实实验-{label}", "dataset_id": ds_id,
            "benchmark_id": bench_id, "prompt_id": prompt_id, "model_id": model["id"],
        })
        exp_id = exp["id"]
        st, _ = req("POST", f"/experiments/{exp_id}/run", body={})
        done = wait_done(exp_id)
        st, rows = req("GET", f"/experiments/{exp_id}/results")
        row_list = rows if isinstance(rows, list) else []
        errors = sum(1 for r in row_list if r.get("error"))
        status = done.get("status")
        acc = done.get("accuracy", 0.0)
        cost = done.get("total_cost", 0.0)
        print(f"--- {label}: status={status} acc={acc:.2%} errors={errors} cost=${cost:.4f}")
        if status in ("failed", "cancelled"):
            print("    error:", done.get("error"))
        elif row_list:
            ok_rows = [r for r in row_list if r.get("error") is None]
            sample = ok_rows[0] if ok_rows else row_list[0]
            print("    sample output:", str(sample.get("output"))[:100])

    for mid in model_ids:
        req("DELETE", f"/models/{mid}")
    print("项目保留:", pid)


if __name__ == "__main__":
    main()
