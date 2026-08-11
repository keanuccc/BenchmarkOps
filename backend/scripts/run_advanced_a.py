"""进阶链路 A：多轮对话/few-shot、敏感字段脱敏、数据集版本化、异步导入、多答案评分。

用法：python scripts/run_advanced_a.py [--base http://localhost:8000/api/v1]
"""
from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
import uuid

BASE = "http://localhost:8000/api/v1"
passed: list[str] = []
failed: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    tag = "PASS" if ok else "FAIL"
    print(f"[{tag}] {name}" + (f" — {detail}" if detail else ""))
    (passed if ok else failed).append(name)


def req(method: str, path: str, *, body=None, files=None):
    url = BASE + path
    headers = {"User-Agent": "run-advanced-a"}
    data = None
    if files is not None:
        boundary = "----adv"
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


def wait_done(experiment_id: str) -> dict:
    for _ in range(180):
        st, exp = req("GET", f"/experiments/{experiment_id}")
        if st == 200 and exp.get("status") in (
            "completed", "partial", "failed", "cancelled",
        ):
            return exp
        time.sleep(1)
    return {"status": "timeout"}


def wait_import(job_id: str) -> dict:
    for _ in range(120):
        st, job = req("GET", f"/datasets/imports/{job_id}")
        if st == 200 and job.get("status") in ("completed", "succeeded", "failed"):
            return job
        time.sleep(1)
    return {"status": "timeout"}


def upload(pid: str, name: str, rows: list[dict], *, task="qa", structured=False, sensitive=None, answer_policy=None):
    payload = "\n".join(json.dumps(r, ensure_ascii=False) for r in rows).encode("utf-8")
    body = {
        "project_id": pid,
        "name": name,
        "format": "jsonl",
        "task_type": task,
        "input_fields": '["question"]',
        "expected_fields": '["answer"]',
        "metadata_fields": '["category"]',
    }
    if structured:
        body["structured_chat"] = "true"
        body["input_fields"] = '["question","messages","examples"]'
    if sensitive:
        body["sensitive_fields"] = json.dumps(sensitive)
        body["metadata_fields"] = '["category","phone"]'
    if answer_policy:
        body["answer_policy"] = json.dumps(answer_policy)
    st, ds = req("POST", "/datasets/upload", body=body, files={"file": (name + ".jsonl", payload)})
    return st, ds


