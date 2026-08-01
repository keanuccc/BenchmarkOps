"""Boundary tests for short-answer extraction and deterministic metrics."""
from __future__ import annotations

from app.evaluation.metrics import exact_match_ci, numeric_match
from app.evaluation.runner import _extract_answer


def test_extract_answer_strips_english_prefix_with_full_width_colon():
    assert _extract_answer("Final Answer： Asia") == "Asia"


def test_exact_match_ci_accepts_aliases_from_expected_raw_dict():
    expected_raw = {"answer": "亚洲", "aliases": ["Asia", "亚细亚洲"]}

    assert exact_match_ci("asia", "亚洲", expected_raw=expected_raw) == 1.0


def test_exact_match_ci_rejects_broader_or_narrower_substrings():
    assert exact_match_ci("热带雨林", "热带") == 0.0
    assert exact_match_ci("20世纪60年代", "20世纪") == 0.0


def test_numeric_match_uses_first_number_when_prediction_has_explanation():
    assert numeric_match("答案：62.5（约 60）", "62.5") == 1.0


def test_extract_answer_preserves_thousands_separator_for_numeric_metric():
    assert _extract_answer("Answer: 1,234") == "1,234"


def test_extract_answer_prefers_explicit_answer_line_over_trailing_explanation():
    text = "答案：北京\n解释：因为题目问的是中国首都。"

    assert _extract_answer(text) == "北京"
