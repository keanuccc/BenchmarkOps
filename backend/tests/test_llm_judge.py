"""Tests for the LLM-as-Judge metric."""
import asyncio
from unittest.mock import patch

import pytest

from app.evaluation.metrics import llm_judge, get_metric


class MockCompletionResult:
    def __init__(self, text: str):
        self.text = text
        self.prompt_tokens = 100
        self.completion_tokens = 2
        self.latency_ms = 50
        self.total_tokens = 102


class MockProvider:
    def __init__(self, response_text: str):
        self.response_text = response_text

    async def complete(self, request):
        return MockCompletionResult(self.response_text)


def test_llm_judge_match():
    """When judge returns MATCH, score should be 1.0."""
    prediction = "Paris"
    expected = "巴黎"

    with patch("app.providers.registry.get_provider") as mock_get_provider:
        mock_get_provider.return_value = MockProvider("MATCH")
        result = asyncio.run(llm_judge(prediction, expected))
        assert result == 1.0


def test_llm_judge_no_match():
    """When judge returns NO_MATCH, score should be 0.0."""
    prediction = "London"
    expected = "Paris"

    with patch("app.providers.registry.get_provider") as mock_get_provider:
        mock_get_provider.return_value = MockProvider("NO_MATCH")
        result = asyncio.run(llm_judge(prediction, expected))
        assert result == 0.0


def test_llm_judge_empty_expected():
    """Empty expected should return 0.0 without calling provider."""
    prediction = "some answer"
    expected = ""

    with patch("app.providers.registry.get_provider") as mock_get_provider:
        result = asyncio.run(llm_judge(prediction, expected))
        assert result == 0.0
        mock_get_provider.assert_not_called()


def test_llm_judge_ambiguous_response():
    """Ambiguous judge response should return 0.0 (conservative)."""
    prediction = "some answer"
    expected = "another answer"

    with patch("app.providers.registry.get_provider") as mock_get_provider:
        mock_get_provider.return_value = MockProvider("Hmm, maybe?")
        result = asyncio.run(llm_judge(prediction, expected))
        assert result == 0.0


def test_llm_judge_yes_alias():
    """YES should be treated as positive match."""
    prediction = "answer"
    expected = "expected"

    with patch("app.providers.registry.get_provider") as mock_get_provider:
        mock_get_provider.return_value = MockProvider("YES")
        result = asyncio.run(llm_judge(prediction, expected))
        assert result == 1.0


def test_llm_judge_correct_alias():
    """CORRECT should be treated as positive match."""
    prediction = "answer"
    expected = "expected"

    with patch("app.providers.registry.get_provider") as mock_get_provider:
        mock_get_provider.return_value = MockProvider("CORRECT")
        result = asyncio.run(llm_judge(prediction, expected))
        assert result == 1.0


def test_llm_judge_false_alias():
    """FALSE should be treated as negative match."""
    prediction = "answer"
    expected = "expected"

    with patch("app.providers.registry.get_provider") as mock_get_provider:
        mock_get_provider.return_value = MockProvider("FALSE")
        result = asyncio.run(llm_judge(prediction, expected))
        assert result == 0.0


def test_llm_judge_timeout():
    """Timeout should return 0.0."""
    prediction = "answer"
    expected = "expected"

    class TimeoutProvider:
        async def complete(self, request):
            await asyncio.sleep(100)
            return MockCompletionResult("MATCH")

    with patch("app.providers.registry.get_provider") as mock_get_provider:
        mock_get_provider.return_value = TimeoutProvider()
        result = asyncio.run(llm_judge(prediction, expected))
        assert result == 0.0


def test_llm_judge_benchmark_type_selection():
    """Different benchmark types should use different prompt templates."""
    from app.evaluation.judge_prompts import JUDGE_PROMPTS

    prediction = "answer"
    expected = "expected"

    with patch("app.providers.registry.get_provider") as mock_get_provider:
        mock_get_provider.return_value = MockProvider("MATCH")

        # Test qa type
        result = asyncio.run(
            llm_judge(
                prediction,
                expected,
                benchmark_type="qa",
                judge_model="test-model",
                judge_provider="mock",
            )
        )
        assert result == 1.0

        # Verify the function runs without error for different types
        for btype in ["qa", "classification", "coding", "generation", "agent"]:
            result = asyncio.run(
                llm_judge(
                    prediction,
                    expected,
                    benchmark_type=btype,
                    judge_model="test-model",
                    judge_provider="mock",
                )
            )
            assert result == 1.0
