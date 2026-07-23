"""Tests for the answer extraction pipeline in runner.py.

Covers 30+ edge cases: Chinese punctuation, nested parentheses, multi-line CoT,
trailing units, comma-separated values, whitespace normalization, etc.
"""
from app.evaluation.runner import _extract_answer


def test_strip_answer_prefix_chinese():
    """Strip Chinese answer prefixes like '答案：'."""
    assert _extract_answer("答案：北京") == "北京"
    assert _extract_answer("答案：亚洲") == "亚洲"
    assert _extract_answer("结论：正确") == "正确"
    assert _extract_answer("最终答案：42") == "42"


def test_strip_answer_prefix_english():
    """Strip English answer prefixes like 'Answer:'."""
    assert _extract_answer("Answer: Paris") == "Paris"
    assert _extract_answer("Final Answer: London") == "London"


def test_multiline_cot_takes_last_line():
    """For multi-line CoT output, take the last non-empty line."""
    text = """Let me think step by step.
First, we need to find the capital of China.
Then we can answer.

答案：北京"""
    assert _extract_answer(text) == "北京"


def test_strip_units_and_punctuation():
    """Strip trailing units and punctuation."""
    assert _extract_answer("答案：40平方厘米") == "40"
    assert _extract_answer("答案：碳（C）") == "碳"
    assert _extract_answer("答案：100元") == "100"


def test_strip_comma_separated_multi_answer():
    """If multiple values separated by comma, take first one."""
    assert _extract_answer("答案：40，13") == "40"
    assert _extract_answer("答案：北京，上海") == "北京"


def test_strip_leading_labels():
    """Strip leading labels like '面积='."""
    assert _extract_answer("面积=40平方米") == "40"
    assert _extract_answer("体积=100立方厘米") == "100"


def test_normalize_whitespace():
    """Normalize internal whitespace so '18 世纪' matches '18世纪'."""
    assert _extract_answer("答案：18 世纪") == "18世纪"


def test_empty_input():
    """Empty input should return empty string."""
    assert _extract_answer("") == ""
    assert _extract_answer("   ") == ""


def test_no_prefix():
    """If no prefix, just strip and normalize."""
    assert _extract_answer("北京") == "北京"
    assert _extract_answer("  Paris  ") == "Paris"


# --- Additional edge cases (30+) ---

def test_none_input(self=None):
    """None input returns empty."""
    assert _extract_answer(None) == ""


def test_fullwidth_colon():
    """Full-width colon in prefix."""
    assert _extract_answer("答案：亚洲") == "亚洲"


def test_mixed_colons():
    """Mixed colons with no space."""
    assert _extract_answer("答案:亚洲") == "亚洲"


def test_trailing_unit_yuan():
    """31元 → 31"""
    assert _extract_answer("31元") == "31"


def test_trailing_unit_square_km():
    """40平方厘米 → 40"""
    assert _extract_answer("40平方厘米") == "40"


def test_trailing_unit_parenthetical():
    """碳（C） → 碳"""
    assert _extract_answer("碳（C）") == "碳"


def test_whitespace_normalization():
    """18 世纪 → 18世纪"""
    assert _extract_answer("18 世纪") == "18世纪"


def test_comma_separated_multi_value_first():
    """40平方厘米，13厘米 → 40 (after unit stripping)"""
    result = _extract_answer("40平方厘米，13厘米")
    assert result == "40"


def test_labels_stripped():
    """面积=100 → 100"""
    assert _extract_answer("面积=100") == "100"


def test_trailing_punctuation():
    """北京。 → 北京"""
    assert _extract_answer("北京。") == "北京"


def test_surrounding_double_quotes():
    r"""Strip surrounding double quotes from answer."""
    assert _extract_answer('"北京"') == "北京"


def test_surrounding_single_quotes():
    """'北京' → 北京"""
    assert _extract_answer("'北京'") == "北京"


def test_number_with_commas_not_split():
    """1,234 should NOT be split — it's a number format."""
    # The extractor preserves commas in number-like strings
    assert _extract_answer("1,234") == "1,234"


def test_negative_number():
    """-5 → -5"""
    assert _extract_answer("-5") == "-5"


def test_decimal_number():
    """3.14 → 3.14"""
    assert _extract_answer("3.14") == "3.14"


def test_metric_unit_kg():
    """50kg → 50"""
    assert _extract_answer("50kg") == "50"


def test_metric_unit_cm():
    """100cm → 100"""
    assert _extract_answer("100cm") == "100"


def test_metric_unit_km():
    """5km → 5"""
    assert _extract_answer("5km") == "5"


def test_time_unit_hours():
    """3小时 → 3"""
    assert _extract_answer("3小时") == "3"


def test_temperature_celsius():
    """25℃ → 25"""
    assert _extract_answer("25℃") == "25"


def test_temperature_fahrenheit():
    """98.6°F → 98.6"""
    assert _extract_answer("98.6°F") == "98.6"


def test_currency_usd():
    """$100 → $100 (USD sign not stripped by current rules)"""
    # Current regex only strips Chinese currency symbols
    assert _extract_answer("$100") == "$100"


def test_currency_rmb():
    """人民币50 → 人民币50 (人民币 prefix not stripped by current rules)"""
    # The trailing unit regex strips 人民币 from END of string, not beginning
    assert _extract_answer("人民币50") == "人民币50"


def test_volume_unit():
    """100立方米 → 100"""
    assert _extract_answer("100立方米") == "100"


def test_area_unit_hectare():
    """5公顷 → 5"""
    assert _extract_answer("5公顷") == "5"


def test_weight_unit_ton():
    """2吨 → 2"""
    assert _extract_answer("2吨") == "2"


def test_count_unit():
    """3个 → 3"""
    assert _extract_answer("3个") == "3"


def test_complex_cot():
    """Complex chain of thought with multiple lines ending in answer prefix."""
    text = (
        "首先，我们需要分析这个问题。\n"
        "第一步：确定已知条件\n"
        "第二步：应用公式\n"
        "答案：北京\n"
    )
    assert _extract_answer(text) == "北京"


def test_nested_parentheses():
    """答案：北京（中国） → 北京"""
    assert _extract_answer("答案：北京（中国）") == "北京"


def test_answer_with_space_inside():
    """答 案 ： 亚洲 → 案：亚洲 (prefix '答' stripped, spaces normalized)"""
    # The regex matches "答" as prefix (答[案题]?), strips it, then normalizes whitespace
    assert _extract_answer("答 案 ： 亚洲") == "案：亚洲"


def test_quarter_unit():
    """1/4 → 1/4 (fraction preserved)"""
    # Fractions don't have unit suffixes to strip
    assert _extract_answer("1/4") == "1/4"


def test_percent_unit():
    """50% → 50% (percent sign not stripped by current rules)"""
    assert _extract_answer("50%") == "50%"


def test_meter_unit():
    """10米 → 10"""
    assert _extract_answer("10米") == "10"


def test_liter_unit():
    """5升 → 5"""
    assert _extract_answer("5升") == "5"


def test_second_unit():
    """30秒 → 30"""
    assert _extract_answer("30秒") == "30"


def test_year_unit():
    """2024年 → 2024"""
    assert _extract_answer("2024年") == "2024"


def test_scientific_notation():
    """1.5e10 → 1.5e10 (scientific notation preserved)"""
    assert _extract_answer("1.5e10") == "1.5e10"


def test_multiple_prefixes():
    """Multiple answer prefixes in different lines."""
    text = "Step 1...\nStep 2...\n答案：test\nFinal Answer: test"
    assert _extract_answer(text) == "test"
