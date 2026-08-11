"""补齐真实评测矩阵：在已有项目上补跑缺失的模型×数据集组合，并生成最终报告。

背景：run_real_eval.py 在跑分类实验时后端进程被外部终止，ceval 全部完成、
分类只完成 1/3。本脚本从 eval.db 的项目里复用数据集/基准/提示词/模型，
只创建缺失的实验，完成后用全部实验生成报告与 results.json。

用法：python scripts/finish_real_eval.py --project <project_id>
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "docs" / "real-world-eval"
BASE = os.environ.get("BENCHMARKOPS_API", "http://127.0.0.1:8001/api/v1")


def req(method: str, path: str, *, body=None, raw=False):
    url = BASE + path
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"}
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=240) as resp:
            content = resp.read()
            if raw:
                return resp.status, content
            return resp.status, (json.loads(content) if content else None)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")[:500]
    except urllib.error.URLError as e:
        raise SystemExit(f"无法连接后端 {BASE}：{e}") from e


def wait_done(eid: str, timeout_s: int = 1800) -> dict:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        st, exp = req("GET", f"/experiments/{eid}")
        if st == 200 and exp.get("status") in ("completed", "partial", "failed", "cancelled"):
            return exp
        time.sleep(5)
    return {"status": "timeout"}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True)
    args = parser.parse_args()
    pid = args.project

    # 现有资源
    st, datasets = req("GET", f"/datasets/?project_id={pid}")
    datasets = datasets.get("items", datasets) if isinstance(datasets, dict) else (datasets or [])
    st, benches = req("GET", f"/benchmarks/?project_id={pid}")
    benches = benches.get("items", benches) if isinstance(benches, dict) else (benches or [])
    st, prompts = req("GET", f"/prompts/?project_id={pid}")
    prompts = prompts.get("items", prompts) if isinstance(prompts, dict) else (prompts or [])
    st, models = req("GET", "/models/")
    models = models.get("items", models) if isinstance(models, dict) else (models or [])
    st, exps = req("GET", f"/experiments/?project_id={pid}")
    exps = exps.get("items", exps) if isinstance(exps, dict) else (exps or [])

    ds_by_name = {d["name"]: d["id"] for d in datasets}
    bench_by_name = {b["name"]: b["id"] for b in benches}
    prompt_by_name = {p["name"]: p["id"] for p in prompts}
    model_by_id = {m["id"]: m for m in models}

    done = {
        (e["model_id"], e["dataset_id"]): e
        for e in exps if e.get("status") in ("completed", "partial")
    }
    targets = [
        ("Doubao Seed 2.0 Pro (Qiniu)", "THUCNews 新闻分类"),
        ("GPT-4o mini (OpenRouter)", "THUCNews 新闻分类"),
    ]

    all_experiment_ids: list[str] = []
    for mname, dsname in targets:
        mid = next(m["id"] for m in models if m["name"] == mname)
        dsid = ds_by_name[dsname]
        if (mid, dsid) in done:
            all_experiment_ids.append(done[(mid, dsid)]["id"])
            continue
        st, exp = req("POST", "/experiments/", body={
            "project_id": pid,
            "name": f"{mname} | {dsname}",
            "dataset_id": dsid,
            "benchmark_id": bench_by_name["THUCNews 类别精确匹配"],
            "prompt_id": prompt_by_name["提示词-classification"],
            "model_id": mid,
        })
        if st != 201:
            print(f"创建实验失败 {mname} x {dsname}: {exp}")
            continue
        eid = exp["id"]
        all_experiment_ids.append(eid)
        req("POST", f"/experiments/{eid}/run", body={})
        done_exp = wait_done(eid)
        print(f"实验 {mname} x {dsname}: {done_exp.get('status')} acc={done_exp.get('accuracy', 0.0):.2%} rows={done_exp.get('cells_done')}/{done_exp.get('rows_total')}")

    # 汇总全部实验
    st, exps = req("GET", f"/experiments/?project_id={pid}")
    exps = exps.get("items", exps) if isinstance(exps, dict) else (exps or [])
    results = {}
    for e in exps:
        mid = e.get("model_id")
        dsid = e.get("dataset_id")
        if mid not in model_by_id or e.get("status") not in ("completed", "partial"):
            continue
        m = model_by_id[mid]
        dsname = next((k for k, v in ds_by_name.items() if v == dsid), dsid)
        results[f"{m['name']}|{dsname}"] = {
            "experiment_id": e["id"],
            "dataset": dsname,
            "model": m["name"],
            "provider": m["provider"],
            "model_id": m["model_id"],
            "status": e["status"],
            "accuracy": e.get("accuracy", 0.0),
            "cells_done": e.get("cells_done", 0),
            "rows_total": e.get("rows_total", 0),
            "total_cost": e.get("total_cost", 0.0),
            "total_tokens": e.get("total_tokens", 0),
            "avg_latency_ms": e.get("avg_latency_ms", 0.0),
        }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "results.json").write_text(
        json.dumps({
            "project_id": pid,
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "results": results,
        }, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("[ok] results.json 已写入")

    st, report = req("POST", "/reports/generate", body={
        "project_id": pid,
        "experiment_ids": [e["id"] for e in exps if e.get("status") in ("completed", "partial")],
        "title": "真实模型跨网关评测报告",
    })
    if st == 201:
        rid = report["id"]
        for fmt, ext, path in (
            ("md", "md", OUT_DIR / "report.md"),
            ("html", "html", OUT_DIR / "report.html"),
            ("pdf", "pdf", OUT_DIR / "report.pdf"),
        ):
            p = f"/reports/{rid}/export"
            if fmt == "pdf":
                p += "/pdf"
            elif fmt == "html":
                p += "?format=html"
            s, content = req("GET", p, raw=True)
            if s == 200:
                path.write_bytes(content)
                print(f"报告导出 {ext}: {path}")
    else:
        print(f"报告生成失败: {report}")


if __name__ == "__main__":
    main()
