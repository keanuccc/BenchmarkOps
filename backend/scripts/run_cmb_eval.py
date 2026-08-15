"""CMB 中文医疗问答真实模型评测（白盒、可复现版）。

使用公开 CMB 中文医疗基准（Apache-2.0）中的单项选择题与多项选择题，
在 BenchmarkOps 上通过七牛云 AI 网关运行真实模型，并生成：
  - results.json（含数据哈希、提示词/采样快照、逐模型结果、显著性检验）
  - report.md / report.html / report.pdf

数据文件：sample-data/cmb_medical_eval/

用法：
  python scripts/run_cmb_eval.py
  python scripts/run_cmb_eval.py --limit 10
  python scripts/run_cmb_eval.py --no-multi
  python scripts/run_cmb_eval.py --include-openrouter
  python scripts/run_cmb_eval.py --max-tokens 32
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "sample-data" / "cmb_medical_eval"
OUT_DIR = ROOT / "docs" / "cmb-medical-eval"
BASE = os.environ.get("BENCHMARKOPS_API", "http://localhost:8000/api/v1")
TOKEN = os.environ.get("BENCHMARKOPS_TOKEN", "")

# 默认仅使用七牛云 AI 网关的真实模型；OpenRouter 可选，但会真实产生费用。
REAL_MODELS: dict[str, dict] = {
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
}

OPENROUTER_MODELS: dict[str, dict] = {
    "GPT-4o mini (OpenRouter)": {
        "provider": "openrouter",
        "model_id": "openai/gpt-4o-mini",
        "pricing": {"input_per_1k": 0.15, "output_per_1k": 0.60},
    },
}

SINGLE_PROMPT = (
    "你是严格的中国医学考试出题考官。请阅读下面的单项选择题，"
    "从 A/B/C/D/E 中选出唯一正确选项，只输出选项字母，不要输出任何解释。\n\n"
    "题目：\n{question}\n\n答案："
)
MULTI_PROMPT = (
    "你是严格的中国医学考试出题考官。请阅读下面的多项选择题，"
    "选出所有正确选项。只输出选项字母，并用英文逗号分隔，例如：A,C,D。"
    "不要输出任何解释。\n\n题目：\n{question}\n\n答案："
)


def _gateway_key_present(provider: str) -> bool:
    env_path = ROOT / "backend" / ".env"
    if not env_path.exists():
        return False
    key_name = {
        "qiniu": "QINIU_API_KEY",
        "openrouter": "OPENROUTER_API_KEY",
        "deepseek": "DEEPSEEK_API_KEY",
    }.get(provider, "QINIU_API_KEY")
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


def req(method: str, path: str, *, body=None, files=None, raw: bool = False, retries: int = 5):
    url = BASE + path
    headers = _headers()
    data = None
    if files is not None:
        boundary = "----cmbevalbnd"
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

    last_err: Exception | None = None
    for attempt in range(retries + 1):
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=300) as resp:
                content = resp.read()
                if raw:
                    return resp.status, content
                return resp.status, (json.loads(content) if content else None)
        except urllib.error.HTTPError as e:
            if e.code >= 500 and attempt < retries:
                time.sleep(min(2 ** attempt, 10))
                continue
            if raw:
                return e.code, e.read()
            return e.code, e.read().decode("utf-8", "replace")[:500]
        except urllib.error.URLError as e:
            last_err = e
            if attempt < retries:
                time.sleep(min(2 ** attempt, 10))
                continue
    raise SystemExit(f"无法连接后端 {BASE}：{last_err}")


def _jsonl_rows(name: str, limit: int | None) -> list[dict]:
    with open(DATA_DIR / name, encoding="utf-8") as f:
        rows = [json.loads(line) for line in f if line.strip()]
    return rows if limit is None else rows[:limit]


def wait_done(experiment_id: str, timeout_s: int = 2400) -> dict:
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


def upload_dataset(
    pid: str,
    fname: str,
    name: str,
    desc: str,
    task: str,
    inp: list,
    exp: list,
    meta: list,
    limit: int | None,
    answer_policy: dict | None = None,
) -> dict:
    rows = _jsonl_rows(fname, limit)
    payload = ("\n".join(json.dumps(r, ensure_ascii=False) for r in rows)).encode("utf-8")
    body = {
        "project_id": pid,
        "name": name,
        "description": desc,
        "format": "jsonl",
        "task_type": task,
        "input_fields": json.dumps(inp),
        "expected_fields": json.dumps(exp),
        "metadata_fields": json.dumps(meta),
    }
    if answer_policy:
        body["answer_policy"] = json.dumps(answer_policy)
    st, ds = req(
        "POST", "/datasets/upload",
        body=body,
        files={"file": (fname, payload, "application/jsonl")},
    )
    if st >= 400:
        raise SystemExit(f"上传数据集 {fname} 失败: {ds}")
    return {
        "id": ds["id"],
        "rows": ds.get("row_count", len(rows)),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def _mcnemar_p(b: int, c: int) -> float:
    """精确双侧 McNemar 检验 p 值。"""
    n = b + c
    if n == 0:
        return 1.0
    low = min(b, c)
    p = 0.0
    for k in range(low + 1):
        p += math.comb(n, k)
    p *= 0.5 ** n
    return min(1.0, 2.0 * p)


def _wilson_ci(correct: int, total: int) -> tuple[float, float]:
    """Wilson 95% 置信区间，用于小样本准确率表达。"""
    if total == 0:
        return 0.0, 1.0
    z = 1.959963984540054
    p = correct / total
    denom = 1 + z * z / total
    center = (p + z * z / (2 * total)) / denom
    margin = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denom
    return max(0.0, center - margin), min(1.0, center + margin)


def _result_rows(experiment_id: str) -> list[dict]:
    st, rows = req("GET", f"/experiments/{experiment_id}/results")
    if isinstance(rows, list):
        return rows
    if isinstance(rows, dict):
        return rows.get("items", [])
    return []


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None, help="每个数据集最多行数")
    parser.add_argument("--models", default=None, help="逗号分隔的模型展示名")
    parser.add_argument("--include-openrouter", action="store_true", help="追加 OpenRouter 模型（会产生费用）")
    parser.add_argument("--no-multi", action="store_true", help="跳过多项选择题")
    parser.add_argument("--max-tokens", type=int, default=None, help="每次模型调用最大输出 token")
    args = parser.parse_args()

    tag = uuid.uuid4().hex[:6]
    candidates = dict(REAL_MODELS)
    if args.include_openrouter:
        candidates.update(OPENROUTER_MODELS)
    if args.models is None:
        chosen = {k: v for k, v in candidates.items() if _gateway_key_present(v["provider"])}
        skipped = {k: v for k, v in candidates.items() if not _gateway_key_present(v["provider"])}
    else:
        wanted = args.models.split(",")
        chosen = {k: v for k, v in candidates.items() if k in wanted and _gateway_key_present(v["provider"])}
        skipped = {k: v for k, v in candidates.items() if k in wanted and not _gateway_key_present(v["provider"])}

    if not chosen:
        raise SystemExit("没有可用的模型：请先在 backend/.env 配置 QINIU_API_KEY")

    st, proj = req(
        "POST", "/projects/",
        body={
            "name": f"CMB 中文医疗问答评测 {tag}",
            "description": "公开 CMB 中文医疗基准选择题 x 真实模型对比评测",
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
    if skipped:
        print(f"   跳过未配置密钥的模型: {list(skipped)}")

    datasets: list[tuple[str, str, str, str, list, list, list, dict | None, str]] = [
        (
            "cmb-medical-qa.jsonl",
            "CMB 中文医疗问答（单项选择题）",
            "来自公开 CMB 基准的医疗单选题，答案为选项字母",
            "qa",
            ["question"],
            ["answer"],
            ["subject", "exam_type", "exam_class", "source_id"],
            None,
            SINGLE_PROMPT,
        )
    ]
    if not args.no_multi:
        datasets.append(
            (
                "cmb-medical-multi-qa.jsonl",
                "CMB 中文医疗问答（多项选择题）",
                "来自公开 CMB 基准的医疗多选题，答案为选项字母集合",
                "qa",
                ["question"],
                ["answer"],
                ["subject", "exam_type", "exam_class", "source_id"],
                {"multi_answer": "set", "reject_extra": True},
                MULTI_PROMPT,
            )
        )

    ds_info: dict[str, dict] = {}
    for fname, name, desc, task, inp, exp, meta, answer_policy, _ in datasets:
        ds_info[fname] = upload_dataset(
            pid, fname, name, desc, task, inp, exp, meta, args.limit, answer_policy
        )
    print(f"[3] 数据集: { {k: v['rows'] for k, v in ds_info.items()} }")

    st, bm = req(
        "POST", "/benchmarks/",
        body={
            "project_id": pid,
            "name": "CMB 选项精确匹配",
            "type": "qa",
            "metric": "exact_match_ci",
            "description": "模型输出须与标准答案选项字母完全一致（忽略大小写；多选按集合匹配）",
        },
    )
    if st != 201:
        raise SystemExit(f"创建基准失败: {bm}")
    bench_id = bm["id"]
    print("[4] 基准就绪")

    prompt_ids: dict[str, str] = {}
    prompt_templates: dict[str, str] = {}
    for fname, name, desc, task, inp, exp, meta, answer_policy, template in datasets:
        prompt_name = f"提示词-CMB-{'多选' if answer_policy else '单选'}"
        st, pr = req(
            "POST", "/prompts/",
            body={"project_id": pid, "name": prompt_name, "template": template},
        )
        if st not in (200, 201):
            raise SystemExit(f"创建提示词失败: {pr}")
        prompt_ids[fname] = pr["id"]
        prompt_templates[fname] = template
    print("[5] 提示词就绪")

    experiment_ids: list[str] = []
    experiment_meta: dict[str, dict] = {}
    for fname, name, desc, task, inp, exp, meta, answer_policy, _ in datasets:
        for model_name in chosen:
            body = {
                "project_id": pid,
                "name": f"{model_name} | {fname.split('.')[0]}",
                "dataset_id": ds_info[fname]["id"],
                "benchmark_id": bench_id,
                "prompt_id": prompt_ids[fname],
                "model_id": model_ids[model_name],
            }
            if "V4" in model_name:
                default_max_tokens = 1024
            else:
                default_max_tokens = 64 if answer_policy else 32
            max_tokens = args.max_tokens if args.max_tokens is not None else default_max_tokens
            params = {"max_tokens": max_tokens}
            if "V4" in model_name:
                params["extra"] = {"enable_thinking": False}
            body["params"] = params
            st, exp = req("POST", "/experiments/", body=body)
            if st != 201:
                print(f"  创建实验失败: {exp}")
                continue
            eid = exp["id"]
            experiment_ids.append(eid)
            experiment_meta[eid] = {
                "model": model_name,
                "dataset": fname,
                "provider": chosen[model_name]["provider"],
                "model_id": chosen[model_name]["model_id"],
            }
            req("POST", f"/experiments/{eid}/run", body={})

    done_by_id: dict[str, dict] = {}
    for eid in experiment_ids:
        done_by_id[eid] = wait_done(eid)

    results: dict[str, dict] = {}
    rows_by_key: dict[str, list[dict]] = {}
    for eid, meta in experiment_meta.items():
        done = done_by_id.get(eid, {})
        rows = _result_rows(eid)
        errors = sum(1 for r in rows if r.get("error"))
        wrong_rows = [
            r for r in rows
            if r.get("error") or (r.get("score") is not None and r.get("score") < 1)
        ]
        key = f"{meta['model']}|{meta['dataset']}"
        results[key] = {
            "experiment_id": eid,
            "dataset": meta["dataset"],
            "model": meta["model"],
            "provider": meta["provider"],
            "model_id": meta["model_id"],
            "status": done.get("status"),
            "accuracy": done.get("accuracy", 0.0),
            "cells_done": done.get("cells_done", 0),
            "rows_total": done.get("rows_total", 0),
            "errors": errors,
            "total_cost": done.get("total_cost", 0.0),
            "total_tokens": done.get("total_tokens", 0),
            "avg_latency_ms": done.get("avg_latency_ms", 0.0),
            "wrong_samples": [
                {
                    "row_idx": r.get("row_idx"),
                    "expected": r.get("expected"),
                    "output": r.get("output"),
                    "cleaned_prediction": r.get("cleaned_prediction"),
                    "score_reason": r.get("score_reason"),
                    "error": r.get("error"),
                }
                for r in wrong_rows[:20]
            ],
        }
        rows_by_key[key] = rows
        print(
            f"  实验 {meta['model']} | {meta['dataset']}: {done.get('status')} "
            f"acc={done.get('accuracy', 0.0):.2%} "
            f"rows={done.get('cells_done', 0)}/{done.get('rows_total', 0)} "
            f"errors={errors}"
        )

    wrong_samples_all = {}
    for key, rows in rows_by_key.items():
        wrong = [
            {
                "row_idx": r.get("row_idx"),
                "expected": r.get("expected"),
                "output": r.get("output"),
                "cleaned_prediction": r.get("cleaned_prediction"),
                "score": r.get("score"),
                "score_reason": r.get("score_reason"),
                "error": r.get("error"),
            }
            for r in rows
            if r.get("error") or (r.get("score") is not None and r.get("score") < 1)
        ]
        wrong_samples_all[key] = wrong
    (OUT_DIR / "wrong_samples.json").write_text(
        json.dumps(wrong_samples_all, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    statistics: dict[str, dict] = {}
    for fname, *_ in datasets:
        model_names = list(chosen)
        if len(model_names) != 2:
            continue
        a, b = model_names
        key_a = f"{a}|{fname}"
        key_b = f"{b}|{fname}"
        rows_a = {r.get("row_idx"): (r.get("score") or 0.0) >= 1.0 for r in rows_by_key.get(key_a, [])}
        rows_b = {r.get("row_idx"): (r.get("score") or 0.0) >= 1.0 for r in rows_by_key.get(key_b, [])}
        common = sorted(set(rows_a) & set(rows_b))
        b_discord = sum(1 for idx in common if rows_a[idx] and not rows_b[idx])
        c_discord = sum(1 for idx in common if not rows_a[idx] and rows_b[idx])
        total = len(common)
        stats = {
            "paired_rows": total,
            "model_a": a,
            "model_b": b,
            "mcnemar_p": _mcnemar_p(b_discord, c_discord),
            "discordant_a_correct_b_wrong": b_discord,
            "discordant_a_wrong_b_correct": c_discord,
        }
        for key, label in ((key_a, a), (key_b, b)):
            r = results.get(key, {})
            correct = int(round((r.get("accuracy") or 0.0) * (r.get("rows_total") or 0)))
            ci = _wilson_ci(correct, r.get("rows_total") or 0)
            stats[f"{label}_wilson_ci"] = {
                "accuracy": r.get("accuracy", 0.0),
                "lower": ci[0],
                "upper": ci[1],
            }
        statistics[fname] = stats

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    meta_out = {
        "project_id": pid,
        "project_name": proj["name"],
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "data_source": {
            "name": "CMB: A Comprehensive Medical Benchmark in Chinese",
            "license": "Apache-2.0",
            "questions_url": "https://raw.githubusercontent.com/FreedomIntelligence/CMB/main/data/CMB.zip",
            "answers_url": "https://raw.githubusercontent.com/FreedomIntelligence/CMB/main/data/CMB-test-choice-answer.json",
        },
        "sampling": {"seed": 42, "per_exam_class": 10},
        "datasets": {k: {"rows": v["rows"], "sha256": v["sha256"]} for k, v in ds_info.items()},
        "prompts": prompt_templates,
        "models": {k: {**v, "model_db_id": model_ids[k]} for k, v in chosen.items()},
        "skipped_models": skipped,
        "results": results,
        "statistics": statistics,
    }
    (OUT_DIR / "results.json").write_text(
        json.dumps(meta_out, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("[6] results.json 已写入 docs/cmb-medical-eval/")

    st, report = req(
        "POST", "/reports/generate",
        body={
            "project_id": pid,
            "experiment_ids": experiment_ids,
            "title": "CMB 中文医疗问答真实模型评测报告",
            "statistics": statistics,
        },
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
