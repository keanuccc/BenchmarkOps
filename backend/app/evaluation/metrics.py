"""Pluggable registry of scoring metrics.

A metric is a pure callable ``(prediction, expected, **kwargs) -> float`` that
returns a score in ``[0, 1]``. This module is stateless, dependency-free (no DB,
no service imports) so the Evaluation Engine can reuse it standalone.

Register new metrics with the ``register`` decorator:

    @register("my_metric")
    def my_metric(prediction: str, expected: str | None, **kwargs) -> float:
        ...
"""
from __future__ import annotations

import re
from collections.abc import Callable
from typing import ParamSpec

from app.core.exceptions import ValidationError

P = ParamSpec("P")
Metric = Callable[..., float]

_METRICS: dict[str, Metric] = {}


def register(name: str) -> Callable[[Metric], Metric]:
    """Decorator registering a metric callable under ``name``."""

    def _wrap(fn: Metric) -> Metric:
        _METRICS[name] = fn
        return fn

    return _wrap


def get_metric(name: str) -> Metric:
    """Return the metric callable for ``name`` (raises ValidationError if unknown)."""
    metric = _METRICS.get(name)
    if metric is None:
        raise ValidationError(f"Unknown metric: {name!r}")
    return metric


def list_metrics() -> list[str]:
    """Return all registered metric names."""
    return sorted(_METRICS)


# Default metric per benchmark type (consumed by the Benchmark service).
DEFAULT_METRIC_FOR_TYPE: dict[str, str] = {
    "qa": "exact_match_ci",
    "classification": "exact_match_ci",
    "coding": "contains",
    "generation": "f1_token",
    "agent": "contains",
}


@register("exact_match")
def exact_match(prediction: str, expected: str | None, **kwargs) -> float:
    return 1.0 if prediction.strip() == (expected or "").strip() else 0.0


@register("exact_match_ci")
def exact_match_ci(prediction: str, expected: str | None, **kwargs) -> float:
    return (
        1.0
        if prediction.strip().lower() == (expected or "").strip().lower()
        else 0.0
    )


@register("contains")
def contains(prediction: str, expected: str | None, **kwargs) -> float:
    exp = (expected or "").strip()
    if not exp:
        return 0.0
    return 1.0 if exp.lower() in prediction.lower() else 0.0


@register("f1_token")
def f1_token(prediction: str, expected: str | None, **kwargs) -> float:
    pred_tokens = prediction.lower().split()
    exp_tokens = (expected or "").lower().split()
    if not pred_tokens or not exp_tokens:
        return 0.0
    common = set(pred_tokens) & set(exp_tokens)
    if not common:
        return 0.0
    precision = len(common) / len(pred_tokens)
    recall = len(common) / len(exp_tokens)
    return 2 * precision * recall / (precision + recall)


@register("numeric_match")
def numeric_match(prediction: str, expected: str | None, **kwargs) -> float:
    def _to_float(value: str | None) -> float | None:
        cleaned = re.sub(r"[^0-9.\-]", "", (value or "").strip())
        if cleaned in ("", "-", ".", "-."):
            return None
        try:
            return float(cleaned)
        except ValueError:
            return None

    a = _to_float(prediction)
    b = _to_float(expected)
    if a is None or b is None:
        return 0.0
    return 1.0 if abs(a - b) < 1e-6 else 0.0
