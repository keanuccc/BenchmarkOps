"""Unit tests for LLM-as-judge calibration helpers."""
from __future__ import annotations

import pytest

from app.evaluation.judge_calibration import (
    binary_calibration_metrics,
    cohen_kappa,
    judge_agreement,
)


def test_binary_calibration_perfect():
    metrics = binary_calibration_metrics(
        gold_labels=[1, 1, 0, 0],
        judge_labels=[1, 1, 0, 0],
    )
    assert metrics["accuracy"] == pytest.approx(1.0)
    assert metrics["precision"] == pytest.approx(1.0)
    assert metrics["recall"] == pytest.approx(1.0)
    assert metrics["f1"] == pytest.approx(1.0)
    assert metrics["confusion"] == {"tp": 2, "fp": 0, "tn": 2, "fn": 0}


def test_binary_calibration_mixed():
    metrics = binary_calibration_metrics(
        gold_labels=[1, 1, 0, 0],
        judge_labels=[1, 0, 1, 0],
    )
    assert metrics["accuracy"] == pytest.approx(0.5)
    assert metrics["precision"] == pytest.approx(0.5)
    assert metrics["recall"] == pytest.approx(0.5)


def test_binary_calibration_length_mismatch():
    with pytest.raises(ValueError):
        binary_calibration_metrics([1, 0], [1])


def test_cohen_kappa_perfect_agreement():
    assert cohen_kappa([1, 1, 0, 0], [1, 1, 0, 0]) == pytest.approx(1.0)


def test_cohen_kappa_complete_disagreement():
    assert cohen_kappa([1, 1, 0, 0], [0, 0, 1, 1]) == pytest.approx(-1.0)


def test_judge_agreement_returns_rate_and_kappa():
    result = judge_agreement([1, 1, 0, 0], [1, 1, 0, 0])
    assert result["n"] == 4
    assert result["agreement_rate"] == pytest.approx(1.0)
    assert result["cohen_kappa"] == pytest.approx(1.0)
