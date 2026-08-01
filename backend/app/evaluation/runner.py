"""Evaluation runner — orchestrates a single experiment run."""
from __future__ import annotations

import asyncio
import logging
import re
import time

from app.core.config import settings
from app.core.database import AsyncSessionLocal, with_retry_on_lock
from app.evaluation.metrics import (
    _call_metric,
    get_metric,
    has_metric_suite,
    MetricEvaluationError,
    normalize_metric_suite,
)
from app.models.benchmark import Benchmark
from app.models.dataset import Dataset
from app.models.experiment import ExperimentResult
from app.models.model import Model
from app.models.prompt import Prompt
from app.providers.base import ChatMessage, CompletionRequest, ProviderRateLimitedError
from app.providers.registry import get_provider
from app.repositories.dataset import DatasetRowRepository
from app.repositories.experiment import (
    ExperimentRepository,
    ExperimentResultRepository,
)
from app.evaluation.task_queue import _mark_experiment_cancelled

logger = logging.getLogger(__name__)

_BATCH_SIZE = 500
_PROGRESS_EVERY = 50

logger = logging.getLogger(__name__)

_ANSWER_PREFIX_RE = re.compile(
    r"^(?:最\s*终\s*答\s*案[：:\s]*|答\s*案(?:\s*是)?[：:\s]*|回\s*答[：:\s]*|答\s*题?[：:\s]*|answer[s]?[：:]?\s*|final\s+answer\s*[：:]?\s*|结\s*论[：:\s]*)",
    flags=re.IGNORECASE,
)


def _first_value(d: dict | None) -> str:
    """Extract the answer string from an expected-row dict.

    Datasets may store the answer under different key names (``answer``, ``label``,
    ``output``, ``target``, ``ground_truth``). We check those explicitly before
    falling back to ``next(iter(...))``.

    Handles common shapes:

    * ``{"answer": "北京"}`` → ``"北京"``
    * ``{"answer": ["北京", "北京市"]}`` → ``"北京"`` (first valid element)
    * ``{"answer": {"text": "北京", "confidence": 0.9}}`` → ``"北京"``
    * ``{"answer": 42}`` → ``"42"``
    * ``{"result": "北京"}`` → ``"北京"`` (fallback to first value)
    * ``None`` / empty → ``""``
    """
    if not d:
        return ""

    def _flatten(value: object) -> str:
        """Recursively extract a string from nested dicts/lists."""
        if value is None:
            return ""
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, (int, float, bool)):
            return str(value)
        if isinstance(value, list):
            for item in value:
                s = _flatten(item)
                if s:
                    return s
            return ""
        if isinstance(value, dict):
            # Prefer known answer keys, then first non-empty value.
            for key in ("answer", "label", "output", "target", "ground_truth", "value", "text"):
                if key in value:
                    s = _flatten(value[key])
                    if s:
                        return s
            for v in value.values():
                s = _flatten(v)
                if s:
                    return s
            return ""
        return str(value).strip()

    # First pass: look for known answer keys at the top level.
    for key in ("answer", "label", "output", "target", "ground_truth", "value", "text"):
        if key in d:
            result = _flatten(d[key])
            if result:
                return result

    # Fallback: flatten the first value.
    val = next(iter(d.values()), "")
    result = _flatten(val)
    return "" if not result else result


