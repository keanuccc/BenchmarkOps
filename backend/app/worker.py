"""ARQ worker entrypoint for the distributed evaluation queue.

Run with ``uv run arq app.worker.WorkerSettings`` (see docker-compose for the
container wiring). The worker consumes ``run_experiment`` jobs from Redis and
executes them with the same evaluation engine as the in-process queue.
"""
from __future__ import annotations

import logging

from arq import Retry
from arq.connections import RedisSettings
from arq.worker import func
from sqlalchemy.exc import OperationalError

from app.core.config import settings
from app.core.database import AsyncSessionLocal, with_retry_on_lock
from app.evaluation.errors import RetryableTaskError
from app.evaluation.runner import run_experiment
from app.repositories.experiment import ExperimentRepository

logger = logging.getLogger("benchmarkops.worker")


async def _reset_stale_running(experiment_id: str) -> None:
    """Let a new worker take over an experiment a dead worker left as 'running'.

    ARQ guarantees a claimable job is not being executed by any live worker
    (the ``arq:in-progress:<id>`` key guards concurrent claims), so a leftover
    'running' status can only come from a crashed/retried attempt. Reset it to
    'queued' so ``run_experiment``'s CAS can claim it again. Cancelled
    experiments are left untouched and skipped by the runner.

    The write is retried on transient 'database is locked' contention (the
    documented SQLite multi-writer caveat), and a lock error that survives the
    retries is converted to ``RetryableTaskError`` so the whole job is retried
    - still before any billable provider call.
    """
    async def _write() -> None:
        async with AsyncSessionLocal() as session:
            repo = ExperimentRepository(session)
            experiment = await repo.get(experiment_id)
            if experiment is not None and experiment.status == "running":
                await repo.update(experiment, {"status": "queued"})
                await session.commit()
                logger.info(
                    "experiment %s reset from stale 'running' to 'queued'",
                    experiment_id,
                )

    try:
        await with_retry_on_lock(_write)
    except OperationalError as exc:
        if "database is locked" in str(exc):
            raise RetryableTaskError(
                f"transient database lock while resetting stale running "
                f"experiment {experiment_id}: {exc}"
            ) from exc
        raise


async def run_experiment_task(ctx: dict, experiment_id: str) -> None:
    """ARQ job function: claim the experiment, then run it.

    Retry policy (billing-safe): only ``RetryableTaskError`` (transient DB
    failures before any provider call) is converted to ``arq.Retry``. Provider
    failures - including quota exhaustion - propagate as terminal job failures.
    """
    del ctx  # ARQ context is not needed by the runner
    try:
        await _reset_stale_running(experiment_id)
        await run_experiment(experiment_id)
    except RetryableTaskError as exc:
        logger.warning(
            "experiment %s hit a transient error; retrying in %ss: %s",
            experiment_id,
            settings.task_retry_after,
            exc,
        )
        raise Retry(defer=settings.task_retry_after) from exc


class WorkerSettings:
    """ARQ settings consumed by ``arq app.worker.WorkerSettings``."""

    functions = [
        func(
            run_experiment_task,
            name="run_experiment",
            max_tries=settings.task_max_tries,
        )
    ]
    redis_settings = RedisSettings.from_dsn(settings.redis_dsn)
    allow_abort_jobs = True
    max_jobs = settings.eval_max_workers
    job_timeout = settings.task_job_timeout
    keep_result = 3600
    max_tries = settings.task_max_tries
