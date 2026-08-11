"""一键把 sample-data/real-world 下的真实数据集导入 BenchmarkOps 并跑起来。

前置条件：后端已在 http://localhost:8000 运行（见项目 README）。
用法：
  python upload_real_world.py            # 导入 + 自动创建实验并运行
  python upload_real_world.py --no-run   # 只导入数据/基准/提示词，不运行实验
"""
from __future__ import annotations

import argparse
import json
import os
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.environ.get("BENCHMARKOPS_API", "http://localhost:8000/api/v1")
TOKEN = os.environ.get("BENCHMARKOPS_TOKEN", "")


def _headers() -> dict:
    h = {"Content-Type": "application/json"}
    if TOKEN:
        h["Authorization"] = f"Bearer {TOKEN}"
    return h


def _req(method: str, path: str, *, body=None, files=None):
    url = BASE + path
    data = None
    headers = _headers()
    if files is not None:
        boundary = "----realworldbnd"
        parts = []
        for field, val in body.items():
            parts.append(
                f"--{boundary}\r\nContent-Disposition: form-data; name=\"{field}\"\r\n\r\n{val}\r\n".encode()
            )
        for fld, (fname, fbytes, ctype) in files.items():
            parts.append(
                f"--{boundary}\r\nContent-Disposition: form-data; name=\"{fld}\"; filename=\"{fname}\"\r\n"
                f"Content-Type: {ctype}\r\n\r\n".encode() + fbytes + b"\r\n"
            )
        parts.append(f"--{boundary}--\r\n".encode())
        data = b"".join(parts)
        headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
    else:
        if body is not None:
            data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            raw = resp.read().decode()
            return resp.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:500]
    except urllib.error.URLError as e:
        raise SystemExit(f"无法连接后端 {BASE}：{e}") from e