def _extract_answer(
    text: str,
    *,
    split_commas: bool = True,
    normalize_whitespace: bool = True,
    strip_units: bool = True,
) -> str:
    """Strip the model's formatting noise so the metric compares against the
    bare answer.

    Handles the common patterns produced by the current prompt template:

    * ``答案：亚洲`` / ``答案: 亚洲`` / ``答案: 亚洲`` / ``Answer: Asia``
    * ``最终答案：xxx`` / ``结论：xxx``
    * Multi-line CoT output — takes the last non-empty line and strips the
      prefix from it.
    * Trailing units / parentheticals that pollute exact-match scoring
      (e.g. ``31元``, ``40平方厘米``, ``碳（C）``).
    * Whitespace inside the answer (e.g. ``18 世纪`` -> ``18世纪``).
    * Comma-separated multi-answer lines (e.g. ``答案：40平方厘米，13厘米``):
      extracts the first numeric or short token before the comma, since the
      expected value usually targets a single answer.
    """
    if not text:
        return ""

    # Split into lines; take the last non-empty line.
    lines = [line.strip() for line in text.strip().splitlines() if line.strip()]
    if not lines:
        return ""
    last = next((line for line in reversed(lines) if _ANSWER_PREFIX_RE.match(line)), lines[-1])

    # Strip common answer-prefixes (case-insensitive, handles Chinese/English
    # colons including full-width ： and ：).
    last = _ANSWER_PREFIX_RE.sub("", last)

    # Remove surrounding quotes that some models add.
    last = last.strip().strip('"').strip("'").strip()

    # Drop a trailing parenthetical annotation (e.g. "碳（C）" -> "碳"),
    # but keep a parenthesized answer such as "(A)".
    if not re.fullmatch(r"[（(][^）)]*[）)]", last):
        last = re.sub(r"\s*[（(][^）)]*[）)]\s*$", "", last)
    if len(last) >= 2 and ((last[0], last[-1]) in (("(", ")"), ("（", "）"))):
        last = last[1:-1].strip()

    # If the answer contains a Chinese comma suggesting multiple values were
    # given, take only the first segment. This handles cases like
    # "40平方厘米，13厘米" -> "40平方厘米" where the expected answer is just
    # the first value "40".
    if split_commas:
        if "，" in last:
            last = last.split("，", 1)[0].strip()
        elif "," in last and not re.fullmatch(r"[-+]?\d{1,3}(?:,\d{3})+(?:\.\d+)?", last):
            last = last.split(",", 1)[0].strip()

    # Strip leading labels like "面积=" / "半周长=" / "体积=" etc.
    last = re.sub(r"^(?:面积|周长|半周长|体积|质量|速度|时间|长度|宽度|高度)[=：:\s]*", "", last)

    # Drop trailing Chinese currency / measurement units that the model often appends.
    # Order matters: match compound units (e.g. 平方千米, 立方米) before atomic units
    # (米, 厘米) to avoid partial stripping like "100立方" from "100立方厘米".
    if strip_units:
        last = re.sub(r"(?:元|块|美元|人民币|元/|$/)?$", "", last)
        last = re.sub(
            r"(?<=\d)\s*(?:平方千米|平方公里|平方米|平方厘米|平方毫米|"
            r"立方米|立方分米|立方厘米|立方毫米|"
            r"公顷|千米|公里|米|厘米|毫米|"
            r"毫升|升|千克|克|吨|秒|分钟|小时|天|年|万元|亿元|个|只|头|条|张|本|辆|架|"
            r"倍|分|度|℃|°C|°F|kg|g|mg|ml|L|m|cm|mm|km)$",
            "",
            last,
        )

    # Strip trailing punctuation that snuck into the answer.
    last = last.rstrip("。,.!?！，、；：")

    # Normalize whitespace inside the answer so "18 世纪" matches "18世纪".
    last = re.sub(r"\s+", "" if normalize_whitespace else " ", last).strip()

    return last


def _score_reason(
    metric_name: str,
    score: float,
    cleaned_prediction: str,
    expected_canonical: str,
    metric_scores: dict[str, float] | None = None,
) -> str:
    outcome = "matched" if score >= 1.0 else "did not match"
    if metric_scores:
        components = ", ".join(
            f"{name}={value:.4f}" for name, value in metric_scores.items()
        )
        detail = f"weighted metric components: {components}"
    elif metric_name in ("contains", "agent"):
        detail = "expected substring matched as a standalone text span"
    elif metric_name == "numeric_match":
        detail = "first numeric values matched within tolerance"
    elif metric_name in ("fuzzy_match", "fuzzy_match_ci"):
        detail = "normalized Levenshtein similarity met the configured threshold"
    elif metric_name == "llm_judge":
        detail = "LLM judge classified the prediction as semantically equivalent"
    elif cleaned_prediction == expected_canonical:
        detail = "cleaned prediction equals expected canonical answer"
    else:
        detail = (
            f"cleaned prediction {cleaned_prediction!r} vs expected "
            f"{expected_canonical!r}"
        )
    return f"{metric_name}: {outcome}; {detail}"


def _render_prompt(template: str, variables: list[str], row_input: dict) -> str:
    ctx = {k: ("" if v is None else v) for k, v in row_input.items()}
    for var in variables:
        ctx.setdefault(var, "")
    try:
        return template.format(**ctx)
    except (KeyError, IndexError):
        joined = "\n".join(f"{k}: {v}" for k, v in row_input.items())
        return f"{template}\n\n{joined}"


