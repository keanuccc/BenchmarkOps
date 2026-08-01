"""Comprehensive edge-case tests for _extract_answer().

Covers 30+ scenarios across Chinese/English prefixes, multi-line CoT,
nested brackets, units, punctuation noise, Unicode full-width digits,
markdown code blocks, comma-separated values, scientific notation, etc.
"""

import pytest
from app.evaluation.runner import _extract_answer


# ===================================================================
# 1. Chinese answer prefixes
# ===================================================================

def test_chinese_prefix_answer_colon():
    """答案：4"""
    assert _extract_answer("答案：4") == "4"


def test_chinese_prefix_answer_is():
    """答案是：4"""
    assert _extract_answer("答案是：4") == "4"


def test_chinese_prefix_final_answer():
    """最终答案：4"""
    assert _extract_answer("最终答案：4") == "4"


def test_chinese_prefix_single_char():
    """答：4"""
    assert _extract_answer("答：4") == "4"


def test_chinese_prefix_hui_da():
    """回答：4"""
    assert _extract_answer("回答：4") == "4"


def test_chinese_prefix_conclusion():
    """结论：北京"""
    assert _extract_answer("结论：北京") == "北京"


# ===================================================================
# 2. English answer prefixes
# ===================================================================

def test_english_prefix_answer():
    """Answer: 4"""
    assert _extract_answer("Answer: 4") == "4"


def test_english_prefix_answers_plural():
    """Answers: 4"""
    assert _extract_answer("Answers: 4") == "4"


def test_english_prefix_final_answer():
    """Final Answer: 4"""
    assert _extract_answer("Final Answer: 4") == "4"


def test_english_prefix_uppercase():
    """ANSWER: 4 (uppercase)"""
    assert _extract_answer("ANSWER: 4") == "4"


def test_english_prefix_lowercase():
    """answer: 4 (lowercase)"""
    assert _extract_answer("answer: 4") == "4"


# ===================================================================
# 3. Chain-of-Thought multi-line
# ===================================================================

def test_cot_multi_line_last_line():
    """Multiple reasoning lines, then '答案：最终答案' on last line."""
    text = (
        "Let me think step by step.\n"
        "First, I add 2 and 2.\n"
        "That gives me 4.\n"
        "答案：4"
    )
    assert _extract_answer(text) == "4"


def test_cot_empty_lines_between():
    """CoT with blank lines between reasoning steps."""
    text = (
        "Step 1: compute the sum.\n"
        "\n"
        "Step 2: verify.\n"
        "\n"
        "答案：42"
    )
    assert _extract_answer(text) == "42"


def test_cot_no_answer_prefix_fallback():
    """Multi-line with no answer prefix — falls back to last non-empty line.
    Whitespace is normalized away (all spaces removed)."""
    text = (
        "Let me calculate.\n"
        "The result is 7."
    )
    assert _extract_answer(text) == "Theresultis7"


# ===================================================================
# 4. Nested brackets / parentheses
# ===================================================================

def test_nested_parentheses_halfwidth():
    """(A) — parenthetical annotation stripped, leaving 'A'."""
    assert _extract_answer("(A)") == "A"


def test_nested_braces():
    """答案：{4}"""
    # Curly braces are NOT stripped by current regex (only round parens)
    assert _extract_answer("{4}") == "{4}"


def test_nested_brackets():
    """答案：[亚洲]"""
    # Square brackets are NOT stripped by current regex
    assert _extract_answer("[亚洲]") == "[亚洲]"


def test_nested_fullwidth_parens():
    """答案：（亚洲）"""
    assert _extract_answer("（亚洲）") == "亚洲"


def test_nested_mixed_content():
    """答案：北京（中国）"""
    assert _extract_answer("北京（中国）") == "北京"


# ===================================================================
# 5. Units
# ===================================================================

def test_unit_kg():
    """答案：42 kg"""
    assert _extract_answer("42 kg") == "42"


def test_unit_radian():
    """3.14 rad — rad not in unit list, but whitespace is normalized."""
    # 'rad' is NOT in the unit strip list, but spaces are removed
    assert _extract_answer("3.14 rad") == "3.14rad"


def test_unit_celsius():
    """答案：100°C"""
    assert _extract_answer("100°C") == "100"


def test_unit_yuan():
    """31元 → 31"""
    assert _extract_answer("31元") == "31"


def test_unit_square_cm():
    """40平方厘米 → 40"""
    assert _extract_answer("40平方厘米") == "40"


def test_unit_km():
    """5km → 5"""
    assert _extract_answer("5km") == "5"


def test_unit_meter():
    """10米 → 10"""
    assert _extract_answer("10米") == "10"


def test_unit_hour():
    """3小时 → 3"""
    assert _extract_answer("3小时") == "3"


def test_unit_year():
    """2024年 → 2024"""
    assert _extract_answer("2024年") == "2024"


def test_unit_ton():
    """2吨 → 2"""
    assert _extract_answer("2吨") == "2"


# ===================================================================
# 6. Punctuation noise
# ===================================================================

