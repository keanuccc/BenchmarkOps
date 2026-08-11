"""五个评测场景（qa/classification/coding/agent/generation）端到端跑测。

数据来自 sample-data/scenarios/*.jsonl（自造原始数据）。实验使用 mock
provider 模型（离线、确定性、不花真实费用）。跑完后：
1. 校验每个实验的逐行结果；
2. 生成一份平台报告并导出 PDF 到仓库（评测文档素材）。

用法：python scripts/run_scenarios.py [--base http://localhost:8000/api/v1]
"""
from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

BASE = "http://localhost:8000/api/v1"
ROOT = Path(__file__).resolve().parents[2]  # repo root
DATA_DIR = ROOT / "sample-data" / "scenarios"


def req(method: str, path: str, *, body=None, files=None):
    url = BASE + path
    headers = {"User-Agent": "run-scenarios"}
    data = None
    if files is not None:
        boundary = "----scenario"
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


def req_raw(path: str) -> tuple[int, bytes]:
    request = urllib.request.Request(BASE + path, headers={"User-Agent": "run-scenarios"})
    try:
        with urllib.request.urlopen(request, timeout=180) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def wait_done(experiment_id: str) -> dict:
    for _ in range(180):
        st, exp = req("GET", f"/experiments/{experiment_id}")
        if st == 200 and exp.get("status") in (
            "completed", "partial", "failed", "cancelled",
        ):
            return exp
        time.sleep(1)
    return {"status": "timeout"}


def upload_dataset(pid: str, fname: str, name: str, *, task: str, inp: list, exp: list, meta: list | None):
    payload = (DATA_DIR / fname).read_bytes()
    body = {
        "project_id": pid,
        "name": name,
        "format": "jsonl",
        "task_type": task,
        "input_fields": json.dumps(inp),
        "expected_fields": json.dumps(exp),
        "metadata_fields": json.dumps(meta or []),
    }
    st, ds = req(
        "POST", "/datasets/upload", body=body,
        files={"file": (fname, payload)},
    )
    return st, ds