def _cost(pricing: dict, prompt_tokens: int, completion_tokens: int) -> float:
    """Compute cost from per-1k pricing. Returns 0.0 when no pricing info is available."""
    try:
        if not pricing:
            return 0.0
        inp = float(pricing.get("input_per_1k", 0.0)) * (prompt_tokens / 1000.0)
        out = float(pricing.get("output_per_1k", 0.0)) * (completion_tokens / 1000.0)
        return round(inp + out, 6)
    except Exception:
        return 0.0


async def _mark_failed(experiment_id: str, error: str) -> None:
    """Write a terminal 'failed' status on an isolated short session.

    Must never be called on a session that is holding a transaction across a
    network await — this is its own connection so it doesn't contend with a
    long-running run. The write is retried on transient 'database is locked'
    contention; if it still fails after exhausting retries, the error is logged.
    """

    async def _write_failed() -> None:
        async with AsyncSessionLocal() as session:
            repo = ExperimentRepository(session)
            exp = await repo.get(experiment_id)
            if exp is not None:
                await repo.update(exp, {"status": "failed", "error": error[:500]})
                await session.commit()

    try:
        await with_retry_on_lock(_write_failed)
    except Exception:  # noqa: BLE001
        logger.exception("failed to persist terminal 'failed' status")


async def _persist_progress(
    experiment_id: str,
    processed: int,
    rows_total: int,
    *,
    cells_done: int = 0,
    cells_error: int = 0,
    metrics_update: dict | None = None,
) -> None:
    """Best-effort progress update on an isolated short session.

    The write is retried on transient 'database is locked' contention; since
    progress is best-effort, a final failure (retries exhausted) is only logged,
    never raised — matching the original no-throw semantics.
    """

    async def _write_progress() -> None:
        async with AsyncSessionLocal() as session:
            repo = ExperimentRepository(session)
            exp = await repo.get(experiment_id)
            if exp is not None and exp.status == "running":
                update = {
                    "progress": processed,
                    "rows_total": rows_total,
                    "cells_done": cells_done,
                    "cells_error": cells_error,
                }
                if metrics_update:
                    current_metrics = dict(exp.metrics or {})
                    current_metrics.update(metrics_update)
                    update["metrics"] = current_metrics
                await repo.update(
                    exp,
                    update,
                )
                await session.commit()

    try:
        await with_retry_on_lock(_write_progress)
    except Exception:  # noqa: BLE001
        logger.debug("progress update skipped (lock or missing experiment)")


