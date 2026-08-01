from __future__ import annotations
import json, time, urllib.request, urllib.error
B = "http://localhost:8000/api/v1"
DATASET_FILE = "sample-data/free-model-qa-10.jsonl"
def _post(url, jsonbody=None, data=None, files=None):
    if jsonbody is not None:
        req = urllib.request.Request(url, data=json.dumps(jsonbody).encode(), headers={"Content-Type":"application/json"})
        return json.loads(urllib.request.urlopen(req).read())
    if files is not None:
        import io, uuid
        boundary=f"----{uuid.uuid4().hex}"; body=io.BytesIO()
        for k,v in (data or {}).items():
            body.write(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
        fn,content,ct=files
        body.write(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{fn}"\r\nContent-Type: {ct}\r\n\r\n'.encode())
        body.write(content); body.write(f"\r\n--{boundary}--\r\n".encode())
        req=urllib.request.Request(url, data=body.getvalue(), headers={"Content-Type":f"multipart/form-data; boundary={boundary}"})
        return json.loads(urllib.request.urlopen(req).read())
def _get(url):
    return json.loads(urllib.request.urlopen(url).read())
def main():
    pid=_post(f"{B}/projects/", jsonbody={"name":"free-model-qa-10-v2"}).get("id") or _post(f"{B}/projects/", jsonbody={"name":"free-model-qa-10-v2"})["id"]
    print("project  ", pid)
    with open(DATASET_FILE,"rb") as f: content=f.read()
    ds=_post(f"{B}/datasets/upload", data={"project_id":pid,"name":"QA-10","format":"jsonl"}, files=("free-model-qa-10.jsonl",content,"application/x-ndjson"))
    print("dataset  ", ds["id"], "rows=", ds["row_count"])
    bm=_post(f"{B}/benchmarks/", jsonbody={"project_id":pid,"name":"QA ExactMatchCI","type":"qa","metric":"exact_match_ci"})
    print("benchmark", bm["id"])
    pr=_post(f"{B}/prompts/", jsonbody={"project_id":pid,"name":"Answer only the number","template":"Question: {question}\nGive only the final number, no explanation."})
    print("prompt   ", pr["id"])
    mid=_post(f"{B}/models/", jsonbody={"name":"Tencent HY3 (free)","provider":"tencent","model_id":"tencent/hy3:free","context_length":32000,"pricing":{"input_per_1k":0.0,"output_per_1k":0.0},"capabilities":["chat"],"is_active":True})["id"]
    print("model    ", mid)
    eid=_post(f"{B}/experiments/", jsonbody={"project_id":pid,"name":"Run: hy3:free QA-10 (parallel)","dataset_id":ds["id"],"benchmark_id":bm["id"],"prompt_id":pr["id"],"model_id":mid})["id"]
    print("experiment", eid)
    _post(f"{B}/experiments/{eid}/run")
    for _ in range(120):
        time.sleep(2)
        j=_get(f"{B}/experiments/{eid}")
        if j["status"] in ("completed","failed","partial"):
            m=j.get("metrics",{})
            print(f"FINAL status={j['status']} accuracy={j.get('accuracy')} cost={j.get('total_cost')} rows_scored={m.get('rows_scored')} rows_failed={m.get('rows_failed')} provider_errors={m.get('provider_errors')}")
            return
    print("TIMEOUT")
main()
