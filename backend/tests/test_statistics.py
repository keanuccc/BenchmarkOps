"""Unit tests for the statistical significance helpers."""
from __future__ import annotations

import pytest

from app.evaluation.statistics import (
    bootstrap_ci,
    mcnemar_p_value,
    paired_bootstrap_test,
)


def test_bootstrap_ci_mean_and_bounds():
    values = [1.0, 1.0, 1.0, 0.0, 0.0]
    result = bootstrap_ci(values, n_iterations=1000, seed=7)
    assert result["n"] == 5
    assert result["mean"] == pytest.approx(0.6)
    assert 0.0 <= result["lower"] <= result["mean"] <= result["upper"] <= 1.0


def test_bootstrap_ci_empty():
    result = bootstrap_ci([])
    assert result == {"mean": 0.0, "lower": 0.0, "upper": 0.0, "n": 0}


def test_paired_bootstrap_clear_winner():
    a = [1.0] * 8
    b = [0.0] * 8
    result = paired_bootstrap_test(a, b, n_iterations=1000, seed=3)
    assert result["mean_diff"] == pytest.approx(1.0)
    assert result["significant"] is True
    assert result["p_value"] < 0.01


def test_paired_bootstrap_no_difference():
    a = [1.0, 0.0, 1.0, 0.0]
    b = [1.0, 0.0, 1.0, 0.0]
    result = paired_bootstrap_test(a, b, n_iterations=1000, seed=3)
    assert result["mean_diff"] == pytest.approx(0.0)
    assert result["significant"] is False
    assert result["p_value"] > 0.05


def test_paired_bootstrap_rejects_length_mismatch():
    with pytest.raises(ValueError):
        paired_bootstrap_test([1.0], [1.0, 0.0])


def test_mcnemar_identical_is_not_significant():
    a = [True, True, False, False]
    b = [True, True, False, False]
    assert mcnemar_p_value(a, b) == pytest.approx(1.0)


def test_mcnemar_discordant_is_smaller():
    a = [True, True, True, True]
    b = [True, True, False, False]
    p = mcnemar_p_value(a, b)
    assert 0.0 < p < 1.0
