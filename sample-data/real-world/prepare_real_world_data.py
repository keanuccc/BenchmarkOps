"""Download real-world benchmark data and convert it to BenchmarkOps JSONL.

Sources:
  1. C-Eval (Chinese exam QA)   - https://huggingface.co/datasets/ceval/ceval-exam
  2. THUCNews (Chinese news classification) - https://huggingface.co/datasets/spiritx2023/ThuCnews
  3. HumanEval (Python coding)  - https://github.com/openai/human-eval

Downloads go through hf-mirror.com / cdn.jsdelivr.net so they work on a
China-network machine. Output files land next to this script:
  - ceval-qa.jsonl
  - thucnews-classification.jsonl
  - humaneval-coding.jsonl
"""
from __future__ import annotations

import gzip
import json
import os
import random
import urllib.request

try:
    import pandas as pd
except ImportError:
    pd = None


HERE = os.path.dirname(os.path.abspath(__file__))
DOWNLOADS = os.path.join(HERE, "_downloads")

CEVAL_SUBJECTS = [
    "computer_network",
    "chinese_language_and_literature",
    "advanced_mathematics",
]
CEVAL_VAL_SIZE = 40  # rows per subject
THUC_SIZE_PER_CLASS = 12  # 10 classes => 120 rows
HUMANEVAL_SIZE = 60

CEVAL_BASE = "https://hf-mirror.com/datasets/ceval/ceval-exam/resolve/main"
THUC_URL = (
    "https://hf-mirror.com/datasets/spiritx2023/ThuCnews/resolve/main/cnews.test.txt"
)
HUMANEVAL_URL = (
    "https://cdn.jsdelivr.net/gh/openai/human-eval@master/data/HumanEval.jsonl.gz"
)


def _download(url: str, dest: str) -> str:
    if os.path.exists(dest) and os.path.getsize(dest) > 0:
        print(f"  [skip] {os.path.basename(dest)} already exists")
        return dest
    print(f"  [get ] {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "BenchmarkOps-data-prep/1.0"})
    with urllib.request.urlopen(req, timeout=120) as resp, open(dest, "wb") as f:
        while True:
            chunk = resp.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
    print(f"  [done] {os.path.getsize(dest):,} bytes")
    return dest


def _read_parquet(path: str):
    if pd is None:
        raise RuntimeError("pandas/pyarrow is required to read C-Eval parquet files")
    return pd.read_parquet(path)


def prepare_ceval() -> list[dict]:
    print("C-Eval (中文考试真题 QA)")
    rng = random.Random(42)
    rows: list[dict] = []
    for subject in CEVAL_SUBJECTS:
        url = f"{CEVAL_BASE}/{subject}/val-00000-of-00001.parquet"
        path = _download(url, os.path.join(DOWNLOADS, f"ceval-{subject}.parquet"))
        df = _read_parquet(path)
        sample = df.sample(n=min(CEVAL_VAL_SIZE, len(df)), random_state=42)
        for _, item in sample.iterrows():
            q = str(item.get("question") or "").strip()
            answer = str(item.get("answer") or "").strip().upper()
            # Some mirrors already inline the options; if not, append A-D.
            if "A." not in q and any(pd.notna(item.get(k)) for k in ("A", "B", "C", "D")):
                options = []
                for k in ("A", "B", "C", "D"):
                    val = item.get(k)
                    if pd.notna(val):
                        options.append(f"{k}. {str(val).strip()}")
                if options:
                    q = q + "\n" + "\n".join(options)
            rows.append({"question": q, "answer": answer, "subject": subject})
    return rows


def prepare_thucnews() -> list[dict]:
    print("THUCNews (中文新闻分类)")
    path = _download(THUC_URL, os.path.join(DOWNLOADS, "cnews.test.txt"))
    buckets: dict[str, list[dict]] = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if "\t" not in line:
                continue
            label, text = line.split("\t", 1)
            label, text = label.strip(), text.strip()
            if not label or not text:
                continue
            buckets.setdefault(label, []).append({"text": text, "answer": label})
    rng = random.Random(42)
    rows: list[dict] = []
    for label in sorted(buckets):
        pool = buckets[label]
        rows.extend(rng.sample(pool, min(THUC_SIZE_PER_CLASS, len(pool))))
    rng.shuffle(rows)
    return rows


def prepare_humaneval() -> list[dict]:
    print("HumanEval (Python 代码生成)")
    gz_path = _download(HUMANEVAL_URL, os.path.join(DOWNLOADS, "HumanEval.jsonl.gz"))
    rows: list[dict] = []
    with gzip.open(gz_path, "rt", encoding="utf-8") as f:
        for line in f:
            item = json.loads(line)
            rows.append(
                {
                    "prompt": item["prompt"],
                    "answer": item["canonical_solution"],
                    # 官方测试代码（def check(candidate) + check(entry_point)），
                    # 供 code_pass 指标真实执行验证。
                    "tests": [item["test"]],
                    "entry_point": item["entry_point"],
                    "task_id": item["task_id"],
                }
            )
    return rows[:HUMANEVAL_SIZE]


def _write_jsonl(rows: list[dict], name: str) -> None:
    path = os.path.join(HERE, name)
    with open(path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"wrote {len(rows)} rows -> {path}")


def main() -> None:
    os.makedirs(DOWNLOADS, exist_ok=True)
    _write_jsonl(prepare_ceval(), "ceval-qa.jsonl")
    _write_jsonl(prepare_thucnews(), "thucnews-classification.jsonl")
    _write_jsonl(prepare_humaneval(), "humaneval-coding.jsonl")
    print("all done.")


if __name__ == "__main__":
    main()
