"""把 sample-data/complex 下的 4 个数据集 + 4 个基准 + 4 个提示词 上传到 BenchmarkOps。

通过 HTTP 接口创建：
  1) 新建项目「复杂评测套件 v2」
  2) 上传 4 个大数据集（multihop_qa / codegen / classification / summarization）
  3) 创建 4 个复杂基准（不同类型 + 指标）
  4) 创建 4 个复杂提示词（CoT / few-shot / 角色设定 / 代码约束）

用法：uv run python upload_complex.py
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = "http://localhost:8000/api/v1"


def _req(method: str, path: str, *, body=None, files=None):
    url = BASE + path
    data = None
    headers = {}
    if files is not None:
        import email.generator
        boundary = "----benchopbnd"
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
            headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            raw = resp.read().decode()
            return resp.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def main() -> None:
    # 1) 项目
    st, proj = _req("POST", "/projects/", body={"name": "复杂评测套件 v2", "description": "多任务、大数据量的复杂评测：多跳推理 / 代码生成 / 文本分类 / 摘要生成"})
    print("project:", st, proj.get("id") if proj else proj)
    pid = proj["id"]

    # 2) 数据集上传
    datasets = [
        ("multihop_qa.jsonl", "多跳推理QA", "qa", "需要 2~3 步推理的常识/科学/逻辑问题（中文）"),
        ("codegen.jsonl", "代码生成任务", "coding", "跨语言、带约束的编程任务，期望包含关键函数签名"),
        ("classification.jsonl", "文本分类", "classification", "六类新闻文本分类"),
        ("summarization.jsonl", "摘要生成", "generation", "长文本 -> 关键信息摘要"),
    ]
    dataset_ids = {}
    for fname, name, fmt, desc in datasets:
        with open(os.path.join(HERE, fname), "rb") as f:
            fbytes = f.read()
        st, ds = _req(
            "POST", "/datasets/upload",
            body={"project_id": pid, "name": name, "description": desc, "tags": f"complex,{fmt}", "format": "jsonl"},
            files={"file": (fname, fbytes, "application/jsonl")},
        )
        print(f"  dataset[{name}]: {st} id={ds.get('id') if ds else ds} rows={ds.get('row_count') if ds else '?'}")
        if ds:
            dataset_ids[name] = ds["id"]

    # 3) 基准
    benchmarks = [
        ("多跳推理QA基准", "qa", "exact_match_ci", "对多跳推理问题的简短答案做大小写不敏感精确匹配"),
        ("代码生成基准", "coding", "contains", "判定模型输出是否包含期望的关键函数签名/片段"),
        ("文本分类基准", "classification", "exact_match_ci", "对六类新闻文本的分类结果做精确匹配"),
        ("摘要生成基准", "generation", "f1_token", "以 token 级 F1 评估生成摘要与参考摘要的重叠"),
    ]
    bench_ids = {}
    for name, btype, metric, desc in benchmarks:
        st, bm = _req("POST", "/benchmarks/", body={
            "project_id": pid, "name": name, "type": btype, "metric": metric, "description": desc,
        })
        print(f"  benchmark[{name}]: {st} id={bm.get('id') if bm else bm} ({btype}/{metric})")
        if bm:
            bench_ids[name] = bm["id"]

    # 4) 复杂提示词
    prompts = [
        (
            "思维链推理提示",
            "你是一名严谨的推理助手。请对下列问题进行逐步思考（Chain-of-Thought），"
            "在内部完成所有推理步骤后，只在最后一行以「答案：」开头给出最终结论，"
            "不要输出多余解释。\n\n问题：{question}\n\n示例输出格式：\n答案：北京",
            "多跳/事实推理任务的思维链模板，强制模型先推理后给答案，并给出格式示例。",
        ),
        (
            "少样本分类提示",
            "你是一个文本分类器。可选类别仅限：体育、科技、财经、娱乐、政治、健康。"
            "下面是示例：\n"
            "示例1 文本：主队加时逆转取胜。-> 体育\n"
            "示例2 文本：芯片制程迈入 2 纳米。-> 科技\n"
            "示例3 文本：央行下调存款准备金率。-> 财经\n"
            "请只输出一个类别名称，不要解释。\n\n待分类文本：{text}\n\n示例输出格式：\n类别：体育",
            "六类新闻分类的少样本（few-shot）提示，约束输出为单一类别并给出格式示例。",
        ),
        (
            "角色设定+结构化输出提示",
            "你是一位资深软件工程师。请实现用户的需求，并严格按照以下 JSON 结构输出：\n"
            "{{\"thought\": \"简要思路\", \"code\": \"完整可运行代码\", \"tests\": \"关键测试用例\"}}\n"
            "不要输出 JSON 以外的任何内容。\n\n需求：{prompt}",
            "代码生成的角色设定 + 结构化（JSON）输出约束提示。",
        ),
        (
            "摘要生成提示",
            "你是一名新闻编辑。请阅读下列文章，用一句话（不超过 40 字）概括其核心信息，"
            "必须覆盖主体、动作与关键数字。只输出摘要本身。\n\n文章：{article}",
            "摘要/生成的紧凑输出约束提示，强调覆盖关键实体与数字。",
        ),
    ]
    prompt_ids = {}
    for name, template, desc in prompts:
        st, pr = _req("POST", "/prompts/", body={
            "project_id": pid, "name": name, "template": template, "description": desc,
        })
        print(f"  prompt[{name}]: {st} id={pr.get('id') if pr else pr}")
        if pr:
            prompt_ids[name] = pr["id"]

    print("\n完成。项目 ID:", pid)
    print("数据集:", dataset_ids)
    print("基准:", bench_ids)
    print("提示词:", prompt_ids)


if __name__ == "__main__":
    main()