def _jsonl_rows(name: str) -> list[dict]:
    with open(os.path.join(HERE, name), encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-run", action="store_true", help="只导入，不创建/运行实验")
    args = parser.parse_args()

    # 1) 项目
    st, proj = _req(
        "POST", "/projects/",
        body={
            "name": "真实场景评测 Real-World",
            "description": "真实公开数据评测：C-Eval 中文考试真题 / THUCNews 新闻分类 / HumanEval 代码生成",
        },
    )
    if st >= 400:
        raise SystemExit(f"创建项目失败: {proj}")
    pid = proj["id"]
    print(f"[1/7] 项目创建成功 id={pid}")

    # 2) 模型（幂等：已存在会报错，忽略即可）
    _req("POST", "/models/seed", body={})
    st, resp = _req("GET", "/models/")
    models = resp["items"] if isinstance(resp, dict) and "items" in resp else (resp or [])
    enabled = [m for m in models if m.get("is_active", True)]
    print(f"[2/7] 模型就绪，可用 {len(enabled)} 个: {[m['name'] for m in enabled[:3]]} ...")

    # 3) 数据集
    datasets = [
        (
            "ceval-qa.jsonl", "C-Eval 中文考试真题 (QA)",
            "真实中文考试选择题（计算机网络/语文/高数），答案为标准选项字母",
            "qa", ["question"], ["answer"], ["subject"],
        ),
        (
            "thucnews-classification.jsonl", "THUCNews 新闻分类",
            "清华 THUCNews 子集（CNews）10 类新闻文本，真实新闻标题/正文",
            "classification", ["text"], ["answer"], [],
        ),
        (
            "humaneval-coding.jsonl", "HumanEval 代码生成",
            "OpenAI HumanEval 真实 Python 编程题，标准解为期望输出",
            "coding", ["prompt"], ["answer"], ["entry_point", "task_id"],
        ),
    ]
    dataset_ids: dict[str, str] = {}
    dataset_names: dict[str, str] = {}
    for fname, name, desc, task, inp, exp, meta in datasets:
        with open(os.path.join(HERE, fname), "rb") as f:
            fbytes = f.read()
        st, ds = _req(
            "POST", "/datasets/upload",
            body={
                "project_id": pid,
                "name": name,
                "description": desc,
                "tags": "real-world," + task,
                "format": "jsonl",
                "task_type": task,
                "input_fields": json.dumps(inp),
                "expected_fields": json.dumps(exp),
                "metadata_fields": json.dumps(meta),
            },
            files={"file": (fname, fbytes, "application/jsonl")},
        )
        if st >= 400:
            raise SystemExit(f"上传数据集 {fname} 失败: {ds}")
        dataset_ids[fname] = ds["id"]
        dataset_names[fname] = name
        print(f"[3/7] 数据集 {fname}: id={ds['id']} rows={ds.get('row_count', '?')}")

    # 4) 基准
    benchmarks = [
        ("C-Eval 选项精确匹配", "qa", "exact_match_ci",
         "模型输出须与标准答案选项字母完全一致（忽略大小写）"),
        ("THUCNews 类别精确匹配", "classification", "exact_match_ci",
         "模型输出须与新闻类别标签完全一致"),
        ("HumanEval 标准解包含", "coding", "contains",
         "模型输出须包含标准参考实现（真实模型通常只能部分命中）"),
    ]
    bench_ids: dict[str, str] = {}
    for name, btype, metric, desc in benchmarks:
        st, bm = _req("POST", "/benchmarks/", body={
            "project_id": pid, "name": name, "type": btype,
            "metric": metric, "description": desc,
        })
        if st >= 400:
            raise SystemExit(f"创建基准 {name} 失败: {bm}")
        bench_ids[name] = bm["id"]
        print(f"[4/7] 基准 {name}: id={bm['id']}")

    # 5) 提示词
    prompts = [
        (
            "C-Eval 考官提示词",
            "你是严格的出题考官。请从 A/B/C/D 中选出唯一正确选项，"
            "只输出选项字母，不要输出解释。\n\n题目：\n{question}\n\n答案：",
            "约束模型只输出选项字母，适配 exact_match_ci",
        ),
        (
            "THUCNews 分类提示词",
            "对下面的新闻文本进行分类，只输出一个类别名称"
            "（体育/财经/房产/家居/教育/科技/时政/时尚/游戏/娱乐），不要解释。\n\n"
            "文本：{text}\n\n类别：",
            "约束模型只输出类别名，适配 exact_match_ci",
        ),
        (
            "HumanEval 代码提示词",
            "请补全下面的 Python 函数，只输出完整代码本身，不要任何解释。\n\n{prompt}",
            "代码补全提示词，适配 contains 指标",
        ),
    ]
    prompt_ids: dict[str, str] = {}
    for name, template, desc in prompts:
        st, pr = _req("POST", "/prompts/", body={
            "project_id": pid, "name": name, "template": template, "description": desc,
        })
        if st >= 400:
            raise SystemExit(f"创建提示词 {name} 失败: {pr}")
        prompt_ids[name] = pr["id"]
        print(f"[5/7] 提示词 {name}: id={pr['id']}")

    if args.no_run:
        print("\n完成（未运行实验）。可用 --no-run 之外的模式自动创建并运行实验。")
        return

    # 6) 每个数据集挑前 2 个模型建实验
    pair = [
        ("ceval-qa.jsonl", bench_ids["C-Eval 选项精确匹配"], prompt_ids["C-Eval 考官提示词"]),
        ("thucnews-classification.jsonl", bench_ids["THUCNews 类别精确匹配"], prompt_ids["THUCNews 分类提示词"]),
        ("humaneval-coding.jsonl", bench_ids["HumanEval 标准解包含"], prompt_ids["HumanEval 代码提示词"]),
    ]
    chosen = enabled[:2]
    experiment_ids: list[str] = []
    for fname, bm_id, pr_id in pair:
        for i, model in enumerate(chosen, 1):
            st, ex = _req("POST", "/experiments/", body={
                "project_id": pid,
                "name": f"{dataset_names[fname]} x {model['name']}",
                "dataset_id": dataset_ids[fname],
                "benchmark_id": bm_id,
                "prompt_id": pr_id,
                "model_id": model["id"],
            })
            if st >= 400:
                print(f"  创建实验失败: {ex}")
                continue
            experiment_ids.append(ex["id"])
            print(f"[6/7] 实验 {ex['name']}: id={ex['id']}")

    # 7) 运行
    for eid in experiment_ids:
        st, run = _req("POST", f"/experiments/{eid}/run", body={})
        print(f"[7/7] 触发运行 {eid}: {st} {run if isinstance(run, str) else 'ok'}")

    print("\n全部完成。前端打开 http://localhost:3000 进入项目「真实场景评测 Real-World」查看。")


if __name__ == "__main__":
    main()
