"""Tests for opt-in partial credit on multi-answer string metrics."""
from app.evaluation.metrics import contains, exact_match_ci, numeric_match


def test_exact_match_ci_all_mode_partial_credit():
    raw = {"answer": ["A", "B"]}
    policy = {"multi_answer": "all", "partial_credit": True}
    assert exact_match_ci("A", "A", expected_raw=raw, answer_policy=policy) == 0.5
    assert exact_match_ci("A, B", "A", expected_raw=raw, answer_policy=policy) == 1.0


def test_exact_match_ci_set_mode_partial_credit():
    raw = {"answer": ["A", "B"]}
    policy = {"multi_answer": "set", "partial_credit": True}
    assert exact_match_ci("B", "A", expected_raw=raw, answer_policy=policy) == 0.5
    assert exact_match_ci("A,B", "A", expected_raw=raw, answer_policy=policy) == 1.0


def test_exact_match_ci_stays_binary_without_partial_credit():
    raw = {"answer": ["A", "B"]}
    policy = {"multi_answer": "all"}
    assert exact_match_ci("A", "A", expected_raw=raw, answer_policy=policy) == 0.0


def test_contains_all_mode_partial_credit():
    raw = {"answer": ["北京", "上海"]}
    policy = {"multi_answer": "all", "partial_credit": True}
    assert contains("北京", "北京", expected_raw=raw, answer_policy=policy) == 0.5
    assert (
        contains("北京、上海", "北京", expected_raw=raw, answer_policy=policy)
        == 1.0
    )


def test_numeric_match_all_mode_partial_credit():
    raw = {"answer": ["1", "2"]}
    policy = {"multi_answer": "all", "partial_credit": True}
    assert numeric_match("1", "1", expected_raw=raw, answer_policy=policy) == 0.5
    assert numeric_match("2, 1", "1", expected_raw=raw, answer_policy=policy) == 1.0