def main() -> None:
    global BASE
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default=BASE)
    args = parser.parse_args()
    BASE = args.base

    results: dict[str, dict] = {}
    run_suffix = uuid.uuid4().hex[:6]

    # 1) 项目
    st, project = req(
        "POST", "/projects/",
        body={"name": f"全场景评测 {run_suffix}", "description": "qa/classification/coding/agent/generation 五场景端到端评测"},
    )
    if st != 201:
        raise SystemExit(f"创建项目失败: {project}")
    pid = project["id"]
    print(f"项目: {project['name']} ({pid})")

    # 2) 数据集
    datasets = [
        ("qa.jsonl", "场景QA-问答", "qa", ["question"], ["answer"], ["category"]),
        ("classification.jsonl", "场景CLASS-分类", "classification", ["text"], ["answer"], ["category"]),
        ("coding.jsonl", "场景CODING-代码", "coding", ["prompt"], ["answer", "tests"], ["entry_point"]),
        ("agent.jsonl", "场景AGENT-工具调用", "agent", ["question"], ["answer", "arguments"], []),
        ("generation.jsonl", "场景GEN-生成", "generation", ["article"], ["answer"], []),
    ]
    ds_ids: dict[str, str] = {}
    for fname, name, task, inp, exp, meta in datasets:
        st, ds = upload_dataset(pid, fname, name, task=task, inp=inp, exp=exp, meta=meta)
        if st not in (200, 201):
            raise SystemExit(f"上传 {fname} 失败: {ds}")
        ds_ids[fname] = ds["id"]
        print(f"  数据集 {fname}: {ds['row_count']} 行")

    # 3) 基准
    benchmarks = [
        ("场景基准 QA", "qa", "exact_match_ci", {}),
        ("场景基准 CLASS", "classification", "exact_match_ci", {}),
        ("场景基准 CODING", "coding", "code_pass", {"timeout_seconds": 5}),
        ("场景基准 AGENT", "agent", "tool_call", {}),
        ("场景基准 GEN", "generation", "f1_token", {}),
    ]
    bench_ids: dict[str, str] = {}
    for name, btype, metric, mcfg in benchmarks:
        st, bench = req(
            "POST", "/benchmarks/",
            body={"project_id": pid, "name": name, "type": btype,
                  "metric": metric, "metric_config": mcfg},
        )
        if st != 201:
            raise SystemExit(f"创建基准 {name} 失败: {bench}")
        bench_ids[btype] = bench["id"]

    # 4) 提示词
    prompts = [
        ("场景提示词 QA", "问题：{question}\n答案：", ["question"]),
        ("场景提示词 CLASS", "请将下面文本分类，只输出类别名：\n{text}\n类别：", ["text"]),
        ("场景提示词 CODING", "{prompt}", ["prompt"]),
        ("场景提示词 AGENT", "{question}", ["question"]),
        ("场景提示词 GEN", "请对下面文章生成一句话摘要：\n{article}\n摘要：", ["article"]),
    ]
    prompt_ids: dict[str, str] = {}
    for name, template, _ in prompts:
        st, pr = req(
            "POST", "/prompts/",
            body={"project_id": pid, "name": name, "template": template},
        )
        if st not in (200, 201):
            raise SystemExit(f"创建提示词 {name} 失败: {pr}")
        prompt_ids[name] = pr["id"]

    # 5) Mock 模型
    st, model = req(
        "POST", "/models/",
        body={
            "name": f"场景评测 Mock {run_suffix}",
            "provider": "mock",
            "model_id": f"scenario-mock-{run_suffix}",
            "context_length": 8192,
            "pricing": {"input_per_1k": 0.0, "output_per_1k": 0.0},
            "capabilities": ["qa", "classification", "coding", "agent", "generation"],
        },
    )
    if st not in (200, 201):
        raise SystemExit(f"注册 Mock 模型失败: {model}")
    model_id = model["id"]

    # 6) 五实验 + 运行
    scenario_map = [
        ("qa", "qa.jsonl", "QA", "场景提示词 QA"),
        ("classification", "classification.jsonl", "CLASS", "场景提示词 CLASS"),
        ("coding", "coding.jsonl", "CODING", "场景提示词 CODING"),
        ("agent", "agent.jsonl", "AGENT", "场景提示词 AGENT"),
        ("generation", "generation.jsonl", "GEN", "场景提示词 GEN"),
    ]
    experiment_ids: list[str] = []
    for btype, fname, label, prompt_name in scenario_map:
        st, exp = req(
            "POST", "/experiments/",
            body={
                "project_id": pid,
                "name": f"场景实验 {label}",
                "dataset_id": ds_ids[fname],
                "benchmark_id": bench_ids[btype],
                "prompt_id": prompt_ids[prompt_name],
                "model_id": model_id,
            },
        )
        if st != 201:
            raise SystemExit(f"创建实验 {label} 失败: {exp}")
        exp_id = exp["id"]
        experiment_ids.append(exp_id)
        req("POST", f"/experiments/{exp_id}/run", body={})
        done = wait_done(exp_id)
        st, rows = req("GET", f"/experiments/{exp_id}/results")
        row_list = rows if isinstance(rows, list) else []
        errors = sum(1 for r in row_list if r.get("error"))
        results[label] = {
            "experiment_id": exp_id,
            "status": done.get("status"),
            "accuracy": done.get("accuracy", 0.0),
            "cells_done": done.get("cells_done", 0),
            "rows_total": done.get("rows_total", 0),
            "errors": errors,
            "total_cost": done.get("total_cost", 0.0),
            "avg_latency_ms": done.get("avg_latency_ms", 0.0),
        }
        print(
            f"  实验 {label}: status={done.get('status')} "
            f"acc={done.get('accuracy', 0.0):.2%} "
            f"rows={done.get('cells_done', 0)}/{done.get('rows_total', 0)} "
            f"errors={errors}"
        )

    # 7) 汇总校验
    print("\n=== 五场景汇总 ===")
    all_ok = True
    for label, r in results.items():
        ok = (
            r["status"] in ("completed", "partial")
            and r["cells_done"] == r["rows_total"]
            and r["errors"] == 0
        )
        all_ok = all_ok and ok
        print(
            f"  {label:>4}: {'PASS' if ok else 'FAIL'}  "
            f"acc={r['accuracy']:.2%} cost=${r['total_cost']:.4f} "
            f"latency={r['avg_latency_ms']:.0f}ms"
        )

    # 8) 平台报告 + PDF 导出（评测文档素材）
    st, report = req(
        "POST", "/reports/generate",
        body={
            "project_id": pid,
            "experiment_ids": experiment_ids,
            "title": "全场景评测报告",
        },
    )
    if st == 201:
        report_id = report["id"]
        out_dir = ROOT / "docs" / "scenario-eval"
        out_dir.mkdir(parents=True, exist_ok=True)
        for fmt, ext, path in (
            ("md", "md", out_dir / "report.md"),
            ("html", "html", out_dir / "report.html"),
            ("pdf", "pdf", out_dir / "report.pdf"),
        ):
            if fmt == "pdf":
                s, content = req_raw(f"/reports/{report_id}/export/pdf")
            elif fmt == "html":
                s, content = req_raw(f"/reports/{report_id}/export?format=html")
            else:
                s, content = req_raw(f"/reports/{report_id}/export")
            if s == 200:
                path.write_bytes(content)
                print(f"  报告导出 {ext}: {path}")
    else:
        print(f"  报告生成失败: {report}")

    print(f"\n项目: {pid}（保留在平台中，可打开前端查看）")
    print(f"模型: {model_id}（保留）")
    raise SystemExit(0 if all_ok else 2)


if __name__ == "__main__":
    main()
