"""Statistical significance helpers for A/B model comparison.

Pure-Python (no numpy/scipy) so the backend keeps its current dependency
footprint. All bootstrap procedures accept a ``seed`` for reproducible results.
"""
from __future__ import annotations

import math
import random
from statistics import fmean


def _resample_indices(n: int, rng: random.Random) -> list[int]:
    return [rng.randrange(n) for _ in range(n)]


def bootstrap_ci(
    values: list[float],
    *,
    n_iterations: int = 2000,
    confidence: float = 0.95,
    seed: int | None = None,
) -> dict[str, float]:
    """Percentile bootstrap confidence interval for the mean.

    Returns ``{"mean", "lower", "upper", "n"}``. ``lower``/``upper`` are the
    ``(1 - confidence) / 2`` and ``(1 + confidence) / 2`` quantiles of the
    bootstrap mean distribution.
    """
    if not values:
        return {"mean": 0.0, "lower": 0.0, "upper": 0.0, "n": 0}
    if not 0.0 < confidence < 1.0:
        raise ValueError("confidence must be between 0 and 1")
    n = len(values)
    rng = random.Random(seed)
    means: list[float] = []
    for _ in range(n_iterations):
        idx = _resample_indices(n, rng)
        means.append(fmean(values[i] for i in idx))
    means.sort()
    tail = (1.0 - confidence) / 2.0
    lower_idx = int(tail * n_iterations)
    upper_idx = int((1.0 - tail) * n_iterations) - 1
    lower_idx = max(0, min(lower_idx, n_iterations - 1))
    upper_idx = max(0, min(upper_idx, n_iterations - 1))
    return {
        "mean": fmean(values),
        "lower": means[lower_idx],
        "upper": means[upper_idx],
        "n": n,
    }


def paired_bootstrap_test(
    a: list[float],
    b: list[float],
    *,
    n_iterations: int = 2000,
    confidence: float = 0.95,
    seed: int | None = None,
) -> dict[str, float | bool | int]:
    """Bootstrap test for the paired difference ``a - b``.

    Both lists must have the same length and are assumed to be aligned by row
    (same dataset). Returns the mean difference, its percentile confidence
    interval, and a two-sided p-value under the null hypothesis that the mean
    difference is zero.
    """
    if len(a) != len(b):
        raise ValueError("a and b must have the same length")
    if not a:
        return {
            "mean_diff": 0.0,
            "ci_lower": 0.0,
            "ci_upper": 0.0,
            "p_value": 1.0,
            "significant": False,
            "n": 0,
        }
    observed = fmean(a) - fmean(b)
    n = len(a)
    rng = random.Random(seed)

    # Percentile CI on the observed paired differences.
    diffs = [ai - bi for ai, bi in zip(a, b)]
    ci_means: list[float] = []
    for _ in range(n_iterations):
        idx = _resample_indices(n, rng)
        ci_means.append(fmean(diffs[i] for i in idx))
    ci_means.sort()
    tail = (1.0 - confidence) / 2.0
    lower_idx = int(tail * n_iterations)
    upper_idx = int((1.0 - tail) * n_iterations) - 1
    lower_idx = max(0, min(lower_idx, n_iterations - 1))
    upper_idx = max(0, min(upper_idx, n_iterations - 1))

    # p-value via centered bootstrap (H0: mean difference == 0).
    centered = [d - observed for d in diffs]
    null_means: list[float] = []
    for _ in range(n_iterations):
        idx = _resample_indices(n, rng)
        null_means.append(fmean(centered[i] for i in idx))
    null_means.sort()
    extreme = min(
        sum(1 for m in null_means if m >= abs(observed)),
        sum(1 for m in null_means if m <= -abs(observed)),
    )
    # Two-sided p-value; +1 in the denominator avoids a hard zero.
    p_value = 2.0 * (extreme + 1) / (n_iterations + 1)
    p_value = min(1.0, max(0.0, p_value))

    return {
        "mean_diff": observed,
        "ci_lower": ci_means[lower_idx],
        "ci_upper": ci_means[upper_idx],
        "p_value": p_value,
        "significant": bool(p_value < (1.0 - confidence)),
        "n": n,
    }


def mcnemar_p_value(a_correct: list[bool], b_correct: list[bool]) -> float:
    """McNemar test p-value for paired binary (pass/fail) outcomes.

    Uses the continuity-corrected statistic and the chi-square(df=1) CDF via
    ``math.erfc``, so no scipy dependency is required.
    """
    if len(a_correct) != len(b_correct):
        raise ValueError("a_correct and b_correct must have the same length")
    b_only = c_only = 0
    for a_ok, b_ok in zip(a_correct, b_correct):
        if a_ok and not b_ok:
            b_only += 1
        elif not a_ok and b_ok:
            c_only += 1
    discordant = b_only + c_only
    if discordant == 0:
        return 1.0
    # Continuity-corrected McNemar statistic.
    chi2 = (abs(b_only - c_only) - 1.0) ** 2 / discordant
    if chi2 < 0:
        chi2 = 0.0
    # chi-square(df=1) upper-tail probability == erfc(sqrt(chi2) / sqrt(2)).
    return float(math.erfc(math.sqrt(chi2) / math.sqrt(2.0)))
