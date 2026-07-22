"""Pluggable registry of scoring metrics.

A metric is a callable ``(prediction, expected, *, expected_raw=None, **kwargs) -> float`` that
returns a score in ``[0, 1]``. Metrics may be either synchronous callables or async coroutines;
the runner dispatches via ``_call_metric()`` which handles both transparently.

- ``prediction``: the model's cleaned output string.
- ``expected``: the canonical answer string extracted by the runner.
- ``expected_raw``: the original expected dict/list from the dataset row, or
  ``None`` if unavailable. Metrics that need structural information (e.g.
  multi-answer sets, nested answer+reasoning) can read this instead of relying
  on the flattened string.

Register new metrics with the ``register`` decorator:

    @register("my_metric")
    def my_metric(prediction: str, expected: str | None, *,
                  expected_raw: dict | list | None = None,
                  **kwargs) -> float:
        ...
"""
from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Callable
from typing import ParamSpec

from app.core.exceptions import ValidationError

logger = logging.getLogger(__name__)

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


def _explicit_metric_suite(metric_config: dict | None) -> list | None:
    config = metric_config or {}
    spec_config = config.get("spec") or {}
    suite = config.get("metric_suite") or spec_config.get("metric_suite")
    return suite if isinstance(suite, list) else None


def has_metric_suite(metric_config: dict | None, spec: dict | None = None) -> bool:
    return bool(_explicit_metric_suite(metric_config))


def _configured_metric_suite(metric_config: dict | None, spec: dict | None = None) -> list | None:
    explicit = _explicit_metric_suite(metric_config)
    if explicit:
        return explicit
    suite = (spec or {}).get("metric_suite")
    return suite if isinstance(suite, list) else None


def normalize_metric_suite(
    metric_name: str,
    metric_config: dict | None = None,
    spec: dict | None = None,
) -> list[dict]:
    """Return a normalized MetricSuite list.

    Backward compatibility: benchmarks without an explicit ``metric_suite`` are
    represented as a one-item suite using the legacy metric and full config.
    """
    suite = _configured_metric_suite(metric_config, spec)
    if not suite:
        return [{"name": metric_name, "weight": 1.0, "config": metric_config or {}}]

    normalized: list[dict] = []
    for item in suite:
        if not isinstance(item, dict):
            raise ValidationError("metric_suite entries must be objects")
        name = item.get("name")
        if not isinstance(name, str) or not name:
            raise ValidationError("metric_suite entries require a metric name")
        try:
            weight = float(item.get("weight", 1.0))
        except (TypeError, ValueError) as exc:
            raise ValidationError(f"Invalid weight for metric {name!r}") from exc
        config = item.get("config") or {}
        if not isinstance(config, dict):
            raise ValidationError(f"Config for metric {name!r} must be an object")
        normalized.append(
            {
                "name": name,
                "weight": weight,
                "config": config,
            }
        )
    return normalized


def validate_metric_suite(metric_name: str, metric_config: dict | None = None) -> None:
    suite = normalize_metric_suite(metric_name, metric_config)
    total_weight = 0.0
    for item in suite:
        get_metric(item["name"])
        if item["weight"] < 0:
            raise ValidationError(f"Metric {item['name']!r} has negative weight")
        total_weight += item["weight"]
    if total_weight <= 0:
        raise ValidationError("metric_suite requires a positive total weight")


async def _call_metric(metric_fn: Metric, *args, **kwargs) -> float:
    """Invoke a metric function, handling both sync and async callables.

    Existing metrics are synchronous pure functions. New metrics like
    ``llm_judge`` may be coroutines (they call an LLM provider). This wrapper
    detects coroutine functions and awaits them transparently so the runner
    doesn't need to know which kind of metric it is calling.
    """
    if asyncio.iscoroutinefunction(metric_fn):
        return await metric_fn(*args, **kwargs)
    result = metric_fn(*args, **kwargs)
    if asyncio.isfuture(result) or isinstance(result, asyncio.Future):
        return await result
    return float(result)


# Default metric per benchmark type (consumed by the Benchmark service).
DEFAULT_METRIC_FOR_TYPE: dict[str, str] = {
    "qa": "exact_match_ci",
    "classification": "exact_match_ci",
    "coding": "contains",
    "generation": "f1_token",
    "agent": "contains",
}


def _flatten_strings(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, (int, float, bool)):
        return [str(value)]
    if isinstance(value, list):
        out: list[str] = []
        for item in value:
            out.extend(_flatten_strings(item))
        return out
    if isinstance(value, dict):
        out: list[str] = []
        for key in ("answer", "label", "output", "target", "ground_truth", "value", "text"):
            if key in value:
                out.extend(_flatten_strings(value[key]))
        return out
    return [str(value)]


def _exact_ci_candidates(expected: str | None, expected_raw: dict | list | None) -> list[str]:
    values = [expected or ""]
    if isinstance(expected_raw, list):
        values.extend(_flatten_strings(expected_raw))
    elif isinstance(expected_raw, dict):
        values.extend(_flatten_strings(expected_raw))
        aliases = expected_raw.get("aliases", [])
        values.extend(_flatten_strings(aliases))
    return [re.sub(r"\s+", "", v.strip()).lower() for v in values if v and v.strip()]


@register("exact_match")
def exact_match(prediction: str, expected: str | None, *, expected_raw: dict | list | None = None, **kwargs) -> float:
    pred = prediction.strip()
    exp = (expected or "").strip()
    if not exp:
        return 0.0
    # If expected_raw contains a list of valid answers, match any of them.
    if isinstance(expected_raw, list):
        return 1.0 if pred in [str(a).strip().lower() for a in expected_raw] else 0.0
    return 1.0 if pred.lower() == exp.lower() else 0.0


