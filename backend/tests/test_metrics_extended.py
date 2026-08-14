"""Tests for extended metrics: code_pass / semantic_similarity / tool_call."""
from __future__ import annotations

import pytest

from app.evaluation.metrics import _call_metric, get_metric


@pytest.mark.asyncio
async def test_code_pass_runs_tests_and_scores_pass_rate():
    metric = get_metric("code_pass")
    code = "def add(a, b):\n    return a + b\n"
    tests = ["assert add(1, 2) == 3", "assert add(0, 0) == 0"]
    score = await _call_metric(
        metric,
        code,
        "def add(a, b):\n    return a + b\n",
        expected_raw={"answer": code, "tests": tests},
    )
    assert score == 1.0


@pytest.mark.asyncio
async def test_code_pass_partial_and_failure():
    metric = get_metric("code_pass")
    good = "def add(a, b):\n    return a + b\n"
    bad = "def add(a, b):\n    return a - b\n"

    # One passing + one failing test -> 0.5 (the failing case simulates a
    # dataset test the model output does not satisfy).
    partial = await _call_metric(
        metric,
        good,
        good,
        expected_raw={"tests": ["assert add(1, 2) == 3", "assert add(2, 2) == 5"]},
    )
    assert partial == 0.5

    failed = await _call_metric(
        metric,
        bad,
        bad,
        expected_raw={"tests": ["assert add(1, 2) == 3"]},
    )
    assert failed == 0.0

    # No tests -> unverifiable -> 0.
    no_tests = await _call_metric(metric, good, good, expected_raw={})
    assert no_tests == 0.0


@pytest.mark.asyncio
async def test_code_pass_timeout_scores_zero():
    metric = get_metric("code_pass")
    code = "import time\ntime.sleep(10)\n"
    score = await _call_metric(
        metric,
        code,
        code,
        expected_raw={"tests": ["assert True"]},
        timeout_seconds=1,
    )
    assert score == 0.0


@pytest.mark.asyncio
async def test_code_pass_sandbox_blocks_dangerous_imports():
    metric = get_metric("code_pass")
    dangerous = "import os\nprint(os.getcwd())\n"
    score = await _call_metric(
        metric,
        dangerous,
        dangerous,
        expected_raw={"tests": ["assert True"]},
    )
    assert score == 0.0


@pytest.mark.asyncio
async def test_code_pass_sandbox_allows_safe_stdlib():
    metric = get_metric("code_pass")
    safe = "import math\ndef f(x):\n    return math.sqrt(x)\n"
    score = await _call_metric(
        metric,
        safe,
        safe,
        expected_raw={"tests": ["assert f(4) == 2.0"]},
    )
    assert score == 1.0


def test_semantic_similarity_exact_and_rephrase():
    metric = get_metric("semantic_similarity")
    assert metric("退款需要1-3个工作日", "退款需要1-3个工作日") == 1.0

    rephrased = metric("退款一般需要一到三个工作日", "退款需要1-3个工作日")
    assert rephrased > 0.5

    unrelated = metric("今天天气很好", "退款需要1-3个工作日")
    assert unrelated < 0.5


def test_tool_call_checks_name_and_arguments():
    metric = get_metric("tool_call")
    output = (
        '```json\n{"name": "search_orders", '
        '"arguments": {"order_id": "DD123", "customer": "zhang"}}\n```'
    )
    assert metric(output, "search_orders", expected_raw={"arguments": {"order_id": None}}) == 1.0

    # Missing required argument key -> partial credit.
    missing = metric(
        output,
        "search_orders",
        expected_raw={"arguments": {"order_id": None, "amount": None}},
    )
    assert missing == 0.5

    # Wrong tool -> 0.
    assert metric(output, "refund_order", expected_raw={}) == 0.0


def test_tool_call_openai_function_format():
    metric = get_metric("tool_call")
    output = (
        '{"function": {"name": "get_weather", "arguments": {"city": "beijing"}}}'
    )
    assert metric(output, "get_weather") == 1.0
