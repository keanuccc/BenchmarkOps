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
import json
import logging
import math
import re
from collections import Counter
from collections.abc import Callable
from typing import ParamSpec

from app.core.exceptions import ValidationError

logger = logging.getLogger(__name__)

P = ParamSpec("P")
Metric = Callable[..., float]

_METRICS: dict[str, Metric] = {}


class MetricEvaluationError(Exception):
    """A scoring metric could not produce a trustworthy score."""

    def __init__(self, message: str, *, kind: str = "metric"):
        self.kind = kind
        super().__init__(message)



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
    return bool(
        _explicit_metric_suite(metric_config)
        or (spec or {}).get("metric_suite_explicit", False)
    )


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
    seen_names: set[str] = set()
    for item in suite:
        if not isinstance(item, dict):
            raise ValidationError("metric_suite entries must be objects")
        name = item.get("name")
        if not isinstance(name, str) or not name:
            raise ValidationError("metric_suite entries require a metric name")
        if name in seen_names:
            raise ValidationError(f"metric_suite contains duplicate metric {name!r}")
        seen_names.add(name)
        try:
            weight = float(item.get("weight", 1.0))
        except (TypeError, ValueError) as exc:
            raise ValidationError(f"Invalid weight for metric {name!r}") from exc
        if not math.isfinite(weight):
            raise ValidationError(f"Weight for metric {name!r} must be finite")
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
        result = await metric_fn(*args, **kwargs)
    else:
        result = metric_fn(*args, **kwargs)
    if asyncio.isfuture(result) or isinstance(result, asyncio.Future):
        result = await result
    try:
        score = float(result)
    except (TypeError, ValueError) as exc:
        raise MetricEvaluationError("Metric returned a non-numeric score") from exc
    if not math.isfinite(score) or not 0.0 <= score <= 1.0:
        raise MetricEvaluationError("Metric score must be finite and within [0, 1]")
    return score


# Default metric per benchmark type (consumed by the Benchmark service).
DEFAULT_METRIC_FOR_TYPE: dict[str, str] = {
    "qa": "exact_match_ci",
    "classification": "exact_match_ci",
    "coding": "contains",
    "generation": "f1_token",
    "agent": "contains",
}


_UNIT_SUFFIX_RE = re.compile(
    r"(?<=\d)(?:平方千米|平方公里|平方米|平方厘米|平方毫米|"
    r"立方米|立方分米|立方厘米|立方毫米|公顷|千米|公里|米|厘米|毫米|"
    r"毫升|升|千克|克|吨|秒|分钟|小时|天|年|万元|亿元|个|只|头|条|张|本|辆|架|"
    r"倍|分|度|℃|°C|°F|kg|g|mg|ml|L|m|cm|mm|km|元|块|美元|人民币)$",
    flags=re.IGNORECASE,
)


def _normalize_match_text(
    value: object,
    *,
    answer_policy: dict | None = None,
    remove_whitespace: bool = True,
) -> str:
    text = "" if value is None else str(value).strip()
    policy = answer_policy or {}
    if policy.get("strip_units", True):
        compact = re.sub(r"\s+", "", text)
        stripped = _UNIT_SUFFIX_RE.sub("", compact)
        if stripped != compact:
            text = stripped
    if len(text) >= 2 and ((text[0], text[-1]) in (("(", ")"), ("（", "）"))):
        text = text[1:-1].strip()
    text = text.rstrip("。,.!?！，、；：")
    if remove_whitespace:
        text = re.sub(r"\s+", "", text)
    else:
        text = re.sub(r"\s+", " ", text)
    return text.casefold()


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


def _policy_values(answer_policy: dict | None) -> list[str]:
    policy = answer_policy or {}
    values: list[str] = []
    for key in ("aliases", "accepted_answers", "valid_answers"):
        raw = policy.get(key, [])
        values.extend(_flatten_strings(raw))
    return values


def _raw_answer_candidates(
    expected: str | None,
    expected_raw: dict | list | None,
    answer_policy: dict | None = None,
) -> list[str]:
    values = [expected or ""]
    if isinstance(expected_raw, list):
        values.extend(_flatten_strings(expected_raw))
    elif isinstance(expected_raw, dict):
        values.extend(_flatten_strings(expected_raw))
        values.extend(_flatten_strings(expected_raw.get("aliases", [])))
    values.extend(_policy_values(answer_policy))
    return [value for value in values if value and str(value).strip()]


