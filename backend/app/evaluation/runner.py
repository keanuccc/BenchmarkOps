"""Evaluation runner — orchestrates a single experiment run.

Given an experiment id, it:
  1. loads dataset rows, prompt, benchmark, model,
  2. renders the prompt per row and calls the LLM provider,
  3. scores each output with the benchmark's metric,
  4. computes cost from the model's pricing,
  5. persists per-row results + aggregate metrics, and updates status.

It runs in the background with its own DB session (via AsyncSessionLocal), so it
must not depend on a request-scoped session.
"""
from __future__ import annotations

import asyncio
import logging
import time

from sqlalchemy.exc import SQLAlchemyError

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.evaluation.metrics import get_metric
from app.models.benchmark import Benchmark
from app.models.dataset import DatasetRow
from app.models.experiment import Experiment, ExperimentResult
from app.models.model import Model
from app.models.prompt import Prompt
from app.providers.base import ChatMessage, CompletionRequest
from app.providers.registry import get_provider
from app.repositories.dataset import DatasetRowRepository
from app.repositories.experiment import (
    ExperimentRepository,
    ExperimentResultRepository,
)

logger = logging.getLogger(__name__)

_BATCH_SIZE = 500  # dataset rows fetched per cursor page
_PROGRESS_EVERY = 50  # persist progress counter every N processed rows

logger = logging.getLogger(__name__)


def _first_value(d: dict | None) -> str:
    """Extract the ground-truth string from an expected dict ({key: value})."""
    if not d:
        return ""
    val = next(iter(d.values()), "")
    return "" if val is None else str(val)


def _render_prompt(template: str, variables: list[str], row_input: dict) -> str:
    """Render a prompt template against a dataset row.

    Missing declared variables are filled with the row's stringified input so runs
    never crash on a template/data mismatch (robustness over strictness for v1).
    """
    ctx = {k: ("" if v is None else v) for k, v in row_input.items()}
    for var in variables:
        ctx.setdefault(var, "")
    try:
        return template.format(**ctx)
    except (KeyError, IndexError):
        # Fallback: append the raw input so the model still sees the question.
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
    long-running run.
    """
    try:
        async with AsyncSessionLocal() as session:
            repo = ExperimentRepository(session)
            exp = await repo.get(experiment_id)
            if exp is not None:
                await repo.update(exp, {"status": "failed", "error": error[:500]})
                await session.commit()
    except SQLAlchemyError:  # noqa: BLE001
        logger.exception("failed to persist terminal 'failed' status")


async def _persist_progress(experiment_id: str, processed: int, rows_total: int) -> None:
    """Best-effort progress update on an isolated short session."""
    try:
        async with AsyncSessionLocal() as session:
            repo = ExperimentRepository(session)
            exp = await repo.get(experiment_id)
            if exp is not None and exp.status == "running":
                await repo.update(exp, {"progress": processed, "rows_total": rows_total})
                await session.commit()
    except SQLAlchemyError:  # noqa: BLE001
        logger.debug("progress update skipped (lock or missing experiment)")


async def run_experiment(experiment_id: str) -> None:
    logger.info("experiment %s run started", experiment_id)

    # --- Load phase: resolve config using an isolated, short read session. ---
    # This never holds a write lock, so concurrent API writes are never blocked.
    async with AsyncSessionLocal() as load_session:
        exp_repo = ExperimentRepository(load_session)
        experiment = await exp_repo.get(experiment_id)
        if experiment is None:
            return

        # CAS: only one concurrent runner may flip status to 'running'. If another
        # runner (or a prior in-flight run) already holds it, bail — never double-run.
        # The UPDATE must be COMMITTED here (not just flushed): this load session is
        # short-lived and its context-manager exit would otherwise roll the CAS back,
        # making it invisible to a concurrent runner and allowing a double-run.
        if not await exp_repo.set_running_if_not_running(experiment_id):
            return
        await load_session.commit()

        # Resolve prompt/benchmark/model from the creation-time snapshot when
        # present (reproducible runs), else fall back to live lookups for
        # experiments created before snapshots existed.
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

        # Materialize all dataset rows up-front, then close the read session so no
        # lock is held during the network-bound compute phase.
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

    # --- Compute phase: pure CPU + network, NO database write lock held. ---
    result_objs: list[ExperimentResult] = []
    total_score = 0.0
    total_cost = 0.0
    total_tokens = 0
    total_latency = 0
    scored = 0
    provider_errors = 0
    processed = 0
    started = time.perf_counter()

    for row in rows:
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
            score = float(
                metric_fn(completion.text, expected_str, **(metric_config or {}))
            )
            cost = _cost(
                pricing or {},
                completion.prompt_tokens,
                completion.completion_tokens,
            )
            result_objs.append(
                ExperimentResult(
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
            )
            total_score += score
            total_cost += cost
            total_tokens += completion.total_tokens
            total_latency += completion.latency_ms
            scored += 1
        except Exception as exc:  # noqa: BLE001
            provider_errors += 1
            result_objs.append(
                ExperimentResult(
                    experiment_id=experiment_id,
                    row_idx=row.idx,
                    input=row.input,
                    expected=row.expected,
                    output="",
                    score=0.0,
                    error=str(exc)[:500],
                )
            )

        processed += 1
        if processed % _PROGRESS_EVERY == 0:
            # Progress update on its own short connection; never the compute lock.
            await _persist_progress(experiment_id, processed, len(rows))

    # --- Persist phase: one short write transaction, no network awaits. ---
    n = len(result_objs)
    accuracy = (total_score / scored) if scored else 0.0
    avg_latency = (total_latency / scored) if scored else 0.0
    status = "partial" if provider_errors > 0 else "completed"
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

    # Decide the sole writer with a CAS: only the run that still holds the
    # 'running' status may persist results + advance to the terminal state. A
    # concurrent runner (both cleared the start-gate CAS under WAL) that lost
    # this race must NOT delete/bulk_create — otherwise the two would clobber
    # each other's result rows and flip the experiment to 'partial'. The loser
    # returns here, leaving the winner's committed state intact.
    try:
        async with AsyncSessionLocal() as session:
            exp_repo = ExperimentRepository(session)
            if not await exp_repo.finish_if_running(
                experiment_id, status=status, error=None
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
                    "metrics": metrics,
                    "accuracy": round(accuracy, 4),
                    "avg_latency_ms": round(avg_latency, 1),
                    "total_cost": round(total_cost, 6),
                    "total_tokens": total_tokens,
                    "runtime_ms": runtime_ms,
                },
            )
            await session.commit()
    except Exception as exc:  # noqa: BLE001
        logger.exception("experiment %s persist failed", experiment_id)
        await _mark_failed(experiment_id, str(exc)[:500])