def main() -> None:
    global BASE
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default=BASE)
    args = parser.parse_args()
    BASE = args.base
    suffix = uuid.uuid4().hex[:6]

    st, project = req("POST", "/projects/", body={"name": f"进阶链路A {suffix}", "description": "structured_chat/脱敏/版本化/异步导入/多答案"})
    check("创建项目", st == 201)
    pid = project["id"]

    st, bench = req("POST", "/benchmarks/", body={"project_id": pid, "name": "QA精确", "type": "qa", "metric": "exact_match_ci"})
    bench_id = bench["id"]
    st, prompt = req("POST", "/prompts/", body={"project_id": pid, "name": "对话模板", "template": "问题：{question}\n答案："})
    prompt_id = prompt["id"]
    st, model = req("POST", "/models/", body={
        "name": f"Adv Mock {suffix}", "provider": "mock", "model_id": f"adv-mock-{suffix}",
        "context_length": 8192, "pricing": {"input_per_1k": 0.0, "output_per_1k": 0.0}, "capabilities": ["qa"],
    })
    model_id = model["id"]

    # 1) 多轮对话 + few-shot（structured_chat）
    chat_rows = [
        {
            "messages": [
                {"role": "system", "content": "你是电商客服助手"},
                {"role": "user", "content": "我要申请退货"},
                {"role": "assistant", "content": "好的，请提供订单号"},
            ],
            "examples": [
                {"question": "怎么退货？", "answer": "在订单详情页申请售后"},
                {"question": "运费谁出？", "answer": "质量问题商家承担"},
            ],
            "question": "计算 2+2",
            "answer": "4",
            "category": "数学",
        },
        {
            "messages": [{"role": "user", "content": "我的包裹到哪了？"}],
            "examples": [],
            "question": "计算 3*4",
            "answer": "12",
            "category": "数学",
        },
        {
            "messages": [],
            "examples": [],
            "question": "发票怎么开？",
            "answer": "订单完成后在线申请",
            "category": "发票",
        },
    ]
    st, ds_chat = upload(pid, "结构化对话", chat_rows, structured=True)
    check("上传结构化对话数据集", st in (200, 201) and ds_chat.get("row_count") == 3)
    check("结构化标记生效", (ds_chat.get("contract") or {}).get("structured_chat") is True)
    chat_ds_id = ds_chat["id"]

    st, exp = req("POST", "/experiments/", body={
        "project_id": pid, "name": "结构化对话实验", "dataset_id": chat_ds_id,
        "benchmark_id": bench_id, "prompt_id": prompt_id, "model_id": model_id,
    })
    exp_id = exp["id"]
    req("POST", f"/experiments/{exp_id}/run", body={})
    done = wait_done(exp_id)
    st, rows = req("GET", f"/experiments/{exp_id}/results")
    row_list = rows if isinstance(rows, list) else []
    chat_ok = all(r.get("error") is None for r in row_list)
    first_input = row_list[0].get("input", {}) if row_list else {}
    check("结构化对话实验完成", done.get("status") in ("completed", "partial") and chat_ok, f"acc={done.get('accuracy')}")
    check("messages/examples 随行保存", "messages" in first_input and "examples" in first_input)
    check("结构化样本命中算术", any(r.get("score", 0) == 1.0 for r in row_list), f"rows={len(row_list)}")

    # 2) 敏感字段脱敏
    secret_rows = [
        {"question": "查一下我的手机号 13800138000 绑定几个订单", "answer": "2个", "category": "账户", "phone": "13800138000"},
        {"question": "邮箱 a@b.com 能改吗", "answer": "可以", "category": "账户", "phone": "13900139000"},
    ]
    st, ds_secret = upload(pid, "含敏感字段", secret_rows, sensitive=["phone"])
    check("上传含敏感字段数据集", st in (200, 201))
    secret_ds_id = ds_secret["id"]
    st, preview = req("GET", f"/datasets/{secret_ds_id}/preview")
    preview_text = json.dumps(preview, ensure_ascii=False)
    check(
        "预览中手机号已脱敏（字段级+文本级）",
        "13800138000" not in preview_text and "[REDACTED]" in preview_text,
    )

    st, exp_secret = req("POST", "/experiments/", body={
        "project_id": pid, "name": "脱敏实验", "dataset_id": secret_ds_id,
        "benchmark_id": bench_id, "prompt_id": prompt_id, "model_id": model_id,
    })
    req("POST", f"/experiments/{exp_secret['id']}/run", body={})
    done_s = wait_done(exp_secret["id"])
    st, secret_rows_out = req("GET", f"/experiments/{exp_secret['id']}/results?mask_sensitive=true")
    secret_text = json.dumps(secret_rows_out, ensure_ascii=False)
    check("脱敏实验完成", done_s.get("status") in ("completed", "partial"))
    check("实验输出中手机号已脱敏", "13800138000" not in secret_text and "[REDACTED]" in secret_text)

    # 3) 数据集版本化
    v1_rows = [{"question": f"问题{i}", "answer": "A", "category": "c"} for i in range(1, 6)]
    st, ds_v = upload(pid, "版本化数据集", v1_rows)
    check("上传 v1", st in (200, 201) and ds_v.get("row_count") == 5)
    v_ds_id = ds_v["id"]
    v2_rows = [{"question": f"问题{i}", "answer": "B", "category": "c"} for i in range(1, 9)]
    payload2 = "\n".join(json.dumps(r, ensure_ascii=False) for r in v2_rows).encode("utf-8")
    st, version = req(
        "POST", f"/datasets/{v_ds_id}/versions",
        body={"project_id": pid, "name": "版本化数据集-v2", "format": "jsonl"},
        files={"file": ("v2.jsonl", payload2)},
    )
    check("创建 v2 版本", st in (200, 201) and version.get("version") == 2)
    st, versions = req("GET", f"/datasets/{v_ds_id}/versions")
    check("版本列表 = 2", st == 200 and len(versions) == 2)
    st, ds_after_v2 = req("GET", f"/datasets/{v_ds_id}")
    check("激活版本为 v2", ds_after_v2.get("version") == 2 and ds_after_v2.get("row_count") == 8)
    st, activated = req("POST", f"/datasets/{v_ds_id}/versions/1/activate", body={})
    check("回滚激活 v1", st == 200 and activated.get("version") == 1 and activated.get("row_count") == 5)

    # 4) 异步导入
    import_rows = [{"question": f"导入问题{i}", "answer": "ok", "category": "c"} for i in range(1, 6)]
    payload_imp = "\n".join(json.dumps(r, ensure_ascii=False) for r in import_rows).encode("utf-8")
    st, job = req(
        "POST", "/datasets/import",
        body={"project_id": pid, "name": "异步导入数据集", "format": "jsonl"},
        files={"file": ("import.jsonl", payload_imp)},
    )
    check("提交异步导入任务", st == 202 and job.get("id"))
    job_done = wait_import(job["id"])
    check("异步导入完成", job_done.get("status") in ("completed", "succeeded"), f"status={job_done.get('status')}")
    st, ds_list = req("GET", f"/datasets?project_id={pid}")
    check("导入的数据集可见", any(d["name"] == "异步导入数据集" for d in ds_list["items"]))

    # 5) 多答案 / 部分得分
    multi_rows = [
        {"question": "计算 2+2", "answer": ["4", "四"], "category": "数学"},
        {"question": "计算 3*4", "answer": ["12", "十二"], "category": "数学"},
        {"question": "france 的首都？", "answer": ["Paris", "巴黎"], "category": "地理"},
        {"question": "发票怎么开？", "answer": ["在线申请", "订单完成后申请"], "category": "发票"},
    ]
    st, ds_multi = upload(pid, "多答案数据集", multi_rows, answer_policy={"multi_answer": "set", "partial_credit": True})
    check("上传多答案数据集", st in (200, 201))
    multi_ds_id = ds_multi["id"]
    st, exp_multi = req("POST", "/experiments/", body={
        "project_id": pid, "name": "多答案实验", "dataset_id": multi_ds_id,
        "benchmark_id": bench_id, "prompt_id": prompt_id, "model_id": model_id,
    })
    req("POST", f"/experiments/{exp_multi['id']}/run", body={})
    done_m = wait_done(exp_multi["id"])
    st, multi_out = req("GET", f"/experiments/{exp_multi['id']}/results")
    multi_list = multi_out if isinstance(multi_out, list) else []
    scores = sorted(round(r.get("score", 0), 2) for r in multi_list)
    check("多答案实验完成", done_m.get("status") in ("completed", "partial"))
    check("多答案评分有区分度", len(set(scores)) >= 2, f"scores={scores}")

    # 6) 清理临时模型
    req("DELETE", f"/models/{model_id}")

    print()
    print(f"PASSED: {len(passed)}  FAILED: {len(failed)}")
    if failed:
        print("Failed:", *failed, sep="\n  - ")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