def _exact_ci_candidates(
    expected: str | None,
    expected_raw: dict | list | None,
    answer_policy: dict | None = None,
    *,
    remove_whitespace: bool = True,
) -> list[str]:
    values = _raw_answer_candidates(expected, expected_raw, answer_policy)
    return [
        _normalize_match_text(
            v,
            answer_policy=answer_policy,
            remove_whitespace=remove_whitespace,
        )
        for v in values
        if v and str(v).strip()
    ]


def _required_answer_values(expected: str | None, expected_raw: dict | list | None) -> list[str]:
    if isinstance(expected_raw, list):
        return _flatten_strings(expected_raw)
    if isinstance(expected_raw, dict) and "answer" in expected_raw:
        return _flatten_strings(expected_raw["answer"])
    return [expected or ""]


def _split_answer_values(value: str, *, answer_policy: dict | None = None) -> list[str]:
    if (answer_policy or {}).get("multi_answer") not in ("all", "set"):
        return [value]
    return [part.strip() for part in re.split(r"[,，、]\s*", value) if part.strip()]


@register("exact_match")
def exact_match(prediction: str, expected: str | None, *, expected_raw: dict | list | None = None, **kwargs) -> float:
    return 1.0 if expected is not None and expected.strip() and prediction == expected else 0.0


@register("exact_match_ci")
def exact_match_ci(prediction: str, expected: str | None, *, expected_raw: dict | list | None = None, **kwargs) -> float:
    answer_policy = kwargs.get("answer_policy")
    if not _normalize_match_text(expected, answer_policy=answer_policy):
        return 0.0
    pred_n = _normalize_match_text(prediction, answer_policy=answer_policy)
    candidates = _exact_ci_candidates(expected, expected_raw, answer_policy)
    if not candidates:
        return 0.0
    mode = (answer_policy or {}).get("multi_answer")
    if mode in ("all", "set"):
        required = {
            _normalize_match_text(v, answer_policy=answer_policy)
            for v in _required_answer_values(expected, expected_raw)
            if str(v).strip()
        }
        parts = {
            _normalize_match_text(v, answer_policy=answer_policy)
            for v in _split_answer_values(prediction, answer_policy=answer_policy)
        }
        if not required:
            return 0.0
        matched = len(required & parts)
        if (answer_policy or {}).get("partial_credit"):
            return matched / len(required)
        return 1.0 if (parts == required if mode == "set" else required <= parts) else 0.0
    if pred_n in candidates:
        return 1.0
    return 0.0


@register("contains")
def contains(prediction: str, expected: str | None, *, expected_raw: dict | list | None = None, **kwargs) -> float:
    answer_policy = kwargs.get("answer_policy")
    if not _normalize_match_text(expected, answer_policy=answer_policy):
        return 0.0
    prediction_text = _normalize_match_text(
        prediction,
        answer_policy=answer_policy,
        remove_whitespace=False,
    )
    mode = (answer_policy or {}).get("multi_answer")
    required = _required_answer_values(expected, expected_raw)
    candidates = (
        required
        if mode in ("all", "set") and len(required) > 1
        else _exact_ci_candidates(
            expected,
            expected_raw,
            answer_policy,
            remove_whitespace=False,
        )
    )

    def _matches(candidate: str) -> bool:
        candidate_text = _normalize_match_text(
            candidate,
            answer_policy=answer_policy,
            remove_whitespace=False,
        )
        if not candidate_text:
            return False
        if re.fullmatch(r"[a-z0-9]+(?:[ _-][a-z0-9]+)*", candidate_text):
            return bool(re.search(
                rf"(?<![a-z0-9]){re.escape(candidate_text)}(?![a-z0-9])",
                prediction_text,
                flags=re.IGNORECASE,
            ))
        if any("\u3400" <= char <= "\u9fff" for char in candidate_text):
            return bool(re.search(
                rf"(?<![\u3400-\u9fff]){re.escape(candidate_text)}(?![\u3400-\u9fff])",
                prediction_text,
            ))
        return candidate_text.casefold() in prediction_text.casefold()

    if mode in ("all", "set") and len(required) > 1:
        matched = sum(1 for value in required if _matches(value))
        if (answer_policy or {}).get("partial_credit"):
            return matched / len(required)
        return 1.0 if matched == len(required) else 0.0
    return 1.0 if any(_matches(candidate) for candidate in candidates) else 0.0


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
            return re.findall(r"[A-Za-z0-9]+(?:['’][A-Za-z0-9]+)?", text.casefold())
        try:
            import jieba
            return [
                t.casefold()
                for t in jieba.lcut(text)
                if t.strip() and any(ch.isalnum() for ch in t)
            ]
        except ImportError:
            # Fallback: character-level n-grams when jieba is unavailable.
            # This is imperfect but still better than treating the whole string
            # as a single token.
            chars = [ch for ch in text.lower() if ch.strip()]
            bigrams = ["".join(chars[i:i+2]) for i in range(len(chars)-1)]
            return chars + bigrams

    pred_tokens = _tokenize(prediction)
    if not pred_tokens:
        return 0.0
    best = 0.0
    candidates = _raw_answer_candidates(
        expected, expected_raw, kwargs.get("answer_policy")
    )
    if kwargs.get("answer_policy", {}).get("multi_answer") in ("all", "set"):
        required = _required_answer_values(expected, expected_raw)
        if len(required) > 1:
            candidates = [" ".join(required)]
    for candidate in candidates:
        exp_tokens = _tokenize(candidate)
        if not exp_tokens:
            continue
        common = sum((Counter(pred_tokens) & Counter(exp_tokens)).values())
        if not common:
            continue
        precision = common / len(pred_tokens)
        recall = common / len(exp_tokens)
        best = max(best, 2 * precision * recall / (precision + recall))
    return best


