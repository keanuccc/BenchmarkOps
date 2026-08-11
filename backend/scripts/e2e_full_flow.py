"""端到端全流程测试：Project -> Dataset -> Benchmark -> Prompt -> Model -> Experiment -> Run -> Compare -> Report -> Export。

在当前运行中的服务上执行（默认 http://localhost:8000/api/v1）。实验使用
provider=mock 的模型，避免真实网关费用与密钥依赖。

用法：python scripts/e2e_full_flow.py [--base http://localhost:8000/api/v1]
"""
from __future__ import annotations

import argparse
import io
import json
import time
import uuid
import urllib.error
import urllib.request

BASE = "http://localhost:8000/api/v1"
passed: list[str] = []
failed: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    tag = "PASS" if ok else "FAIL"
    print(f"[{tag}] {name}" + (f" — {detail}" if detail else ""))
    (passed if ok else failed).append(name)


def req(method: str, path: str, *, body=None, files=None):
    url = BASE + path
    headers = {"User-Agent": "e2e-full-flow"}
    data = None
    if files is not None:
        boundary = "----e2e"
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
        return e.code, e.read().decode("utf-8", "replace")[:400]
    except urllib.error.URLError as e:
        raise SystemExit(f"Cannot reach {url}: {e}") from e


def req_raw(path: str) -> tuple[int, bytes]:
    request = urllib.request.Request(BASE + path, headers={"User-Agent": "e2e"})
    try:
        with urllib.request.urlopen(request, timeout=120) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def wait_done(experiment_id: str) -> dict:
    for _ in range(120):
        st, exp = req("GET", f"/experiments/{experiment_id}")
        if st == 200 and exp.get("status") in (
            "completed", "partial", "failed", "cancelled",
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

    # 1) Project
    st, project = req(
        "POST", "/projects/",
        body={"name": "E2E-全流程测试", "description": "端到端完整业务流验证"},
    )
    check("创建项目", st == 201, f"id={project.get('id') if isinstance(project, dict) else project}")
    pid = project["id"]

    # 2) Dataset (10 rows, QA with category metadata)
    rows = []
    qa = [
        ("退款要多久到账？", "1-3个工作日", "退款"),
        ("运费谁承担？", "质量问题由商家承担", "物流"),
        ("会员积分多久到账？", "确认收货后24小时内", "会员"),
        ("发票怎么开？", "订单完成后在线申请电子发票", "发票"),
        ("支持货到付款吗？", "目前暂不支持", "支付"),
        ("七天无理由退货有时间限制吗？", "签收之日起7天内", "退款"),
        ("赠品需要一起退回吗？", "未拆封使用建议一并退回", "退款"),
        ("怎么联系人工客服？", "页面右下角客服入口", "客服"),
        ("优惠券过期了还能用吗？", "过期后无法使用", "营销"),
        ("商品破损怎么办？", "签收后48小时内拍照联系客服", "售后"),
    ]
    for q, a, c in qa:
        rows.append(json.dumps(
            {"question": q, "answer": a, "category": c}, ensure_ascii=False
        ))
    st, ds = req(
        "POST", "/datasets/upload",
        body={
            "project_id": pid,
            "name": "E2E-客服QA-10条",
            "format": "jsonl",
            "task_type": "qa",
            "input_fields": '["question"]',
            "expected_fields": '["answer"]',
            "metadata_fields": '["category"]',
        },
        files={"file": ("e2e_qa.jsonl", ("\n".join(rows) + "\n").encode("utf-8"))},
    )
    check("上传数据集", st in (200, 201) and ds.get("row_count") == 10, f"rows={ds.get('row_count')}")
    ds_id = ds["id"]

    st, preview = req("GET", f"/datasets/{ds_id}/preview")
    check("数据集预览", st == 200)
    st, stats = req("GET", f"/datasets/{ds_id}/stats")
    check("数据集统计", st == 200 and stats.get("row_count") == 10)

    # 3) Benchmark
    st, bench = req(
        "POST", "/benchmarks/",
        body={
            "project_id": pid,
            "name": "E2E-客服QA精确匹配",
            "type": "qa",
            "metric": "exact_match_ci",
            "description": "端到端测试基准",
        },
    )
    check("创建基准", st == 201)
    bench_id = bench["id"]
    st, available = req("GET", "/benchmarks/metrics/available")
    check("可用指标列表", st == 200 and "exact_match_ci" in available.get("metrics", []))

    # 4) Prompt
    st, prompt = req(
        "POST", "/prompts/",
        body={
            "project_id": pid,
            "name": "E2E-简洁回答",
            "template": "你是电商客服。请简洁回答用户问题，只输出答案本身。\n问题：{question}",
            "description": "端到端测试提示词",
        },
    )
    check("创建提示词", st in (200, 201))
    prompt_id = prompt["id"]
    st, rendered = req(
        "POST", f"/prompts/{prompt_id}/render",
        body={"variables": {"question": "退款要多久到账？"}},
    )
    rendered_text = rendered.get("rendered", "") if isinstance(rendered, dict) else str(rendered)
    check("提示词渲染", st == 200 and "退款要多久到账" in rendered_text)

    # 5) Mock model (does not touch real gateways)
    run_suffix = uuid.uuid4().hex[:8]
    st, model = req(
        "POST", "/models/",
        body={
            "name": f"E2E Mock 模型 {run_suffix}",
            "provider": "mock",
            "model_id": f"e2e-mock-v1-{run_suffix}",
            "context_length": 8192,
            "pricing": {"input_per_1k": 0.0, "output_per_1k": 0.0},
            "capabilities": ["qa"],
        },
    )
    check("注册 Mock 模型", st in (200, 201))
    model_id = model["id"]

    # 6) Experiment 1 + run
    st, exp1 = req(
        "POST", "/experiments/",
        body={
            "project_id": pid,
            "name": "E2E-实验1-Mock",
            "dataset_id": ds_id,
            "benchmark_id": bench_id,
            "prompt_id": prompt_id,
            "model_id": model_id,
        },
    )
    check("创建实验1", st == 201)
    exp1_id = exp1["id"]
    st, _ = req("POST", f"/experiments/{exp1_id}/run", body={})
    check("触发运行1", st == 200)
    done1 = wait_done(exp1_id)
    check("实验1完成", done1.get("status") in ("completed", "partial"), f"status={done1.get('status')}")
    check("实验1有逐行结果", done1.get("cells_done", 0) >= 1, f"cells={done1.get('cells_done')}")

    # 7) Experiment 2 (another mock model id) + run, for compare
    st, model2 = req(
        "POST", "/models/",
        body={
            "name": f"E2E Mock 模型B {run_suffix}",
            "provider": "mock",
            "model_id": f"e2e-mock-v2-{run_suffix}",
            "context_length": 8192,
            "pricing": {"input_per_1k": 0.0, "output_per_1k": 0.0},
            "capabilities": ["qa"],
        },
    )
    st, exp2 = req(
        "POST", "/experiments/",
        body={
            "project_id": pid,
            "name": "E2E-实验2-MockB",
            "dataset_id": ds_id,
            "benchmark_id": bench_id,
            "prompt_id": prompt_id,
            "model_id": model2["id"],
        },
    )
    exp2_id = exp2["id"]
    req("POST", f"/experiments/{exp2_id}/run", body={})
    done2 = wait_done(exp2_id)
    check("实验2完成", done2.get("status") in ("completed", "partial"), f"status={done2.get('status')}")

    # 8) Results detail
    st, results = req("GET", f"/experiments/{exp1_id}/results")
    check("实验结果明细", st == 200 and isinstance(results, list) and len(results) == 10,
          f"rows={len(results) if isinstance(results, list) else '?'}")

    # 9) Compare
    st, comparison = req(
        "POST", "/analytics/compare",
        body={"experiment_ids": [exp1_id, exp2_id]},
    )
    check("实验对比", st == 200 and len(comparison.get("experiments", [])) == 2)

    # 10) Subgroups
    st, subgroups = req(
        "GET", f"/analytics/experiments/{exp1_id}/subgroups?group_field=category"
    )
    check("分组分析", st == 200 and subgroups.get("total_rows") == 10,
          f"groups={len(subgroups.get('groups', []))}")

    # 11) Leaderboard / trend
    st, leaderboard = req("GET", f"/analytics/leaderboard?project_id={pid}")
    check("排行榜", st == 200 and len(leaderboard) >= 2)
    st, trend = req("GET", f"/analytics/trend?project_id={pid}")
    check("趋势", st == 200)

    # 12) Report + exports
    st, report = req(
        "POST", "/reports/generate",
        body={"project_id": pid, "experiment_ids": [exp1_id, exp2_id], "title": "E2E 全流程报告"},
    )
    check("生成报告", st == 201 and bool(report.get("content_markdown")))
    report_id = report["id"]
    st_md, md_bytes = req_raw(f"/reports/{report_id}/export")
    check("导出 Markdown", st_md == 200 and len(md_bytes) > 100)
    st_html, html_bytes = req_raw(f"/reports/{report_id}/export?format=html")
    check("导出 HTML", st_html == 200 and b"<!DOCTYPE html>" in html_bytes)
    st_pdf, pdf_bytes = req_raw(f"/reports/{report_id}/export/pdf")
    check("导出 PDF", st_pdf == 200 and pdf_bytes.startswith(b"%PDF"))

    # 13) Cleanup: delete the E2E project (cascades datasets/experiments/reports)
    st, _ = req("DELETE", f"/projects/{pid}")
    check("清理测试项目", st in (200, 204))
    for mid in (model_id, model2["id"]):
        req("DELETE", f"/models/{mid}")
    check("清理测试模型", True)

    print()
    print(f"PASSED: {len(passed)}  FAILED: {len(failed)}")
    if failed:
        print("Failed:", *failed, sep="\n  - ")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