@register("exact_match_ci")
def exact_match_ci(prediction: str, expected: str | None, *, expected_raw: dict | list | None = None, **kwargs) -> float:
    pred_n = re.sub(r"\s+", "", prediction.strip()).lower()
    candidates = _exact_ci_candidates(expected, expected_raw)
    if not candidates:
        return 0.0
    if pred_n in candidates:
        return 1.0
    return 0.0


@register("contains")
def contains(prediction: str, expected: str | None, *, expected_raw: dict | list | None = None, **kwargs) -> float:
    exp = (expected or "").strip()
    if not exp:
        return 0.0
    # If expected_raw contains a list, check if any expected value appears in prediction.
    if isinstance(expected_raw, list):
        preds_lower = prediction.lower()
        for item in expected_raw:
            s = str(item).strip().lower()
            if s and s in preds_lower:
                return 1.0
        return 0.0
    return 1.0 if exp.lower() in prediction.lower() else 0.0


@register("f1_token")
def f1_token(prediction: str, expected: str | None, *, expected_raw: dict | list | None = None, **kwargs) -> float:
    """Token-level F1 metric that handles both CJK and Latin scripts.

    For texts containing CJK characters (Chinese/Japanese/Korean), uses *jieba*
    for word segmentation; otherwise falls back to whitespace splitting.
    """

    def _tokenize(text: str) -> list[str]:
        # Detect CJK presence — if any character falls in the CJK Unicode range,
        # use jieba for proper word segmentation.
        has_cjk = any("　" <= ch <= "鿿" for ch in text)
        if not has_cjk:
            return text.lower().split()
        try:
            import jieba
            return [t for t in jieba.lcut(text.lower()) if t.strip()]
        except ImportError:
            # Fallback: character-level n-grams when jieba is unavailable.
            # This is imperfect but still better than treating the whole string
            # as a single token.
            chars = [ch for ch in text.lower() if ch.strip()]
            bigrams = ["".join(chars[i:i+2]) for i in range(len(chars)-1)]
            return chars + bigrams

    pred_tokens = _tokenize(prediction)
    exp_tokens = _tokenize(expected or "")
    if not pred_tokens or not exp_tokens:
        return 0.0
    common = set(pred_tokens) & set(exp_tokens)
    if not common:
        return 0.0
    precision = len(common) / len(pred_tokens)
    recall = len(common) / len(exp_tokens)
    return 2 * precision * recall / (precision + recall)


@register("numeric_match")
def numeric_match(prediction: str, expected: str | None, *, expected_raw: dict | list | None = None, **kwargs) -> float:
    def _to_float(value: str | None) -> float | None:
        match = re.search(
            r"[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?",
            (value or "").strip(),
        )
        if match is None:
            return None
        cleaned = match.group(0).replace(",", "")
        try:
            return float(cleaned)
        except ValueError:
            return None

    a = _to_float(prediction)
    b = _to_float(expected)
    if a is None or b is None:
        return 0.0
    return 1.0 if abs(a - b) < 1e-6 else 0.0


@register("llm_judge")
async def llm_judge(
    prediction: str,
    expected: str | None,
    *,
    expected_raw: dict | list | None = None,
    judge_model: str | None = None,
    judge_provider: str | None = None,
    benchmark_type: str | None = None,
    **kwargs,
) -> float:
    """LLM-as-Judge metric.

    Uses another LLM to determine whether ``prediction`` semantically matches
    ``expected``. This handles cases where the model's answer is correct in
    meaning but differs in wording from the reference answer.

    Config keys passed via ``metric_config``:

      - ``judge_model``: model id to use for judging (e.g. "gpt-4o-mini").
        Defaults to the primary evaluation model if not set.
      - ``judge_provider``: provider name ("openrouter", "qiniu", "mock").
        Defaults to the primary evaluation provider if not set.
      - ``benchmark_type``: used to select the prompt template.
        Defaults to "qa".

    Returns 0.0 conservatively on any failure (timeout, provider error,
    ambiguous response). The judge is called with temperature=0.0 and
    max_tokens=16 to keep cost and latency minimal.
    """
    from app.evaluation.judge_prompts import get_judge_prompt
    from app.providers.base import ChatMessage, CompletionRequest
    from app.providers.registry import get_provider

    if not expected or not expected.strip():
        return 0.0

    # Resolve judge model/provider. Fall back to primary model/provider if not set.
    model_id = judge_model or kwargs.get("model_id", "")
    provider_name = judge_provider or kwargs.get("provider", "mock")

    try:
        provider = get_provider(provider_name)
    except Exception:
        logger.warning("llm_judge: provider %r unavailable, skipping", provider_name)
        return 0.0

    prompt_text = get_judge_prompt(benchmark_type or "qa")
    # Truncate prediction to prevent prompt-too-long errors; judge only needs substance.
    pred_for_judge = (prediction or "")[:2000]
    messages = [
        ChatMessage(
            role="user",
            content=prompt_text.format(expected=expected, prediction=pred_for_judge),
        )
    ]

    try:
        completion = await asyncio.wait_for(
            provider.complete(
                CompletionRequest(
                    model_id=model_id,
                    messages=messages,
                    temperature=0.0,
                    max_tokens=16,
                )
            ),
            timeout=30,
        )
    except Exception as exc:
        logger.warning("llm_judge: judge call failed: %s", exc)
        return 0.0

    text = (completion.text or "").strip().upper()
    # Check negative signals first — "NO_MATCH" contains "MATCH", so order matters.
    if any(tok in text for tok in ("NO_MATCH", "NO", "INCORRECT", "FALSE")):
        return 0.0
    if any(tok in text for tok in ("MATCH", "YES", "CORRECT", "TRUE")):
        return 1.0
    # Ambiguous / malformed response: default to 0.0 (conservative).
    return 0.0