@register("numeric_match")
def numeric_match(prediction: str, expected: str | None, *, expected_raw: dict | list | None = None, **kwargs) -> float:
    def _to_floats(value: str | None) -> list[float]:
        matches = re.finditer(
            r"[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?:[eE][-+]?\d+)?",
            (value or "").strip(),
        )
        values: list[float] = []
        for match in matches:
            try:
                values.append(float(match.group(0).replace(",", "")))
            except ValueError:
                continue
        return values

    predicted = _to_floats(prediction)
    candidates = _raw_answer_candidates(expected, expected_raw, kwargs.get("answer_policy"))
    if not predicted or not candidates:
        return 0.0
    tolerance = float(kwargs.get("tolerance", 1e-6))
    if not math.isfinite(tolerance) or tolerance < 0:
        raise ValidationError("tolerance must be finite and non-negative")
    expected_values = list(
        dict.fromkeys(
            value for candidate in candidates for value in _to_floats(candidate)
        )
    )
    mode = (kwargs.get("answer_policy") or {}).get("multi_answer")
    if mode in ("all", "set") and len(expected_values) > 1:
        matched = sum(
            any(abs(actual - target) <= tolerance for actual in predicted)
            for target in expected_values
        )
        if (kwargs.get("answer_policy") or {}).get("partial_credit"):
            return matched / len(expected_values)
        return 1.0 if matched == len(expected_values) else 0.0
    return 1.0 if any(
        abs(actual - target) <= tolerance
        for actual in predicted
        for target in expected_values
    ) else 0.0


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
    from app.providers.base import ChatMessage, CompletionRequest, ProviderRateLimitedError
    from app.providers.registry import get_provider

    if not expected or not expected.strip():
        return 0.0

    raise_on_error = bool(kwargs.get("raise_on_error", False))

    # Resolve judge model/provider. Fall back to primary model/provider if not set.
    model_id = judge_model or kwargs.get("model_id", "")
    provider_name = judge_provider or kwargs.get("provider", "mock")
    cache_enabled = bool(judge_model or judge_provider or kwargs.get("model_id") or kwargs.get("provider"))

    try:
        provider = get_provider(provider_name)
    except Exception as exc:
        logger.warning("llm_judge: provider %r unavailable, skipping", provider_name)
        if raise_on_error:
            raise MetricEvaluationError(
                f"llm judge provider unavailable: {exc}", kind="provider"
            ) from exc
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

    cache_key = _llm_judge_cache_key(
        prediction,
        expected,
        model_id=model_id,
        provider=provider_name,
        benchmark_type=benchmark_type,
    )
    if cache_enabled and cache_key in _llm_judge_cache:
        return _llm_judge_cache[cache_key]

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
    except ProviderRateLimitedError:
        raise
    except Exception as exc:
        logger.warning("llm_judge: judge call failed: %s", exc)
        if raise_on_error:
            raise MetricEvaluationError(
                f"llm judge provider call failed: {exc}", kind="provider"
            ) from exc
        return 0.0

    text = (completion.text or "").strip().upper()
    # The prompt requires one token. Substring matching would accept values such
    # as UNTRUE and can turn malformed judge output into a false positive.
    if text in {"NO_MATCH", "NO", "INCORRECT", "FALSE"}:
        score = 0.0
    elif text in {"MATCH", "YES", "CORRECT", "TRUE"}:
        score = 1.0
    else:
        if raise_on_error:
            raise MetricEvaluationError(
                f"llm judge returned an invalid response: {text!r}",
                kind="metric",
            )
        score = 0.0

    # Cache the result for identical prediction+expected pairs.
    if cache_enabled:
        _llm_judge_cache[cache_key] = score
        if len(_llm_judge_cache) > _MAX_CACHE_SIZE:
            _llm_judge_cache.pop(next(iter(_llm_judge_cache)))
    return score


