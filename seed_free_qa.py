"""一键灌入 10 行免费模型 QA 测试资产并触发运行。

用法:
    uv run python seed_free_qa.py
依赖: 后端已在 http://localhost:8000 运行。
"""
from __future__ import annotations
import json, time, urllib.request, urllib.error

B = "http://localhost:8000/api/v1"
DATASET_FILE = "sample-data/free-model-qa-10.jsonl"

def _post(url, jsonbody=None, data=None, files=None, method="POST"):
    if jsonbody is not None:
        req = urllib.request.Request(url, data=json.dumps(jsonbody).encode(),
                                     headers={"Content-Type": "application/json"}, method=method)
        return json.loads(urllib.request.urlopen(req).read())
    if files is not None:
        import io, uuid
        boundary = f"----{uuid.uuid4().hex}"
        body = io.BytesIO()
        for k, v in (data or {}).items():
            body.write(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
        fname, content, ctype = files
        body.write(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{fname}"\r\nContent-Type: {ctype}\r\n\r\n'.encode())
        body.write(content)
        body.write(f"\r\n--{boundary}--\r\n".encode())
        req = urllib.request.Request(url, data=body.getvalue(),
                                     headers={"Content-Type": f"multipart/form-data; boundary={boundary}"}, method=method)
        return json.loads(urllib.request.urlopen(req).read())
    return json.loads(urllib.request.urlopen(urllib.request.Request(url, method=method)).read())

def _get(url):
    return json.loads(urllib.request.urlopen(url).read())

def main() -> None:
    # 1. 项目
    pid = _post(f"{B}/projects/", jsonbody={"name": "free-model-qa-10"}).get("id") \
        or _post(f"{B}/projects/", jsonbody={"name": "free-model-qa-10"})["id"]
    print("project   ", pid)

    # 2. 数据集（10 行）
    with open(DATASET_FILE, "rb") as f:
        content = f.read()
    ds = _post(f"{B}/datasets/upload",
              data={"project_id": pid, "name": "QA-10", "format": "jsonl"},
              files=("free-model-qa-10.jsonl", content, "application/x-ndjson"))
    print("dataset   ", ds["id"], "rows=", ds["row_count"])

    # 3. 基准（exact_match_ci：大小写不敏感精确匹配，最适合免费模型稳定输出）
    bm = _post(f"{B}/benchmarks/", jsonbody={
        "project_id": pid, "name": "QA ExactMatchCI", "type": "qa", "metric": "exact_match_ci"})
    print("benchmark ", bm["id"], "metric=", bm["metric"])

    # 4. 提示词（让模型只输出最终数字，便于精确匹配）
    pr = _post(f"{B}/prompts/", jsonbody={
        "project_id": pid, "name": "Answer only the number",
        "template": "Question: {question}\nGive only the final number, no explanation."})
    print("prompt    ", pr["id"], "vars=", pr["variables"])

    # 5. 模型（真实 hy3:free）
    mid = _post(f"{B}/models/", jsonbody={
        "name": "Tencent HY3 (free)", "provider": "tencent", "model_id": "tencent/hy3:free",
        "context_length": 32000, "pricing": {"input_per_1k": 0.0, "output_per_1k": 0.0},
        "capabilities": ["chat"], "is_active": True})["id"]
    print("model     ", mid)

    # 6. 实验 + 运行
    eid = _post(f"{B}/experiments/", jsonbody={
        "project_id": pid, "name": "Run: hy3:free QA-10",
        "dataset_id": ds["id"], "benchmark_id": bm["id"],
        "prompt_id": pr["id"], "model_id": mid})["id"]
    print("experiment", eid)
    _post(f"{B}/experiments/{eid}/run")
    print("\n运行中…（免费模型约每 30s 一行，10 行 ≈ 5 分钟）")

    # 7. 轮询直到完成
    for _ in range(240):
        time.sleep(3)
        j = _get(f"{B}/experiments/{eid}")
        if j["status"] in ("completed", "failed", "partial"):
            m = j.get("metrics", {})
            print(f"\nFINAL status={j['status']} accuracy={j.get('accuracy')} "
                  f"cost={j.get('total_cost')} rows_scored={m.get('rows_scored')} "
                  f"rows_failed={m.get('rows_failed')} provider_errors={m.get('provider_errors')}")
            return
    print("TIMEOUT — 检查后端日志 /tmp/backend8000.log")

if __name__ == "__main__":
    main()