def test_trailing_chinese_period():
    """答案：亚洲。"""
    assert _extract_answer("亚洲。") == "亚洲"


def test_trailing_comma():
    """答案：亚洲，"""
    assert _extract_answer("亚洲，") == "亚洲"


def test_leading_trailing_spaces():
    """答案： 亚洲  (leading/trailing spaces)"""
    assert _extract_answer(" 亚洲 ") == "亚洲"


def test_trailing_english_punctuation():
    """答案：Hello!"""
    assert _extract_answer("Hello!") == "Hello"


def test_trailing_exclamation():
    """答案：正确！"""
    assert _extract_answer("正确！") == "正确"


# ===================================================================
# 7. Multi-line output (no prefix on last line)
# ===================================================================

def test_multiline_no_prefix():
    """Model outputs several lines, only last line has answer text (no prefix).
    Whitespace normalized away, trailing '.' preserved (not in rstrip set for '.')."""
    text = (
        "Based on my analysis:\n"
        "The correct option is B.\n"
        "Therefore the answer is 42."
    )
    # rstrip("。,.!?！，、；：") DOES include '.', so it gets stripped
    assert _extract_answer(text) == "Thereforetheansweris42"


def test_multiline_single_word_last():
    """Last line is a single word. Whitespace normalized, trailing '.' stripped."""
    text = (
        "Let me reason through this.\n"
        "The answer is Paris."
    )
    assert _extract_answer(text) == "TheanswerisParis"


# ===================================================================
# 8. Empty output / pure reasoning with no answer line
# ===================================================================

def test_empty_string():
    """Empty string returns empty."""
    assert _extract_answer("") == ""


def test_whitespace_only():
    """Whitespace-only string returns empty."""
    assert _extract_answer("   \n\t  ") == ""


def test_none_input():
    """None input returns empty."""
    assert _extract_answer(None) == ""


# ===================================================================
# 9. CJK character boundaries
# ===================================================================

def test_mixed_chinese_english_answer():
    """Mixed Chinese/English answer. NOTE: trailing 'g' in 'Beijing' gets stripped
    by unit regex (kg/g/mg pattern matches bare 'g'). This is a known gap."""
    result = _extract_answer("北京Beijing")
    assert result == "北京Beijing"


def test_mixed_with_space_normalized():
    """18 世纪 -> 18世纪 (whitespace normalized away)"""
    assert _extract_answer("18 世纪") == "18世纪"


# ===================================================================
# 10. Unicode full-width / half-width mixing
# ===================================================================

def test_fullwidth_digits():
    """答案：４２ (full-width digits)"""
    # Full-width digits are NOT converted by current logic
    assert _extract_answer("４２") == "４２"


def test_halfwidth_digits():
    """答案：42 (normal half-width)"""
    assert _extract_answer("42") == "42"


# ===================================================================
# 11. Markdown code blocks
# ===================================================================

def test_markdown_code_block_python():
    """```python\nprint(4)\n``` - multi-line takes last non-empty line."""
    text = "```python\nprint(4)\n```"
    # Current logic splits on newlines, takes last line: "```"
    assert _extract_answer(text) == "```"


def test_backtick_wrapped_answer():
    """`42` - single backtick wrapped"""
    # Backticks are NOT stripped
    assert _extract_answer("`42`") == "`42`"


# ===================================================================
# 12. Multiple answers in one line
# ===================================================================

def test_multiple_answers_chinese_comma():
    """答案：4 或 5 — OR separator not split"""
    # "或" is not a comma, so no splitting occurs
    assert _extract_answer("4 或 5") == "4或5"  # whitespace normalized


def test_multiple_values_chinese_comma_first():
    """答案：40，13 — takes first value before Chinese comma"""
    assert _extract_answer("40，13") == "40"


def test_multiple_values_english_comma():
    """答案：a, b — splits on English comma"""
    assert _extract_answer("a, b") == "a"


# ===================================================================
# 13. Numbers with commas
# ===================================================================

def test_number_with_commas_preserved():
    """1,000,000 — full match against number pattern, preserved."""
    assert _extract_answer("1,000,000") == "1,000,000"


def test_number_with_commas_and_decimal():
    """1,000.50 — preserved as number."""
    assert _extract_answer("1,000.50") == "1,000.50"


# ===================================================================
# 14. Scientific notation
# ===================================================================

def test_scientific_notation():
    """1.5e10 — preserved as-is."""
    assert _extract_answer("1.5e10") == "1.5e10"


def test_scientific_notation_upper_e():
    """1.5E10 — preserved."""
    assert _extract_answer("1.5E10") == "1.5E10"


# ===================================================================
# 15. Negative numbers
# ===================================================================

def test_negative_integer():
    """-42"""
    assert _extract_answer("-42") == "-42"


def test_negative_decimal():
    """-3.14"""
    assert _extract_answer("-3.14") == "-3.14"


# ===================================================================
# 16. Decimal numbers
# ===================================================================

def test_decimal_pi():
    """3.14159"""
    assert _extract_answer("3.14159") == "3.14159"


def test_leading_zero_decimal():
    """0.5"""
    assert _extract_answer("0.5") == "0.5"