# --- LLM Judge Cache ----------------------------------------------------------
# Simple in-process LRU cache for llm_judge results. Same (prediction, expected)
# pair always returns the same score without re-calling the provider.

_llm_judge_cache: dict[str, float] = {}
_MAX_CACHE_SIZE = 4096


def _llm_judge_cache_key(
    prediction: str,
    expected: str,
    *,
    model_id: str = "",
    provider: str = "",
    benchmark_type: str | None = None,
) -> str:
    """Deterministic cache key from prediction+expected strings."""
    import hashlib
    raw = "|||".join(
        (
            prediction.strip(),
            expected.strip(),
            model_id,
            provider,
            benchmark_type or "qa",
        )
    )
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


# --- Rubric (Dimension-Based) Judge Metric -----------------------------------


def _normalize_rubric_dimensions(
    raw: object, benchmark_type: str | None = None
) -> list[dict]:
    """Validate and normalize rubric dimension config.

    Accepts a list of ``{"name", "description"?, "weight"?}`` objects; when
    ``raw`` is empty/None, falls back to the default dimensions for the
    benchmark type (``qa`` if unknown). Each entry gets a JSON-safe ``key``.
    """
    from app.evaluation.judge_prompts import RUBRIC_DEFAULT_DIMENSIONS

    if isinstance(raw, list) and raw:
        source = raw
    else:
        source = RUBRIC_DEFAULT_DIMENSIONS.get(
            benchmark_type or "qa", RUBRIC_DEFAULT_DIMENSIONS["qa"]
        )

    normalized: list[dict] = []
    seen_keys: set[str] = set()
    for item in source:
        if not isinstance(item, dict):
            raise ValidationError("rubric dimensions must be objects")
        name = item.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ValidationError("rubric dimension requires a non-empty name")
        key = re.sub(r"[^0-9a-z_]+", "_", name.strip().lower()).strip("_")
        if not key:
            raise ValidationError(f"rubric dimension name {name!r} has no usable key")
        if key in seen_keys:
            raise ValidationError(f"rubric dimension key {key!r} is duplicated")
        seen_keys.add(key)
        try:
            weight = float(item.get("weight", 1.0))
        except (TypeError, ValueError) as exc:
            raise ValidationError(f"invalid weight for rubric dimension {name!r}") from exc
        if not math.isfinite(weight) or weight < 0:
            raise ValidationError(f"invalid weight for rubric dimension {name!r}")
        description = item.get("description")
        normalized.append(
            {
                "key": key,
                "name": name.strip(),
                "description": "" if description is None else str(description),
                "weight": weight,
            }
        )
    if not normalized or sum(entry["weight"] for entry in normalized) <= 0:
        raise ValidationError("rubric dimensions require a positive total weight")
    return normalized


def _parse_rubric_scores(
    text: str, keys: list[str], scale: int
) -> dict[str, float] | None:
    """Parse judge JSON/line output into per-dimension scores in [0, 1].

    Accepts ``{"scores": {...}}``, a flat ``{key: n}`` object, or
    ``key: n`` lines. Missing/unparseable dimensions score 0.0; returns None
    when no dimension could be parsed at all.
    """
    if not text:
        return None
    cleaned = re.sub(r"```(?:json)?", "", text, flags=re.IGNORECASE).strip()
    scores: dict = {}
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end > start:
        try:
            data = json.loads(cleaned[start : end + 1])
            if isinstance(data, dict):
                inner = data.get("scores")
                scores = inner if isinstance(inner, dict) else data
        except json.JSONDecodeError:
            scores = {}

    out: dict[str, float] = {}
    parsed_any = False
    for key in keys:
        value = scores.get(key) if isinstance(scores, dict) else None
        if value is None:
            match = re.search(rf"{re.escape(key)}\s*[:：=]\s*(\d+(?:\.\d+)?)", text)
            if match:
                value = match.group(1)
        if value is None:
            out[key] = 0.0
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            out[key] = 0.0
            continue
        if not math.isfinite(number):
            out[key] = 0.0
            continue
        parsed_any = True
        out[key] = max(0.0, min(1.0, number / float(scale)))
    return out if parsed_any else None


