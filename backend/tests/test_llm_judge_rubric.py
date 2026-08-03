"""Tests for the dimension-based rubric judge metric."""
import asyncio
import json
from unittest.mock import patch

import pytest

from app.core.exceptions import ValidationError
from app.evaluation.metrics import MetricEvaluationError, llm_judge_rubric


class MockCompletionResult:
    def __init__(self, text: str):
        self.text = text
        self.prompt_tokens = 100
        self.completion_tokens = 20
        self.latency_ms = 50
        self.total_tokens = 120


class MockProvider:
    def __init__(self, response_text: str):
        self.response_text = response_text
        self.calls = 0

    async def complete(self, request):
        self.calls += 1
        return MockCompletionResult(self.response_text)


DIMS = [
    {"name": "correctness", "description": "答案是否正确", "weight": 1},
    {"name": "completeness", "description": "是否完整", "weight": 1},
]


def _run_judge(prediction, expected, provider, **kwargs):
    with patch("app.providers.registry.get_provider") as mock_get_provider:
        mock_get_provider.return_value = provider
        return asyncio.run(
            llm_judge_rubric(
                prediction,
                expected,
                judge_model="judge-model",
                judge_provider="mock",
                **kwargs,
            )
        )


def test_rubric_weighted_composite():
    provider = MockProvider(
        json.dumps({"scores": {"correctness": 5, "completeness": 3}})
    )
    score = _run_judge("answer", "expected", provider, dimensions=DIMS, scale=5)
    assert score == pytest.approx(0.8)  # (1.0 + 0.6) / 2


def test_rubric_honors_dimension_weights():
    weighted = [
        {"name": "correctness", "weight": 2},
        {"name": "completeness", "weight": 1},
    ]
    provider = MockProvider(
        json.dumps({"scores": {"correctness": 5, "completeness": 3}})
    )
    score = _run_judge("answer", "expected", provider, dimensions=weighted, scale=5)
    assert score == pytest.approx((2 * 1.0 + 1 * 0.6) / 3)


def test_rubric_scale_10_normalization():
    provider = MockProvider(
        json.dumps({"scores": {"correctness": 8, "completeness": 6}})
    )
    score = _run_judge("answer", "expected", provider, dimensions=DIMS, scale=10)
    assert score == pytest.approx((0.8 + 0.6) / 2)


def test_rubric_accepts_fenced_json():
    provider = MockProvider(
        '```json\n{"scores": {"correctness": 5, "completeness": 4}}\n```'
    )
    score = _run_judge("fenced pred", "fenced exp", provider, dimensions=DIMS, scale=5)
    assert score == pytest.approx(0.9)


def test_rubric_line_based_fallback():
    provider = MockProvider("correctness: 5\ncompleteness: 3")
    score = _run_judge("line pred", "line exp", provider, dimensions=DIMS, scale=5)
    assert score == pytest.approx(0.8)


def test_rubric_missing_dimension_scores_zero():
    provider = MockProvider(json.dumps({"scores": {"correctness": 5}}))
    score = _run_judge("missing pred", "missing exp", provider, dimensions=DIMS, scale=5)
    assert score == pytest.approx(0.5)


def test_rubric_invalid_response_is_conservative():
    provider = MockProvider("I think it is good.")
    assert (
        _run_judge("invalid pred", "invalid exp", provider, dimensions=DIMS, scale=5)
        == 0.0
    )


def test_rubric_invalid_response_can_raise():
    provider = MockProvider("not json at all")
    with pytest.raises(MetricEvaluationError):
        with patch("app.providers.registry.get_provider") as mock_get_provider:
            mock_get_provider.return_value = provider
            asyncio.run(
                llm_judge_rubric(
                    "answer",
                    "expected",
                    dimensions=DIMS,
                    scale=5,
                    judge_provider="mock",
                    raise_on_error=True,
                )
            )


def test_rubric_empty_expected_returns_zero_without_provider():
    with patch("app.providers.registry.get_provider") as mock_get_provider:
        result = asyncio.run(llm_judge_rubric("answer", "", dimensions=DIMS, scale=5))
        assert result == 0.0
        mock_get_provider.assert_not_called()


def test_rubric_default_dimensions_per_benchmark_type():
    provider = MockProvider(
        json.dumps(
            {"scores": {"correctness": 5, "completeness": 5, "coherence": 3}}
        )
    )
    score = _run_judge(
        "answer", "expected", provider, benchmark_type="generation", scale=5
    )
    assert score == pytest.approx((1.0 + 1.0 + 0.6) / 3)


def test_rubric_reuses_cache():
    provider = MockProvider(json.dumps({"scores": {"correctness": 5, "completeness": 5}}))
    first = _run_judge("rubric-cache-pred", "rubric-cache-exp", provider, dimensions=DIMS, scale=5)
    second = _run_judge("rubric-cache-pred", "rubric-cache-exp", provider, dimensions=DIMS, scale=5)
    assert first == second == 1.0
    assert provider.calls == 1


def test_rubric_invalid_config_is_conservative():
    provider = MockProvider(json.dumps({"scores": {"correctness": 5}}))
    assert _run_judge("answer", "expected", provider, dimensions=[], scale=1) == 0.0


def test_rubric_invalid_config_validation_error():
    from app.evaluation.metrics import _normalize_rubric_dimensions

    with pytest.raises(ValidationError):
        _normalize_rubric_dimensions(
            [{"name": "", "weight": 1}], benchmark_type="qa"
        )
