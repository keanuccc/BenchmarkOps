"""进阶链路 E：CSV/TSV/XLSX 数据格式、answer_policy 别名、模型停用行为。

用法：python scripts/run_advanced_e.py [--base http://localhost:8000/api/v1]
"""
from __future__ import annotations

import argparse
import csv
import io
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


def req(method: str, path: str, *, body=None, files=None, ctype="application/jsonl"):
    url = BASE + path
    headers = {"User-Agent": "run-advanced-e"}
    data = None
    if files is not None:
        boundary = "----adve"
        parts = []
        for field, val in body.items():
            parts.append(
                f'--{boundary}\r\nContent-Disposition: form-data; name="{field}"\r\n\r\n{val}\r\n'.encode()
            )
        for fld, (fname, fbytes) in files.items():
            parts.append(
                f'--{boundary}\r\nContent-Disposition: form-data; name="{fld}"; filename="{fname}"\r\n'
                f"Content-Type: {ctype}\r\n\r\n".encode() + fbytes + b"\r\n"
            )
        parts.append(f"--{boundary}--\r\n".encode())
        data = b"".join(parts)
        headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
    elif body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=300) as resp:
            raw = resp.read()
            return resp.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")[:500]
    except urllib.error.URLError as e:
        raise SystemExit(f"Cannot reach {url}: {e}") from e


def wait_done(experiment_id: str) -> dict:
    for _ in range(300):
        st, exp = req("GET", f"/experiments/{experiment_id}")
        if st == 200 and exp.get("status") in ("completed", "partial", "failed", "cancelled"):
            return exp
        time.sleep(1)
    return {"status": "timeout"}


def upload_bytes(pid, name, fname, fbytes, *, fmt, ctype):
    return req(
        "POST", "/datasets/upload",
        body={"project_id": pid, "name": name, "format": fmt, "task_type": "qa",
              "input_fields": '["question"]', "expected_fields": '["answer"]', "metadata_fields": '["category"]'},
        files={"file": (fname, fbytes)},
        ctype=ctype,
    )


def run_experiment(pid, ds_id, bench_id, prompt_id, model_id, name):
    st, exp = req("POST", "/experiments/", body={
        "project_id": pid, "name": name, "dataset_id": ds_id,
        "benchmark_id": bench_id, "prompt_id": prompt_id, "model_id": model_id,
    })
    if st != 201:
        print(f"    [DBG] 实验创建失败 st={st} body={str(exp)[:200]}")
        return None, st, exp
    req("POST", f"/experiments/{exp['id']}/run", body={})
    done = wait_done(exp["id"])
    st, rows = req("GET", f"/experiments/{exp['id']}/results")
    return exp["id"], done, (rows if isinstance(rows, list) else [])


