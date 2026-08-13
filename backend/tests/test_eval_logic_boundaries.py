"""评估逻辑边界测试：全角归一化、中文数字单位、多答案分隔等。

这些场景来自真实模型输出的常见形态（全角数字、万/亿单位、顿号多答案），
曾导致本应正确的答案被判错。
"""
from __future__ import annotations

from app.evaluation.metrics import exact_match_ci, numeric_match, f1_token


def test_fullwidth_digits_and_letters_normalized():
    assert exact_match_ci("１２３", "123") == 1.0
    assert exact_match_ci("ＡＢＣ", "ABC") == 1.0
    assert exact_match_ci("答案：１２３", "123") == 0.0  # 前缀不剥（指标层不剥前缀）
    assert exact_match_ci("１２ ３", "123") == 1.0  # 全角空格也归一


def test_fullwidth_punctuation_normalized():
    assert exact_match_ci("北京，上海", "北京, 上海") == 1.0
    assert exact_match_ci("价格：５０元", "价格: 50元") == 1.0


def test_numeric_match_chinese_units():
    assert numeric_match("2.5万", "25000") == 1.0
    assert numeric_match("1亿", "100000000") == 1.0
    assert numeric_match("3000万", "30000000") == 1.0
    assert numeric_match("1千", "1000") == 1.0
    assert numeric_match("25000", "2.5万") == 1.0
    assert numeric_match("1.5亿", "150000000") == 1.0
    assert numeric_match("1.5万亿", "1500000000000") == 1.0
    assert numeric_match("1,234万", "12340000") == 1.0
    # 带单位的数字不应同时保留裸数字候选，避免假阳性
    assert numeric_match("2.5万", "2.5") == 0.0
    assert numeric_match("1亿", "1") == 0.0
    # 单位之外的普通数字仍应正常提取
    assert numeric_match("价格 2.5万，库存 100", "100") == 1.0


def test_numeric_match_still_handles_plain_forms():
    assert numeric_match("1,234", "1234") == 1.0
    assert numeric_match("1e3", "1000") == 1.0
    assert numeric_match("12.5%", "12.5") == 1.0
    assert numeric_match("-3", "3") == 0.0


def test_multi_answer_separators():
    ap = {"multi_answer": "set"}
    expected_raw = {"answer": ["北京", "上海"]}
    assert exact_match_ci("北京、上海", "北京", expected_raw=expected_raw, answer_policy=ap) == 1.0
    assert exact_match_ci("北京, 上海", "北京", expected_raw=expected_raw, answer_policy=ap) == 1.0
    assert exact_match_ci("北京，上海", "北京", expected_raw=expected_raw, answer_policy=ap) == 1.0


def test_f1_token_empty_prediction():
    assert f1_token("", "北京") == 0.0
    assert f1_token("北京", "") == 0.0
