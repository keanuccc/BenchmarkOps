"""真实模型跨网关评测（Real-World Eval）。

用 C-Eval / THUCNews 真实数据集，在 BenchmarkOps 上跑多个真实模型
（七牛云网关 + OpenRouter 网关），生成对比报告（md/html/pdf）与结果 JSON。

用法：
  python scripts/run_real_eval.py                     # 默认 2 数据集 x 4 模型
  python scripts/run_real_eval.py --limit 10          # 每数据集限 10 行（冒烟）
  python scripts/run_real_eval.py --models deepseek/deepseek-v4-flash,openai/gpt-4o-mini
  python scripts/run_real_eval.py --include-coding    # 追加 HumanEval 代码评测
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "sample-data" / "real-world"
OUT_DIR = ROOT / "docs" / "real-world-eval"
BASE = os.environ.get("BENCHMARKOPS_API", "http://localhost:8000/api/v1")
TOKEN = os.environ.get("BENCHMARKOPS_TOKEN", "")

# 国产真实模型：key = 展示名, value = (provider, model_id, pricing, 说明)
# 说明：默认 5 个国产模型，覆盖 DeepSeek 官方直连与七牛云双网关；
# 未配置对应网关 Key 的模型会被自动跳过。
REAL_MODELS: dict[str, dict] = {
    "DeepSeek-V3 (DeepSeek)": {
        "provider": "deepseek",
        "model_id": "deepseek-chat",
        "pricing": {"input_per_1k": 0.14, "output_per_1k": 0.28},
    },
    "DeepSeek-R1 (DeepSeek)": {
        "provider": "deepseek",
        "model_id": "deepseek-reasoner",
        "pricing": {"input_per_1k": 0.55, "output_per_1k": 2.19},
    },
    "DeepSeek V4 Flash (Qiniu)": {
        "provider": "qiniu",
        "model_id": "deepseek/deepseek-v4-flash",
        "pricing": {"input_per_1k": 0.0, "output_per_1k": 0.0},
    },
    "DeepSeek V3 (Qiniu)": {
        "provider": "qiniu",
        "model_id": "deepseek-v3",
        "pricing": {"input_per_1k": 0.0, "output_per_1k": 0.0},
    },
    "Doubao Seed 2.0 Pro (Qiniu)": {
        "provider": "qiniu",
        "model_id": "doubao-seed-2.0-pro",
        "pricing": {"input_per_1k": 0.0, "output_per_1k": 0.0},
    },
}


def _gateway_key_present(provider: str) -> bool:
    """检查 backend/.env 中对应网关 Key 是否已配置（避免把 Mock 结果混入真实评测）。"""
    env_path = ROOT / "backend" / ".env"
    if not env_path.exists():
        return False
    key_name = {
        "deepseek": "DEEPSEEK_API_KEY",
        "openrouter": "OPENROUTER_API_KEY",
        "qiniu": "QINIU_API_KEY",
    }.get(provider, "OPENROUTER_API_KEY")
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith(key_name + "="):
            value = line.split("=", 1)[1].strip().strip('"').strip("'")
            return bool(value)
    return False


def _headers() -> dict:
    h = {"Content-Type": "application/json"}
    if TOKEN:
        h["Authorization"] = f"Bearer {TOKEN}"
    return h


def req(method: str, path: str, *, body=None, files=None, raw: bool = False):
    url = BASE + path
    headers = _headers()
    data = None
    if files is not None:
        boundary = "----realworldbnd"
        parts = []
        for field, val in body.items():
            parts.append(
                f'--{boundary}\r\nContent-Disposition: form-data; name="{field}"\r\n\r\n{val}\r\n'.encode()
            )
        for fld, (fname, fbytes, ctype) in files.items():
            parts.append(
                f'--{boundary}\r\nContent-Disposition: form-data; name="{fld}"; filename="{fname}"\r\n'
                f"Content-Type: {ctype}\r\n\r\n".encode() + fbytes + b"\r\n"
            )
        parts.append(f"--{boundary}--\r\n".encode())
        data = b"".join(parts)
        headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
    elif body is not None:
        data = json.dumps(body).encode()
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=240) as resp:
            content = resp.read()
            if raw:
                return resp.status, content
            return resp.status, (json.loads(content) if content else None)
    except urllib.error.HTTPError as e:
        if raw:
            return e.code, e.read()
        return e.code, e.read().decode("utf-8", "replace")[:500]
    except urllib.error.URLError as e:
        raise SystemExit(f"无法连接后端 {BASE}：{e}") from e


def _jsonl_rows(name: str, limit: int | None) -> list[dict]:
    with open(DATA_DIR / name, encoding="utf-8") as f:
        rows = [json.loads(line) for line in f if line.strip()]
    return rows if limit is None else rows[:limit]


def wait_done(experiment_id: str, timeout_s: int = 1800) -> dict:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        st, exp = req("GET", f"/experiments/{experiment_id}")
        if st == 200 and exp.get("status") in ("completed", "partial", "failed", "cancelled"):
            return exp
        time.sleep(5)
    return {"status": "timeout"}


def ensure_model(name: str, spec: dict) -> str:
    st, models = req("GET", "/models/")
    items = models.get("items", models) if isinstance(models, dict) else (models or [])
    for m in items:
        if m.get("provider") == spec["provider"] and m.get("model_id") == spec["model_id"]:
            return m["id"]
    st, created = req(
        "POST", "/models/",
        body={
            "name": name,
            "provider": spec["provider"],
            "model_id": spec["model_id"],
            "context_length": 128000,
            "pricing": spec["pricing"],
            "capabilities": ["qa", "classification", "coding"],
        },
    )
    if st not in (200, 201):
        raise SystemExit(f"注册模型 {name} 失败: {created}")
    return created["id"]


def upload_dataset(pid: str, fname: str, name: str, desc: str, task: str,
                   inp: list, exp: list, meta: list, limit: int | None) -> dict:
    rows = _jsonl_rows(fname, limit)
    payload = ("\n".join(json.dumps(r, ensure_ascii=False) for r in rows)).encode("utf-8")
    st, ds = req(
        "POST", "/datasets/upload",
        body={
            "project_id": pid,
            "name": name,
            "description": desc,
            "format": "jsonl",
            "task_type": task,
            "input_fields": json.dumps(inp),
            "expected_fields": json.dumps(exp),
            "metadata_fields": json.dumps(meta),
        },
        files={"file": (fname, payload, "application/jsonl")},
    )
    if st >= 400:
        raise SystemExit(f"上传数据集 {fname} 失败: {ds}")
    return {"id": ds["id"], "rows": ds.get("row_count", len(rows))}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None, help="每个数据集最多行数")
    parser.add_argument("--models", default=None, help="逗号分隔的模型名（匹配展示名）")
    parser.add_argument("--include-coding", action="store_true", help="追加 HumanEval 代码评测")
    parser.add_argument("--only-coding", action="store_true", help="只跑 HumanEval 代码评测")
    args = parser.parse_args()

    tag = uuid.uuid4().hex[:6]
    chosen = REAL_MODELS if args.models is None else {
        k: v for k, v in REAL_MODELS.items() if k in args.models.split(",")
    }
    # 未配置对应网关 Key 的模型直接跳过，避免评测失败污染结果。
    chosen = {k: v for k, v in chosen.items() if _gateway_key_present(v["provider"])}
    if not chosen:
        raise SystemExit("没有可用的模型：请先在 backend/.env 配置 OPENROUTER_API_KEY / QINIU_API_KEY")

    st, proj = req(
        "POST", "/projects/",
        body={
            "name": f"真实模型跨网关评测 {tag}",
            "description": "C-Eval / THUCNews 真实数据集 x 真实模型（七牛 + OpenRouter 双网关）对比评测",
        },
    )
    if st != 201:
        raise SystemExit(f"创建项目失败: {proj}")
    pid = proj["id"]
    print(f"[1] 项目: {proj['name']} ({pid})")

    model_ids: dict[str, str] = {}
    for name, spec in chosen.items():
        model_ids[name] = ensure_model(name, spec)
    print(f"[2] 模型就绪: {list(chosen)}")

    datasets = []
    if not args.only_coding:
        datasets = [
            ("ceval-qa.jsonl", "C-Eval 中文考试真题 (QA)", "真实中文考试选择题，答案为选项字母",
             "qa", ["question"], ["answer"], ["subject"]),
            ("thucnews-classification.jsonl", "THUCNews 新闻分类", "10 类新闻文本真实分类",
             "classification", ["text"], ["answer"], []),
        ]
    if args.include_coding or args.only_coding:
        datasets.append(
            ("humaneval-coding.jsonl", "HumanEval 代码生成", "Python 函数补全（真实执行测试用例）",
             "coding", ["prompt"], ["answer", "tests"], ["entry_point", "task_id"])
        )

    ds_info: dict[str, dict] = {}
    for fname, name, desc, task, inp, exp, meta in datasets:
        ds_info[fname] = upload_dataset(pid, fname, name, desc, task, inp, exp, meta, args.limit)
    print(f"[3] 数据集: { {k: v['rows'] for k, v in ds_info.items()} }")

    benches = {
        "qa": ("C-Eval 选项精确匹配", "qa", "exact_match_ci",
               "模型输出须与标准答案选项字母完全一致（忽略大小写）"),
        "classification": ("THUCNews 类别精确匹配", "classification", "exact_match_ci",
                           "模型输出须与新闻类别标签完全一致"),
        "coding": ("HumanEval 测试用例通过", "coding", "code_pass",
                   "模型输出须通过官方测试用例（真实代码执行，超时 8s）"),
    }
    bench_ids: dict[str, str] = {}
    for task, (name, btype, metric, desc) in benches.items():
        body = {
            "project_id": pid, "name": name, "type": btype,
            "metric": metric, "description": desc,
        }
        if metric == "code_pass":
            body["metric_config"] = {"timeout_seconds": 8}
        st, bm = req("POST", "/benchmarks/", body=body)
        if st != 201:
            raise SystemExit(f"创建基准 {name} 失败: {bm}")
        bench_ids[task] = bm["id"]
    print("[4] 基准就绪")

    prompt_templates = {
        "qa": "你是严格的出题考官。请从 A/B/C/D 中选出唯一正确选项，只输出选项字母，不要输出解释。\n\n题目：\n{question}\n\n答案：",
        "classification": "对下面的新闻文本进行分类，只输出一个类别名称（体育/财经/房产/家居/教育/科技/时政/时尚/游戏/娱乐），不要解释。\n\n文本：{text}\n\n类别：",
        "coding": "请补全下面的 Python 函数，只输出完整代码本身，不要任何解释。\n\n{prompt}",
    }
    prompt_ids: dict[str, str] = {}
    for task, template in prompt_templates.items():
        st, pr = req("POST", "/prompts/", body={
            "project_id": pid, "name": f"提示词-{task}", "template": template,
        })
        if st not in (200, 201):
            raise SystemExit(f"创建提示词 {task} 失败: {pr}")
        prompt_ids[task] = pr["id"]
    print("[5] 提示词就绪")

    pairs = []
    if not args.only_coding:
        pairs = [
            ("ceval-qa.jsonl", "qa"),
            ("thucnews-classification.jsonl", "classification"),
        ]
    if args.include_coding or args.only_coding:
        pairs.append(("humaneval-coding.jsonl", "coding"))

    experiment_ids: list[str] = []
    results: dict[str, dict] = {}
    for fname, task in pairs:
        for name in chosen:
            st, exp = req("POST", "/experiments/", body={
                "project_id": pid,
                "name": f"{name} | {fname.split('.')[0]}",
                "dataset_id": ds_info[fname]["id"],
                "benchmark_id": bench_ids[task],
                "prompt_id": prompt_ids[task],
                "model_id": model_ids[name],
            })
            if st != 201:
                print(f"  创建实验失败: {exp}")
                continue
            eid = exp["id"]
            experiment_ids.append(eid)
            req("POST", f"/experiments/{eid}/run", body={})
            done = wait_done(eid)
            st, rows = req("GET", f"/experiments/{eid}/results")
            row_list = rows if isinstance(rows, list) else []
            errors = sum(1 for r in row_list if r.get("error"))
            results[f"{name}|{fname}"] = {
                "experiment_id": eid,
                "dataset": fname,
                "model": name,
                "provider": chosen[name]["provider"],
                "status": done.get("status"),
                "accuracy": done.get("accuracy", 0.0),
                "cells_done": done.get("cells_done", 0),
                "rows_total": done.get("rows_total", 0),
                "errors": errors,
                "total_cost": done.get("total_cost", 0.0),
                "total_tokens": done.get("total_tokens", 0),
                "avg_latency_ms": done.get("avg_latency_ms", 0.0),
            }
            print(
                f"  实验 {name} | {fname}: {done.get('status')} "
                f"acc={done.get('accuracy', 0.0):.2%} "
                f"rows={done.get('cells_done', 0)}/{done.get('rows_total', 0)} "
                f"errors={errors}"
            )

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    meta = {
        "project_id": pid,
        "project_name": proj["name"],
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "models": chosen,
        "results": results,
    }
    (OUT_DIR / "results.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("[6] results.json 已写入 docs/real-world-eval/")

    st, report = req(
        "POST", "/reports/generate",
        body={"project_id": pid, "experiment_ids": experiment_ids, "title": "真实模型跨网关评测报告"},
    )
    if st == 201:
        rid = report["id"]
        for fmt, ext, path in (
            ("md", "md", OUT_DIR / "report.md"),
            ("html", "html", OUT_DIR / "report.html"),
            ("pdf", "pdf", OUT_DIR / "report.pdf"),
        ):
            if fmt == "pdf":
                s, content = req("GET", f"/reports/{rid}/export/pdf", raw=True)
            elif fmt == "html":
                s, content = req("GET", f"/reports/{rid}/export?format=html", raw=True)
            else:
                s, content = req("GET", f"/reports/{rid}/export", raw=True)
            if s == 200:
                path.write_bytes(content)
                print(f"  报告导出 {ext}: {path}")
    else:
        print(f"  报告生成失败: {report}")

    print(f"\n完成。项目 id={pid}，前端 http://localhost:3000 可查看。")


if __name__ == "__main__":
    main()