def main() -> None:
    global BASE
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default=BASE)
    args = parser.parse_args()
    BASE = args.base
    suffix = uuid.uuid4().hex[:6]

    st, project = req("POST", "/projects/", body={"name": f"格式边界 {suffix}"})
    check("创建项目", st == 201)
    pid = project["id"]

    st, bench = req("POST", "/benchmarks/", body={"project_id": pid, "name": "QA", "type": "qa", "metric": "exact_match_ci"})
    bench_id = bench["id"]
    st, prompt = req("POST", "/prompts/", body={"project_id": pid, "name": "P", "template": "问题：{question}\n答案："})
    prompt_id = prompt["id"]
    st, model = req("POST", "/models/", body={
        "name": f"E Mock {suffix}", "provider": "mock", "model_id": f"adve-mock-{suffix}",
        "context_length": 8192, "pricing": {"input_per_1k": 0.0, "output_per_1k": 0.0}, "capabilities": ["qa"],
    })
    model_id = model["id"]

    # 1) CSV（含中文、引号内逗号、BOM）
    csv_buf = io.StringIO()
    writer = csv.writer(csv_buf)
    writer.writerow(["question", "answer", "category"])
    writer.writerow(["计算 2+2", "4", "数学"])
    writer.writerow(["计算 3*4", "12", "数学"])
    writer.writerow(['他说"你好",然后走了', "不相关", "闲聊"])
    csv_bytes = ("\ufeff" + csv_buf.getvalue()).encode("utf-8")
    st, ds_csv = upload_bytes(pid, "CSV数据", "d.csv", csv_bytes, fmt="csv", ctype="text/csv")
    check("上传 CSV（含中文/BOM/引号）", st in (200, 201) and ds_csv.get("row_count") == 3,
          f"st={st} rows={ds_csv.get('row_count') if isinstance(ds_csv, dict) else ds_csv}")
    if st in (200, 201):
        _, done, rows = run_experiment(pid, ds_csv["id"], bench_id, prompt_id, model_id, "CSV实验")
        check("CSV 实验完成", done.get("status") in ("completed", "partial") and len(rows) == 3,
              f"status={done.get('status')} rows={len(rows)}")

    # 2) TSV
    tsv_bytes = "question\tanswer\tcategory\n计算 2+2\t4\t数学\n计算 6/2\t3\t数学\n".encode("utf-8")
    st, ds_tsv = upload_bytes(pid, "TSV数据", "d.tsv", tsv_bytes, fmt="tsv", ctype="text/tab-separated-values")
    check("上传 TSV", st in (200, 201) and ds_tsv.get("row_count") == 2)
    if st in (200, 201):
        _, done, rows = run_experiment(pid, ds_tsv["id"], bench_id, prompt_id, model_id, "TSV实验")
        check("TSV 实验完成", done.get("status") in ("completed", "partial") and len(rows) == 2,
              f"status={done.get('status')} rows={len(rows)}")

    # 3) XLSX（openpyxl 生成）
    try:
        from openpyxl import Workbook

        wb = Workbook()
        ws = wb.active
        ws.append(["question", "answer", "category"])
        ws.append(["计算 2+2", "4", "数学"])
        ws.append(["计算 7+8", "15", "数学"])
        xlsx_bytes = io.BytesIO()
        wb.save(xlsx_bytes)
        st, ds_xlsx = upload_bytes(
            pid, "XLSX数据", "d.xlsx", xlsx_bytes.getvalue(),
            fmt="xlsx", ctype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        check("上传 XLSX", st in (200, 201) and ds_xlsx.get("row_count") == 2,
              f"st={st} rows={ds_xlsx.get('row_count') if isinstance(ds_xlsx, dict) else ds_xlsx}")
        if st in (200, 201):
            _, done, rows = run_experiment(pid, ds_xlsx["id"], bench_id, prompt_id, model_id, "XLSX实验")
            check("XLSX 实验完成", done.get("status") in ("completed", "partial") and len(rows) == 2,
                  f"status={done.get('status')} rows={len(rows)}")
    except ImportError:
        check("XLSX 生成（openpyxl 缺失）", False)

    # 4) answer_policy 别名（aliases）
    alias_rows = [
        {"question": "计算 2+2", "answer": "4", "category": "数学"},
        {"question": "france 的首都？", "answer": "巴黎", "category": "地理"},
        {"question": "一年有几个月？", "answer": "12", "category": "常识"},
    ]
    alias_payload = "\n".join(json.dumps(r, ensure_ascii=False) for r in alias_rows).encode("utf-8")
    st, ds_alias = req(
        "POST", "/datasets/upload",
        body={"project_id": pid, "name": "别名数据", "format": "jsonl", "task_type": "qa",
              "input_fields": '["question"]', "expected_fields": '["answer"]',
              "metadata_fields": '["category"]',
              "answer_policy": json.dumps({
                  "multi_answer": "set",
                  "aliases": {"巴黎": ["Paris", "paris"], "4": ["四"]},
              }, ensure_ascii=False)},
        files={"file": ("alias.jsonl", alias_payload)},
    )
    check("上传别名数据集", st in (200, 201))
    if st in (200, 201):
        _, done, rows = run_experiment(pid, ds_alias["id"], bench_id, prompt_id, model_id, "别名实验")
        scores = sorted(round(r.get("score", 0), 2) for r in rows)
        check("别名实验完成", done.get("status") in ("completed", "partial") and len(rows) == 3,
              f"status={done.get('status')}")
        # 第 2 行主答案是"巴黎"，Mock 输出 "Paris"（france 逻辑），只有别名
        # 匹配才能得 1.0——以此证明 aliases 生效。
        alias_hit = any(
            r.get("score", 0) == 1.0 and "巴黎" in json.dumps(r.get("expected", {}), ensure_ascii=False)
            for r in rows
        )
        check("别名生效（Paris 命中“巴黎”）", alias_hit, f"scores={scores}")

    # 5) 模型停用行为
    st, model_off = req("POST", "/models/", body={
        "name": f"Off {suffix}", "provider": "mock", "model_id": f"adve-off-{suffix}",
        "context_length": 8192, "pricing": {}, "capabilities": ["qa"], "is_active": False,
    })
    check("创建停用模型", st in (200, 201))
    off_id = model_off["id"]
    st, exp_off = req("POST", "/experiments/", body={
        "project_id": pid, "name": "停用模型实验", "dataset_id": ds_csv["id"],
        "benchmark_id": bench_id, "prompt_id": prompt_id, "model_id": off_id,
    })
    check("停用模型可创建实验（快照语义）", st == 201, f"st={st} body={str(exp_off)[:100]}")
    if st == 201:
        req("POST", f"/experiments/{exp_off['id']}/run", body={})
        done_off = wait_done(exp_off["id"])
        check("停用模型运行终态明确", done_off.get("status") in ("completed", "partial", "failed"),
              f"status={done_off.get('status')}")

    req("DELETE", f"/models/{model_id}")
    req("DELETE", f"/models/{off_id}")
    print()
    print(f"PASSED: {len(passed)}  FAILED: {len(failed)}")
    if failed:
        print("Failed:", *failed, sep="\n  - ")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
