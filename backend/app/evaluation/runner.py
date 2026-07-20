"""Evaluation runner — orchestrates a single experiment run."""
from __future__ import annotations

import asyncio
import logging
import time

from sqlalchemy.exc import SQLAlchemyError

from app.core.config import settings
from app.core.database import AsyncSessionLocal, with_retry_on_lock
from app.evaluation.metrics import get_metric
from app.models.benchmark import Benchmark
from app.models.dataset import DatasetRow
from app.models.experiment import Experiment, ExperimentResult
from app.models.model import Model
from app.models.prompt import Prompt
from app.providers.base import ChatMessage, CompletionRequest, ProviderRateLimitedError
from app.providers.registry import get_provider
from app.repositories.dataset import DatasetRowRepository
from app.repositories.experiment import (
    ExperimentRepository,
    ExperimentResultRepository,
)

logger = logging.getLogger(__name__)

_BATCH_SIZE = 500
_PROGRESS_EVERY = 50

logger = logging.getLogger(__name__)


def _first_value(d: dict | None) -> str:
    if not d:
        return ""
    val = next(iter(d.values()), "")
    return "" if val is None else str(val)


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
    inp = float(pricing.get("input_per_1k", 0.0)) * (prompt_tokens / 1000.0)
    out = float(pricing.get("output_per_1k", 0.0)) * (completion_tokens / 1000.0)
    return round(inp + out, 6)


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
    experiment_id: str, processed: int, rows_total: int, *, cells_done: int = 0, cells_error: int = 0
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
                await repo.update(
                    exp,
                    {
                        "progress": processed,
                        "rows_total": rows_total,
                        "cells_done": cells_done,
                        "cells_error": cells_error,
                    },
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
        else:
            benchmark = await load_session.get(Benchmark, experiment.benchmark_id)
            if benchmark is None:
                return await _mark_failed(experiment_id, "Experiment references a missing benchmark")
            metric_name = benchmark.metric
            metric_config = benchmark.metric_config

        msnap = experiment.model_snapshot
        if msnap:
            model_ref = msnap.get("model_id")
            pricing = msnap.get("pricing", {}) or {}
        else:
            model = await load_session.get(Model, experiment.model_id)
            if model is None:
                return await _mark_failed(experiment_id, "Experiment references a missing model")
            model_ref = model.model_id
            pricing = model.pricing

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

        metric_fn = get_metric(metric_name)
        provider = get_provider()
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
        )
        expected_str = _first_value(row.expected)
        try:
            completion = await asyncio.wait_for(
                provider.complete(req),
                timeout=settings.eval_request_timeout,
            )
            score = float(metric_fn(completion.text, expected_str, **(metric_config or {})))
            cost = _cost(pricing or {}, completion.prompt_tokens, completion.completion_tokens)
            res = ExperimentResult(
                experiment_id=experiment_id,
                row_idx=row.idx,
                input=row.input,
                expected=row.expected,
                output=completion.text,
                score=score,
                latency_ms=completion.latency_ms,
                tokens=completion.total_tokens,
                cost=cost,
            )
            return res, False
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
            return res, True
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
            return res, False

    def _merge(res, is_rate_limited):
        """Fold one processed row into the shared accumulators. Called after gather, so
        no two merges run concurrently — safe without extra locking."""
        nonlocal scored, cells_done, cells_error, provider_errors, total_score, total_cost
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
                provider_errors += 1
                cells_error += 1
            else:
                total_score += res.score
                total_cost += res.cost
                total_tokens += res.tokens
                total_latency += res.latency_ms
                scored += 1
                cells_done += 1

    is_free = model_ref.endswith(":free")
    if is_free:
        # Free models measured RPM>=325 + high burst; run rows concurrently (bounded by
        # free_model_concurrency) and merge results serially. No fixed per-row sleep.
        sem = asyncio.Semaphore(settings.free_model_concurrency)

        async def _guarded(row):
            async with sem:
                return await _process_row(row)

        for i in range(0, len(rows), settings.free_model_concurrency):
            batch = rows[i : i + settings.free_model_concurrency]
            outcomes = await asyncio.gather(*(_guarded(r) for r in batch))
            for res, is_rl in outcomes:
                _merge(res, is_rl)
            processed += len(batch)
            # Report progress per batch (batch size == free_model_concurrency, well
            # under _PROGRESS_EVERY), so the UI bar advances without waiting
            # for a full _PROGRESS_EVERY worth of rows under concurrency.
            await _persist_progress(
                experiment_id, processed, len(rows), cells_done=cells_done, cells_error=cells_error
            )
            if rate_limited:
                break
    else:
        # Non-free models: keep the original strict-serial behavior (rate safety is
        # handled by the task queue's eval_max_workers, not by in-run concurrency).
        for row in rows:
            res, is_rl = await _process_row(row)
            _merge(res, is_rl)
            processed += 1
            if processed % _PROGRESS_EVERY == 0:
                await _persist_progress(
                    experiment_id, processed, len(rows), cells_done=cells_done, cells_error=cells_error
                )
            if rate_limited:
                break

    n = len(result_objs)
    accuracy = (total_score / scored) if scored else 0.0
    avg_latency = (total_latency / scored) if scored else 0.0
    status = "failed" if rate_limited else ("partial" if provider_errors > 0 else "completed")
    metrics = {
        "metric": metric_name,
        "accuracy": round(accuracy, 4),
        "avg_latency_ms": round(avg_latency, 1),
        "rows_total": n,
        "rows_scored": scored,
        "rows_failed": n - scored,
        "provider_errors": provider_errors,
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