async def run_experiment(experiment_id: str) -> None:
    logger.info("experiment %s run started", experiment_id)

    async with AsyncSessionLocal() as load_session:
        exp_repo = ExperimentRepository(load_session)
        experiment = await exp_repo.get(experiment_id)
        if experiment is None:
            return

        if not await exp_repo.set_running_if_not_running(experiment_id):
            return
        await load_session.commit()

        snap = experiment.prompt_snapshot
        if snap:
            template = snap.get("template", "")
            variables = snap.get("variables", []) or []
            prompt_version = snap.get("version")
        else:
            prompt = await load_session.get(Prompt, experiment.prompt_id)
            if prompt is None:
                return await _mark_failed(experiment_id, "Experiment references a missing prompt")
            template = prompt.template
            variables = prompt.variables
            prompt_version = getattr(prompt, "version", None)

        bsnap = experiment.benchmark_snapshot
        if bsnap:
            metric_name = bsnap.get("metric")
            metric_config = bsnap.get("metric_config", {}) or {}
            benchmark_spec = bsnap.get("spec", {}) or {}
            benchmark_type = bsnap.get("type")
        else:
            benchmark = await load_session.get(Benchmark, experiment.benchmark_id)
            if benchmark is None:
                return await _mark_failed(experiment_id, "Experiment references a missing benchmark")
            metric_name = benchmark.metric
            metric_config = benchmark.metric_config
            benchmark_spec = {}
            benchmark_type = benchmark.type

        dsnap = experiment.dataset_snapshot
        if dsnap:
            answer_policy = dsnap.get("answer_policy", {}) or {}
        else:
            dataset = await load_session.get(Dataset, experiment.dataset_id)
            contract = dataset.contract if dataset is not None else {}
            answer_policy = (contract or {}).get("answer_policy", {}) or {}

        msnap = experiment.model_snapshot
        if msnap:
            model_ref = msnap.get("model_id")
            pricing = msnap.get("pricing", {}) or {}
            # Routing: honor the model's pinned provider if present in the snapshot,
            # else fall back to the configured default provider.
            model_provider = msnap.get("provider") or settings.default_provider
            model_is_free = bool(msnap.get("is_free", False))
        else:
            model = await load_session.get(Model, experiment.model_id)
            if model is None:
                return await _mark_failed(experiment_id, "Experiment references a missing model")
            model_ref = model.model_id
            pricing = model.pricing
            model_provider = model.provider or settings.default_provider
            # Model table has no is_free column; derive from the ":free" suffix
            # convention and, for Qiniu, the configured free-model set.
            model_is_free = (
                model.model_id.endswith(":free")
                or (model.provider == "qiniu" and model.model_id in settings.qiniu_free_set)
            )

        if not metric_name:
            return await _mark_failed(experiment_id, "Experiment has no scoring metric")

        row_repo = DatasetRowRepository(load_session)
        rows: list = []
        offset = 0
        while True:
            batch = await row_repo.list_by_dataset(
                experiment.dataset_id, offset=offset, limit=_BATCH_SIZE
            )
            if not batch:
                break
            rows.extend(batch)
            offset += len(batch)

        metric_suite = normalize_metric_suite(metric_name, metric_config, benchmark_spec)
        explicit_metric_suite = has_metric_suite(metric_config, benchmark_spec)
        metric_fns = {item["name"]: get_metric(item["name"]) for item in metric_suite}
        total_weight = sum(item["weight"] for item in metric_suite) or 1.0
        # Route by the model's pinned provider (falling back to the configured default).
        # The registry raises if the named gateway has no key configured.
        provider = get_provider(model_provider)
        params = experiment.params or {}
        temperature = float(params.get("temperature", 0.0))
        max_tokens = params.get("max_tokens")

    result_objs: list[ExperimentResult] = []
    total_score = 0.0
    total_cost = 0.0
    total_tokens = 0
    total_latency = 0
    scored = 0
    provider_errors = 0
    metric_errors = 0
    processed = 0
    cells_done = 0   # rows scored successfully (drives the progress bar's "scored" count)
    cells_error = 0   # rows whose provider call failed
    rate_limited = False
    rate_limited_msg = ""
    started = time.perf_counter()

    async def _process_row(row):
        """Run one dataset row: render prompt, call the provider, score, build the
        result object. Returns (ExperimentResult, is_rate_limited). Pure per-row work;
        callers merge the returned object into shared accumulators after gather so the
        concurrent phase never touches shared state across an await point."""
        rendered = _render_prompt(template, variables, row.input)
        req = CompletionRequest(
            model_id=model_ref,
            messages=[ChatMessage(role="user", content=rendered)],
            temperature=temperature,
            max_tokens=max_tokens,
            is_free=model_is_free,
        )
        expected_str = _first_value(row.expected)
        try:
            completion = await asyncio.wait_for(
                provider.complete(req),
                timeout=settings.eval_request_timeout,
            )
            # Clean both sides before scoring: expected may come from a dict key,
            # prediction may carry prompt-enforced prefixes like 「答案：」.
            cleaned_expected = expected_str.strip()
            multi_answer = answer_policy.get("multi_answer")
            cleaned_prediction = _extract_answer(
                completion.text,
                split_commas=multi_answer not in ("all", "set"),
                normalize_whitespace=False,
                strip_units=answer_policy.get("strip_units", True),
            ).strip()

            metric_scores: dict[str, float] = {}
            weighted_score = 0.0
            for item in metric_suite:
                kwargs = dict(item["config"])
                kwargs.setdefault("benchmark_type", benchmark_type)
                kwargs.setdefault("model_id", model_ref)
                kwargs.setdefault("provider", model_provider)
                kwargs.setdefault("answer_policy", answer_policy)
                kwargs["raise_on_error"] = True
                try:
                    metric_score = float(
                        await _call_metric(
                            metric_fns[item["name"]],
                            cleaned_prediction,
                            cleaned_expected,
                            expected_raw=row.expected,
                            **kwargs,
                        )
                    )
                except MetricEvaluationError:
                    raise
                except Exception as exc:
                    raise MetricEvaluationError(
                        f"metric {item['name']!r} failed: {exc}", kind="metric"
                    ) from exc
                metric_scores[item["name"]] = metric_score
                weighted_score += metric_score * item["weight"]
            score = weighted_score / total_weight
            score_reason = _score_reason(
                metric_name,
                score,
                cleaned_prediction,
                cleaned_expected,
                metric_scores,
            )

            cost = _cost(pricing or {}, completion.prompt_tokens, completion.completion_tokens)
            res = ExperimentResult(
                experiment_id=experiment_id,
                row_idx=row.idx,
                input=row.input,
                expected=row.expected,
                output=completion.text,
                score=score,
                cleaned_prediction=cleaned_prediction,
                expected_canonical=cleaned_expected,
                score_reason=score_reason,
                latency_ms=completion.latency_ms,
                tokens=completion.total_tokens,
                cost=cost,
            )
            return res, False, metric_scores, None
        except ProviderRateLimitedError as exc:
            res = ExperimentResult(
                experiment_id=experiment_id,
                row_idx=row.idx,
                input=row.input,
                expected=row.expected,
                output="",
                score=0.0,
                error=str(exc)[:500],
            )
            return res, True, {}, "provider"
        except MetricEvaluationError as exc:
            res = ExperimentResult(
                experiment_id=experiment_id,
                row_idx=row.idx,
                input=row.input,
                expected=row.expected,
                output=completion.text,
                score=0.0,
                error=f"metric_error[{exc.kind}]: {exc}"[:500],
            )
            return res, False, {}, exc.kind
        except Exception as exc:
            res = ExperimentResult(
                experiment_id=experiment_id,
                row_idx=row.idx,
                input=row.input,
                expected=row.expected,
                output="",
                score=0.0,
                error=str(exc)[:500],
            )
            return res, False, {}, "provider"

    metric_totals: dict[str, float] = {item["name"]: 0.0 for item in metric_suite}

    def _merge(res, is_rate_limited, metric_scores, error_kind):
        """Fold one processed row into the shared accumulators. Called after gather, so
        no two merges run concurrently — safe without extra locking."""
        nonlocal scored, cells_done, cells_error, provider_errors, metric_errors, total_score, total_cost
        nonlocal total_tokens, total_latency, rate_limited, rate_limited_msg
        result_objs.append(res)
        if is_rate_limited:
            provider_errors += 1
            cells_error += 1
            rate_limited = True
            rate_limited_msg = (res.error or "")[:500]
        else:
            # A successful completion vs a non-429 failure is distinguished by score/error.
            if res.error:
                if error_kind == "metric":
                    metric_errors += 1
                else:
                    provider_errors += 1
                cells_error += 1
            else:
                total_score += res.score or 0.0
                total_cost += res.cost or 0.0
                total_tokens += res.tokens or 0
                total_latency += res.latency_ms or 0
                for name, metric_score in metric_scores.items():
                    metric_totals[name] = metric_totals.get(name, 0.0) + metric_score
                scored += 1
                cells_done += 1

    def _progress_metrics() -> dict:
        """Live metrics for the running experiment (drives the UI's ETA)."""
        runtime_now = time.perf_counter() - started
        avg_ms = (runtime_now * 1000 / scored) if scored else None
        if avg_ms is None:
            return {}
        return {"avg_ms_per_row": round(avg_ms, 1)}

    is_free = model_is_free
    if is_free:
        # Free models measured RPM>=325 + high burst; run rows concurrently (bounded by
        # free_model_concurrency) and merge results serially. No fixed per-row sleep.
        # Applies to OpenRouter ":free" models and Qiniu free-tier models alike, since
        # the provider layer throttles them via its own token bucket.
        sem = asyncio.Semaphore(settings.free_model_concurrency)

        async def _guarded(row):
            async with sem:
                return await _process_row(row)

        for i in range(0, len(rows), settings.free_model_concurrency):
            batch = rows[i : i + settings.free_model_concurrency]
            outcomes = await asyncio.gather(*(_guarded(r) for r in batch))
            for res, is_rl, metric_scores, error_kind in outcomes:
                _merge(res, is_rl, metric_scores, error_kind)
            processed += len(batch)
            # Report progress per batch (batch size == free_model_concurrency, well
            # under _PROGRESS_EVERY), so the UI bar advances without waiting
            # for a full _PROGRESS_EVERY worth of rows under concurrency.
            await _persist_progress(
                experiment_id,
                processed,
                len(rows),
                cells_done=cells_done,
                cells_error=cells_error,
                metrics_update=_progress_metrics(),
            )
            if rate_limited:
                break
            # Check for cancellation between batches
            try:
                async with AsyncSessionLocal() as check_session:
                    check_repo = ExperimentRepository(check_session)
                    current_exp = await check_repo.get(experiment_id)
                    if current_exp and current_exp.status == "cancelled":
                        logger.info("experiment %s cancelled by user at row %d", experiment_id, processed)
                        await _mark_experiment_cancelled(experiment_id)
                        return
            except Exception:  # noqa: BLE001
                pass  # best-effort only — don't fail the run if check fails
    else:
        # Non-free models: keep the original strict-serial behavior (rate safety is
        # handled by the task queue's eval_max_workers, not by in-run concurrency).
        for row in rows:
            res, is_rl, metric_scores, error_kind = await _process_row(row)
            _merge(res, is_rl, metric_scores, error_kind)
            processed += 1
            if processed % _PROGRESS_EVERY == 0:
                await _persist_progress(
                    experiment_id,
                    processed,
                    len(rows),
                    cells_done=cells_done,
                    cells_error=cells_error,
                    metrics_update=_progress_metrics(),
                )
            if rate_limited:
                break
            # Check for cancellation every row (cheap read-only DB query)
            try:
                async with AsyncSessionLocal() as check_session:
                    check_repo = ExperimentRepository(check_session)
                    current_exp = await check_repo.get(experiment_id)
                    if current_exp and current_exp.status == "cancelled":
                        logger.info("experiment %s cancelled by user at row %d", experiment_id, processed)
                        await _mark_experiment_cancelled(experiment_id)
                        return
            except Exception:  # noqa: BLE001
                pass

    n = len(result_objs)
    accuracy = (total_score / scored) if scored else 0.0
    avg_latency = (total_latency / scored) if scored else 0.0
    runtime_s = (time.perf_counter() - started) if scored > 0 else 0
    avg_ms_per_row = (runtime_s * 1000 / scored) if scored > 0 else 0
    status = "failed" if rate_limited else (
        "partial" if provider_errors + metric_errors > 0 else "completed"
    )
    metrics_by_name = {
        name: metric_total / scored
        for name, metric_total in metric_totals.items()
        if scored
    }
    metrics = {
        "metric": "metric_suite" if explicit_metric_suite else metric_name,
        "accuracy": round(accuracy, 4),
        "primary_score": round(accuracy, 4),
        "metrics_by_name": metrics_by_name,
        "avg_latency_ms": round(avg_latency, 1),
        "avg_ms_per_row": round(avg_ms_per_row, 1),
        "rows_total": n,
        "dataset_rows_total": len(rows),
        "rows_scored": scored,
        "rows_failed": n - scored,
        "rows_unprocessed": len(rows) - processed,
        "coverage": round(scored / len(rows), 4) if rows else 0.0,
        "failure_rate": round((provider_errors + metric_errors) / len(rows), 4) if rows else 0.0,
        "provider_errors": provider_errors,
        "metric_errors": metric_errors,
        "prompt_version": prompt_version,
    }
    runtime_ms = int((time.perf_counter() - started) * 1000)

    async def _persist() -> None:
        async with AsyncSessionLocal() as session:
            exp_repo = ExperimentRepository(session)
            if not await exp_repo.finish_if_running(
                experiment_id, status=status, error=rate_limited_msg or None
            ):
                logger.info("experiment %s lost persist race; discarding", experiment_id)
                return
            res_repo = ExperimentResultRepository(session)
            await res_repo.delete_by_experiment(experiment_id)
            await res_repo.bulk_create(result_objs)
            exp = await exp_repo.get(experiment_id)
            await exp_repo.update(
                exp,
                {
                    "progress": processed,
                    "rows_total": n,
                    "cells_done": cells_done,
                    "cells_error": cells_error,
                    "metrics": metrics,
                    "accuracy": round(accuracy, 4),
                    "avg_latency_ms": round(avg_latency, 1),
                    "total_cost": round(total_cost, 6),
                    "total_tokens": total_tokens,
                    "runtime_ms": runtime_ms,
                },
            )
            await session.commit()

    # The whole persist transaction is wrapped in a lock-retry so a transient
    # 'database is locked' (e.g. two backend processes sharing the SQLite file)
    # recovers instead of silently losing results. If retries are exhausted, we
    # surface the failure as a terminal 'failed' rather than leaving the
    # experiment stuck in 'running'.
    try:
        await with_retry_on_lock(_persist)
    except Exception as exc:
        logger.exception("experiment %s persist failed", experiment_id)
        # Preserve the original diagnostic; a 'database is locked' failure is the
        # common case, but any other persist error (e.g. disk I/O) must keep its
        # own message so it stays debuggable in the UI.
        await _mark_failed(experiment_id, str(exc)[:500])
