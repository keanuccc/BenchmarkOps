"""单项选择字母提取与多选紧凑字母串评分测试。"""
from __future__ import annotations

from app.evaluation.metrics import exact_match_ci


def test_single_choice_letter_prefixes_are_extracted() -> None:
    assert exact_match_ci("选项 B", "B") == 1.0
    assert exact_match_ci("选B", "B") == 1.0
    assert exact_match_ci("B选项", "B") == 1.0
    assert exact_match_ci("正确答案是 B", "B") == 1.0
    assert exact_match_ci("B", "B") == 1.0


def test_single_choice_does_not_confuse_medical_term_with_letter() -> None:
    assert exact_match_ci("B超", "B") == 0.0
    assert exact_match_ci("维生素A", "A") == 0.0


def test_multi_answer_set_accepts_comma_or_compact_letters() -> None:
    expected_raw = {"answer": ["A", "B", "C"]}
    policy = {"multi_answer": "set"}
    assert exact_match_ci("A,B,C", "A", expected_raw=expected_raw, answer_policy=policy) == 1.0
    assert exact_match_ci("ABC", "A", expected_raw=expected_raw, answer_policy=policy) == 1.0


def test_multi_answer_set_rejects_missing_answer() -> None:
    expected_raw = {"answer": ["A", "B", "C"]}
    policy = {"multi_answer": "set"}
    assert exact_match_ci("A,B", "A", expected_raw=expected_raw, answer_policy=policy) == 0.0
    assert exact_match_ci("ABD", "A", expected_raw=expected_raw, answer_policy=policy) == 0.0


def test_multi_answer_reject_extra_penalizes_over_selection() -> None:
    expected_raw = {"answer": ["A", "B", "C"]}
    policy = {"multi_answer": "set", "reject_extra": True}
    assert exact_match_ci("A,B,C", "A", expected_raw=expected_raw, answer_policy=policy) == 1.0
    assert exact_match_ci("A,B,C,E", "A", expected_raw=expected_raw, answer_policy=policy) == 0.0