def _llm_judge_rubric_cache_key(
    prediction: str,
    expected: str,
    *,
    model_id: str = "",
    provider: str = "",
    benchmark_type: str | None = None,
    config_sig: str = "",
) -> str:
    """Deterministic cache key including the rubric config signature."""
    import hashlib

    raw = "|||".join(
        (
            prediction.strip(),
            expected.strip(),
            model_id,
            provider,
            benchmark_type or "qa",
            config_sig,
        )
    )
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


@register("llm_judge_rubric")
async def llm_judge_rubric(
    prediction: str,
    expected: str | None,
    *,
    expected_raw: dict | list | None = None,
    judge_model: str | None = None,
    judge_provider: str | None = None,
    benchmark_type: str | None = None,
    **kwargs,
) -> float:
    """Dimension-based LLM-as-Judge metric (rubric scoring).

    Instead of a binary MATCH/NO_MATCH, the judge scores the prediction on
    several dimensions (e.g. correctness, completeness, coherence) and the
    result is a weighted average normalized to [0, 1].

    Config keys passed via ``metric_config``:

      - ``dimensions``: list of ``{"name", "description"?, "weight"?}``.
        Defaults to the benchmark type's built-in dimensions.
      - ``scale``: integer >= 2 (default 5). Judge scores each dimension
        from 1 to ``scale``.
      - ``rationale``: bool (default False). Ask the judge for a one-sentence
        rationale alongside the scores.
      - ``judge_model`` / ``judge_provider``: defaults to the primary
        evaluation model/provider like ``llm_judge``.

    Returns 0.0 conservatively on any failure (invalid config, provider error,
    unparseable response). Missing dimensions in the response score 0.0.
    """
    from app.evaluation.judge_prompts import build_rubric_judge_prompt
    from app.providers.base import ChatMessage, CompletionRequest, ProviderRateLimitedError
    from app.providers.registry import get_provider

    if not expected or not expected.strip():
        return 0.0

    raise_on_error = bool(kwargs.get("raise_on_error", False))
    try:
        dimensions = _normalize_rubric_dimensions(
            kwargs.get("dimensions"), benchmark_type
        )
        scale = int(kwargs.get("scale", 5))
        if scale < 2:
            raise ValidationError("rubric scale must be >= 2")
        rationale = bool(kwargs.get("rationale", False))
    except (TypeError, ValueError, ValidationError) as exc:
        if raise_on_error:
            raise MetricEvaluationError(str(exc), kind="metric") from exc
        return 0.0

    model_id = judge_model or kwargs.get("model_id", "")
    provider_name = judge_provider or kwargs.get("provider", "mock")
    cache_enabled = bool(
        judge_model or judge_provider or model_id or provider_name
    )
    config_sig = json.dumps(
        {
            "dimensions": [
                {"key": d["key"], "weight": d["weight"]} for d in dimensions
            ],
            "scale": scale,
            "rationale": rationale,
        },
        sort_keys=True,
    )
    cache_key = _llm_judge_rubric_cache_key(
        prediction,
        expected,
        model_id=model_id,
        provider=provider_name,
        benchmark_type=benchmark_type,
        config_sig=config_sig,
    )
    if cache_enabled and cache_key in _llm_judge_cache:
        return _llm_judge_cache[cache_key]

    try:
        provider = get_provider(provider_name)
    except Exception as exc:
        logger.warning("llm_judge_rubric: provider %r unavailable, skipping", provider_name)
        if raise_on_error:
            raise MetricEvaluationError(
                f"llm judge rubric provider unavailable: {exc}", kind="provider"
            ) from exc
        return 0.0

    prompt_text = build_rubric_judge_prompt(
        (prediction or "")[:2000],
        expected,
        dimensions,
        scale=scale,
        rationale=rationale,
    )
    messages = [ChatMessage(role="user", content=prompt_text)]
    try:
        completion = await asyncio.wait_for(
            provider.complete(
                CompletionRequest(
                    model_id=model_id,
                    messages=messages,
                    temperature=0.0,
                    max_tokens=256,
                )
            ),
            timeout=60,
        )
    except ProviderRateLimitedError:
        raise
    except Exception as exc:
        logger.warning("llm_judge_rubric: judge call failed: %s", exc)
        if raise_on_error:
            raise MetricEvaluationError(
                f"llm judge rubric provider call failed: {exc}", kind="provider"
            ) from exc
        return 0.0

    parsed = _parse_rubric_scores(
        completion.text or "", [d["key"] for d in dimensions], scale
    )
    if parsed is None:
        if raise_on_error:
            raise MetricEvaluationError(
                "llm judge rubric returned an invalid response", kind="metric"
            )
        return 0.0
    total_weight = sum(d["weight"] for d in dimensions)
    score = (
        sum(parsed.get(d["key"], 0.0) * d["weight"] for d in dimensions)
        / total_weight
    )
    score = max(0.0, min(1.0, score))

    if cache_enabled:
        _llm_judge_cache[cache_key] = score
        if len(_llm_judge_cache) > _MAX_CACHE_SIZE:
            _llm_judge_cache.pop(next(iter(_llm_judge_cache)))
    return score


