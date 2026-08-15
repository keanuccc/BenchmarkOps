"""从公开 CMB 中文医疗基准中采样、清洗并转换为 BenchmarkOps JSONL。

数据来源：
  - 题目：https://raw.githubusercontent.com/FreedomIntelligence/CMB/main/data/CMB.zip
    （解压后：CMB-Exam/CMB-test/CMB-test-choice-question-merge.json）
  - 答案：https://raw.githubusercontent.com/FreedomIntelligence/CMB/main/data/CMB-test-choice-answer.json
  - 许可证：Apache-2.0

这里生成两类数据：
  - 单项选择题/C 型选择题：使用 exact_match_ci 评分
  - 多项选择题：使用 answer_policy.multi_answer=set 评分

采样按 exam_type -> exam_class 分层，避免某一专科在随机抽样中过度集中。
"""
from __future__ import annotations

import json
import random
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
QUESTION_FILE = HERE / "CMB_unzipped" / "CMB" / "CMB-Exam" / "CMB-test" / "CMB-test-choice-question-merge.json"
ANSWER_FILE = HERE / "CMB-test-choice-answer.json"
SINGLE_OUT_FILE = HERE / "cmb-medical-qa.jsonl"
MULTI_OUT_FILE = HERE / "cmb-medical-multi-qa.jsonl"

# 每个 exam_class 采样条数；28 个 exam_class，默认 10 条/类。
PER_EXAM_CLASS = 10
SEED = 42


def _load_json(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))


def build_question_text(item: dict) -> str:
    question = str(item.get("question") or "").strip()
    options = item.get("option") or {}
    lines = [question]
    for key in sorted(options.keys()):
        lines.append(f"{key}. {str(options[key]).strip()}")
    return "\n".join(lines)


def _write_rows(rows: list[dict], path: Path, *, multi_answer: bool) -> None:
    out = []
    for item in rows:
        if multi_answer:
            answer = [ch for ch in str(item["answer"]).upper() if ch in "ABCDE"]
        else:
            answer = item["answer"]
        out.append(
            {
                "question": item["question"],
                "answer": answer,
                "subject": f"{item['exam_type']}/{item['exam_class']}/{item['exam_subject']}",
                "source_id": item["id"],
                "exam_type": item["exam_type"],
                "exam_class": item["exam_class"],
            }
        )
    with path.open("w", encoding="utf-8") as f:
        for row in out:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def main() -> None:
    questions = _load_json(QUESTION_FILE)
    answers = {item["id"]: str(item.get("answer") or "").strip().upper() for item in _load_json(ANSWER_FILE)}

    single_choice: list[dict] = []
    multi_choice: list[dict] = []
    for item in questions:
        qid = item.get("id")
        if qid not in answers:
            continue
        record = {
            "id": qid,
            "exam_type": item.get("exam_type"),
            "exam_class": item.get("exam_class"),
            "exam_subject": item.get("exam_subject"),
            "question": build_question_text(item),
            "answer": answers[qid],
        }
        if item.get("question_type") == "多项选择题":
            multi_choice.append(record)
        else:
            single_choice.append(record)

    rng = random.Random(SEED)

    single_buckets: dict[str, list[dict]] = defaultdict(list)
    for item in single_choice:
        single_buckets[item["exam_class"]].append(item)

    multi_buckets: dict[str, list[dict]] = defaultdict(list)
    for item in multi_choice:
        multi_buckets[item["exam_class"]].append(item)

    sampled_single: list[dict] = []
    for exam_class in sorted(single_buckets):
        pool = single_buckets[exam_class]
        sampled_single.extend(rng.sample(pool, min(PER_EXAM_CLASS, len(pool))))
    sampled_single.sort(key=lambda x: x["id"])

    sampled_multi: list[dict] = []
    for exam_class in sorted(multi_buckets):
        pool = multi_buckets[exam_class]
        sampled_multi.extend(rng.sample(pool, min(PER_EXAM_CLASS, len(pool))))
    sampled_multi.sort(key=lambda x: x["id"])

    _write_rows(sampled_single, SINGLE_OUT_FILE, multi_answer=False)
    _write_rows(sampled_multi, MULTI_OUT_FILE, multi_answer=True)

    print(f"single-choice rows: {len(single_choice)}")
    print(f"multi-choice rows: {len(multi_choice)}")
    print(f"sampled single rows: {len(sampled_single)}")
    print(f"sampled multi rows: {len(sampled_multi)}")
    print(f"wrote -> {SINGLE_OUT_FILE}")
    print(f"wrote -> {MULTI_OUT_FILE}")


if __name__ == "__main__":
    main()