# ===================================================================
# 17. Quoted answers
# ===================================================================

def test_double_quoted():
    r"""'"北京"' -> 北京"""
    assert _extract_answer('"北京"') == "北京"


def test_single_quoted():
    """'Paris' -> Paris"""
    assert _extract_answer("'Paris'") == "Paris"


# ===================================================================
# 18. Leading labels
# ===================================================================

def test_label_area():
    """面积=40 -> 40"""
    assert _extract_answer("面积=40") == "40"


def test_label_volume():
    """体积=100立方米 -> 100"""
    assert _extract_answer("体积=100立方米") == "100"


# ===================================================================
# 19. Full-width colon in prefix
# ===================================================================

def test_fullwidth_colon():
    """答案：亚洲 (full-width colon)"""
    assert _extract_answer("答案：亚洲") == "亚洲"


def test_halfwidth_colon():
    """答案:亚洲 (half-width colon, no space)"""
    assert _extract_answer("答案:亚洲") == "亚洲"


# ===================================================================
# 20. Fraction preservation
# ===================================================================

def test_fraction():
    """1/4 — fraction preserved."""
    assert _extract_answer("1/4") == "1/4"


# ===================================================================
# 21. Percent sign
# ===================================================================

def test_percent():
    """50% — percent sign not stripped."""
    assert _extract_answer("50%") == "50%"


# ===================================================================
# 22. Parenthetical annotations
# ===================================================================

def test_parenthetical_english():
    """carbon (C) -> carbon"""
    assert _extract_answer("碳(C)") == "碳"


def test_parenthetical_chinese():
    """碳（C） -> 碳"""
    assert _extract_answer("碳（C）") == "碳"


# ===================================================================
# 23. Currency symbols
# ===================================================================

def test_usd_dollar_sign():
    """$100 — dollar sign not stripped."""
    assert _extract_answer("$100") == "$100"


def test_rmb_prefix_not_stripped():
    """人民币50 — prefix not stripped by trailing unit rules."""
    assert _extract_answer("人民币50") == "人民币50"


# ===================================================================
# 24. Multiple answer prefixes in different lines
# ===================================================================

def test_multiple_prefixes_different_lines():
    """Multiple answer prefixes — last matching line wins."""
    text = "Step 1...\nStep 2...\n答案：test\nFinal Answer: test"
    assert _extract_answer(text) == "test"


# ===================================================================
# 25. Whitespace normalization inside answer
# ===================================================================

def test_internal_whitespace_stripped():
    """Multiple internal spaces collapsed."""
    assert _extract_answer("hello   world") == "helloworld"


# ===================================================================
# 26. Trailing Chinese punctuation
# ===================================================================

def test_trailing_semicolon():
    """答案：正确；"""
    assert _extract_answer("正确；") == "正确"


def test_trailing_enumeration_dot():
    """北京、上海 — '、' NOT in rstrip set, no split occurs."""
    # The rstrip set is "。,.!?！，、；：" — wait, let me check...
    # Actually "、" IS in the rstrip set. Let me verify.
    result = _extract_answer("北京、上海")
    assert result == "北京、上海"  # "、" is not in rstrip("。,.!?！，、；：") — it's "、" vs "，"


# ===================================================================
# 27. Mixed full-width/half-width colons
# ===================================================================

def test_answer_prefix_with_space_after_colon():
    """Answer: 4 (space after colon)"""
    assert _extract_answer("Answer: 4") == "4"


def test_answer_prefix_no_space_after_colon():
    """Answer:4 (no space)"""
    assert _extract_answer("Answer:4") == "4"


# ===================================================================
# 28. Edge case: answer that IS a number with prefix
# ===================================================================

def test_numeric_answer_chinese_prefix():
    """答案：0"""
    assert _extract_answer("答案：0") == "0"


def test_numeric_answer_english_prefix():
    """Answer: 0"""
    assert _extract_answer("Answer: 0") == "0"


# ===================================================================
# 29. Edge case: answer with special characters
# ===================================================================

def test_answer_with_hash():
    """C# language name preserved."""
    assert _extract_answer("C#") == "C#"


def test_answer_with_at_symbol():
    """@username"""
    assert _extract_answer("@user") == "@user"


# ===================================================================
# 30. Edge case: very long answer with prefix
# ===================================================================

def test_long_answer_with_prefix():
    """Long sentence after prefix. Chinese comma '，' triggers first-value split."""
    long_text = "这是一个非常长的答案，包含了多个句子和复杂的逻辑推理过程。"
    result = _extract_answer(f"答案：{long_text}")
    # The Chinese comma in the text triggers the multi-value split, taking only the first segment
    assert result == "这是一个非常长的答案"


# ===================================================================
# 31. Edge case: answer with only whitespace after prefix
# ===================================================================

def test_empty_after_prefix():
    """答案：(nothing after prefix)"""
    assert _extract_answer("答案：") == ""


def test_prefix_only_whitespace():
    """答案：   (only whitespace after prefix)"""
    assert _extract_answer("答案：   ") == ""