# --- Fuzzy Match Metric -------------------------------------------------------

def _levenshtein_distance(s1: str, s2: str) -> int:
    """Compute Levenshtein distance between two strings."""
    if len(s1) < len(s2):
        return _levenshtein_distance(s2, s1)
    if len(s2) == 0:
        return len(s1)

    prev_row = list(range(len(s2) + 1))
    for i, c1 in enumerate(s1):
        curr_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = prev_row[j + 1] + 1
            deletions = curr_row[j] + 1
            substitutions = prev_row[j] + (c1 != c2)
            curr_row.append(min(insertions, deletions, substitutions))
        prev_row = curr_row

    return prev_row[-1]


@register("fuzzy_match")
def fuzzy_match(
    prediction: str,
    expected: str | None,
    *,
    expected_raw: dict | list | None = None,
    threshold: float = 0.8,
    **kwargs,
) -> float:
    """Fuzzy string match using normalized Levenshtein distance.

    Returns 1.0 when the prediction is within ``threshold`` similarity of the
    expected answer, 0.0 otherwise. The threshold defaults to 0.8 (80% similarity).

    Config key ``threshold`` can be passed via metric_config.

    Handles CJK by normalizing whitespace and case before comparison.
    """
    if not 0.0 <= threshold <= 1.0 or not math.isfinite(threshold):
        raise ValidationError("threshold must be finite and between 0 and 1")

    pred = prediction.strip()
    if not pred:
        return 0.0

    # Normalize: remove whitespace, lowercase
    pred_n = re.sub(r"\s+", "", pred).lower()
    candidates = _exact_ci_candidates(expected, expected_raw, kwargs.get("answer_policy"))
    return 1.0 if any(
        1.0 - (
            _levenshtein_distance(pred_n, re.sub(r"\s+", "", candidate).lower())
            / max(len(pred_n), len(re.sub(r"\s+", "", candidate).lower()))
        ) >= threshold
        for candidate in candidates
        if candidate and max(len(pred_n), len(re.sub(r"\s+", "", candidate).lower()))
    ) else 0.0


@register("fuzzy_match_ci")
def fuzzy_match_ci(
    prediction: str,
    expected: str | None,
    *,
    expected_raw: dict | list | None = None,
    threshold: float = 0.8,
    **kwargs,
) -> float:
    """Case-insensitive fuzzy match with multiple candidate answers.

    Like exact_match_ci but uses fuzzy matching instead of exact equality.
    Checks all candidates from expected_raw (aliases, lists, etc.).
    Returns 1.0 if ANY candidate matches within the threshold.
    """
    if not 0.0 <= threshold <= 1.0 or not math.isfinite(threshold):
        raise ValidationError("threshold must be finite and between 0 and 1")

    pred = prediction.strip()
    if not pred:
        return 0.0

    # Normalize
    pred_n = re.sub(r"\s+", "", pred).lower()

    candidates = _exact_ci_candidates(
        expected,
        expected_raw,
        kwargs.get("answer_policy"),
    )
    if not candidates:
        return 0.0

    best_score = 0.0
    for cand in candidates:
        cand_n = re.sub(r"\s+", "", cand).lower()
        if not cand_n:
            continue
        max_len = max(len(pred_n), len(cand_n))
        if max_len == 0:
            continue
        dist = _levenshtein_distance(pred_n, cand_n)
        similarity = 1.0 - (dist / max_len)
        if similarity > best_score:
            best_score = similarity

    return 1.0 if best_score >= threshold else 0.0
