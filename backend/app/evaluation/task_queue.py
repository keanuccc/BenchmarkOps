"""Task queue abstraction for background evaluation runs.

v1 uses an in-process asyncio task runner (`AsyncioTaskQueue`). The distributed
backend (`ArqTaskQueue`) persists jobs in Redis and lets multiple worker
processes consume them. The Evaluation Engine depends only on `TaskQueue`, so
swapping backends is a config change (`settings.task_queue_backend`).

Task persistence:
- Task state (queued/running/completed/failed) lives in the experiments DB table.
- On startup, any experiment stuck in "running" or "queued" is auto-recovered
  (marked as failed with a diagnostic message).
- A running task can be cancelled by setting its status to "cancelled" — the
  runner checks this between rows and exits gracefully.
"""
from __future__ import annotations

import asyncio
import logging
import threading
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable

from arq.connections import ArqRedis, RedisSettings, create_pool
from arq.constants import (
    abort_jobs_ss,
    default_queue_name,
    in_progress_key_prefix,
    job_key_prefix,
    result_key_prefix,
)
from arq.jobs import Job
from arq.utils import timestamp_ms

from app.core.config import settings
from app.evaluation.cancellation import request_cancel
from app.evaluation.task_records import mark_done

logger = logging.getLogger("benchmarkops.tasks")


class TaskQueue(ABC):
    @abstractmethod
    def submit(self, coro_factory: Callable[[], Awaitable[None]]) -> None:
        """Schedule background work. Must not block the caller."""
        raise NotImplementedError

    @abstractmethod
    def get_running_tasks(self) -> list[str]:
        """Return experiment_ids of tasks currently executing."""
        raise NotImplementedError

    @abstractmethod
    def cancel_task(self, experiment_id: str) -> bool:
        """Cancel a running task. Returns True if cancellation was requested."""
        raise NotImplementedError


class AsyncioTaskQueue(TaskQueue):
    """Runs each job as an asyncio Task on a dedicated background event loop.

    A standalone loop (its own thread) owns the tasks, so a job keeps running
    even after the submitting HTTP request's own event loop has shut down —
    which is exactly what happens under Starlette's synchronous TestClient and
    is also the correct behaviour for a fire-and-forget background worker in
    production. The submitting coroutine just schedules the work and returns.
    """

    def __init__(self) -> None:
        # Bounds how many evaluations run their real provider calls concurrently.
        # Protects the SQLite single-writer lock and the provider's rate limit.
        self._loop = asyncio.new_event_loop()
        # Semaphore is created on the loop thread itself (see _run_loop), since
        # asyncio primitives bind to a loop at construction time and the loop
        # only exists once the background thread starts.
        self._sem: asyncio.Semaphore | None = None
        self._futures: dict[str, asyncio.Future] = {}  # experiment_id -> future
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        self._ready.wait()

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._sem = asyncio.Semaphore(settings.eval_max_workers)
        self._ready.set()
        self._loop.run_forever()

    def submit(self, coro_factory: Callable[[], Awaitable[None]], *, experiment_id: str | None = None) -> None:
        # Schedule on the queue's own loop, independent of the caller's loop,
        # so the job survives the caller's loop shutting down after the request.
        fut = asyncio.run_coroutine_threadsafe(
            self._guard(coro_factory, experiment_id=experiment_id), self._loop
        )
        if experiment_id:
            self._futures[experiment_id] = fut
        else:
            self._futures[id(fut)] = fut
        fut.add_done_callback(lambda f: self._futures.pop(next((k for k, v in self._futures.items() if v is f), None), None))

    async def _guard(self, coro_factory: Callable[[], Awaitable[None]], *, experiment_id: str | None = None) -> None:
        # Acquire the concurrency slot only when work actually begins, then run.
        # try/finally guarantees the slot is always released, even on failure.
        await self._sem.acquire()
        try:
            await coro_factory()
        except asyncio.CancelledError:
            logger.info("Background evaluation task cancelled%s", f" ({experiment_id})" if experiment_id else "")
            if experiment_id:
                await _mark_experiment_cancelled(experiment_id)
                await mark_done(experiment_id, status="cancelled")
        except Exception:  # noqa: BLE001
            logger.exception("Background evaluation task failed")
            if experiment_id:
                await _mark_experiment_failed(experiment_id)
                await mark_done(experiment_id, status="failed")
        finally:
            self._sem.release()

    def get_running_tasks(self) -> list[str]:
        """Return experiment_ids of futures that are still running (not done)."""
        return [
            eid for eid, fut in self._futures.items()
            if isinstance(eid, str) and not fut.done()
        ]

    def cancel_task(self, experiment_id: str) -> bool:
        """Request graceful cancellation of a tracked task.

        The in-process runner checks the cancellation registry between rows, so
        we never hard-cancel the future mid-provider-call (which could interrupt
        a billable request). Returns True if the task was tracked and running.
        """
        fut = self._futures.get(experiment_id)
        if fut and not fut.done():
            request_cancel(experiment_id)
            return True
        return False


class ArqTaskQueue(TaskQueue):
    """Redis-persisted queue backed by ARQ.

    Jobs are enqueued with ``_job_id=experiment_id`` so a duplicate submission is
    a no-op and a worker can cancel/query by experiment id. All Redis I/O runs
    on a dedicated background loop so the caller (an HTTP request) never blocks.
    """

    def __init__(self, *, redis_dsn: str | None = None) -> None:
        self._redis_dsn = redis_dsn or settings.redis_dsn
        self._pool: ArqRedis | None = None
        self._loop = asyncio.new_event_loop()
        self._ready = threading.Event()
        self._thread = threading.Thread(
            target=self._run_loop, daemon=True, name="arq-task-queue"
        )
        self._thread.start()
        self._ready.wait()

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._ready.set()
        self._loop.run_forever()

    def _call(self, coro: Awaitable, timeout: float = 10.0):
        """Run a coroutine on the queue's own loop and wait for its result."""
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result(timeout=timeout)

    async def _get_pool(self) -> ArqRedis:
        if self._pool is None:
            self._pool = await create_pool(RedisSettings.from_dsn(self._redis_dsn))
        return self._pool

    async def _enqueue(self, experiment_id: str) -> None:
        pool = await self._get_pool()
        # Keep ARQ's uniqueness guarantee for jobs that are already queued or
        # claimed: never enqueue a second copy of a live job.
        if await pool.zscore(default_queue_name, experiment_id) is not None:
            logger.info(
                "job for experiment %s already queued; skipping enqueue",
                experiment_id,
            )
            return
        if await pool.exists(in_progress_key_prefix + experiment_id):
            logger.info(
                "experiment %s already running; skipping enqueue", experiment_id
            )
            return
        # A finished job leaves a retained result key, and a cancelled job can
        # leave its job key and abort marker. All of those would make
        # ``enqueue_job`` a silent no-op and strand a retried experiment in
        # 'queued', so clear the stale state before re-enqueueing.
        await pool.delete(job_key_prefix + experiment_id, result_key_prefix + experiment_id)
        await pool.zrem(abort_jobs_ss, experiment_id)
        job = await pool.enqueue_job(
            "run_experiment", experiment_id, _job_id=experiment_id
        )
        if job is None:
            logger.info(
                "job for experiment %s already exists in Redis; skipping enqueue",
                experiment_id,
            )

    def submit(self, coro_factory: Callable[[], Awaitable[None]], *, experiment_id: str | None = None) -> None:
        """Enqueue a persistent run_experiment job. The coroutine factory is an
        in-process-queue detail; ARQ re-executes by experiment id from Redis."""
        if not experiment_id:
            raise ValueError("ArqTaskQueue.submit requires experiment_id")
        self._call(self._enqueue(experiment_id))

    async def _cancel(self, experiment_id: str) -> bool:
        pool = await self._get_pool()
        job = Job(
            experiment_id,
            pool,
            _queue_name=pool.default_queue_name,
            _deserializer=pool.job_deserializer,
        )
        if await job.info() is None:
            return False
        # Non-blocking cancel: remove the job from the queue and mark it in the
        # abort set so a worker that already claimed it is cancelled. We do not
        # call Job.abort() (it blocks until a worker records the result, which
        # may never happen if no worker is running); the DB status written by
        # the cancel endpoint is the source of truth.
        await pool.zrem(default_queue_name, experiment_id)
        await pool.zadd(abort_jobs_ss, {experiment_id: timestamp_ms()})
        logger.info("cancel signal sent for experiment %s", experiment_id)
        return True

    def cancel_task(self, experiment_id: str) -> bool:
        """Signal cancellation for a queued/running ARQ job. Best-effort."""
        try:
            return self._call(self._cancel(experiment_id))
        except Exception:  # noqa: BLE001
            logger.exception("failed to cancel ARQ job for experiment %s", experiment_id)
            return False

    async def _running(self) -> list[str]:
        pool = await self._get_pool()
        keys = await pool.keys(in_progress_key_prefix + "*")
        return [key.decode().rsplit(":", 1)[-1] for key in keys]

    def get_running_tasks(self) -> list[str]:
        """Return experiment ids of jobs currently being executed by workers."""
        return self._call(self._running())


async def _mark_experiment_failed(experiment_id: str) -> None:
    """Best-effort: mark an experiment as 'failed' when its background task crashes.

    Must not be called while holding the long-running runner's session — this opens
    its own isolated connection. Retries on transient 'database is locked'.
    """
    from app.core.database import AsyncSessionLocal, with_retry_on_lock
    from app.repositories.experiment import ExperimentRepository

    async def _write() -> None:
        async with AsyncSessionLocal() as session:
            repo = ExperimentRepository(session)
            exp = await repo.get(experiment_id)
            if exp is not None and exp.status == "running":
                await repo.update(exp, {"status": "failed"})
                await session.commit()

    try:
        await with_retry_on_lock(_write)
    except Exception:  # noqa: BLE001
        logger.exception("failed to mark experiment %s as failed", experiment_id)


async def _mark_experiment_cancelled(experiment_id: str) -> None:
    """Best-effort: mark an experiment as 'cancelled' when the user cancels it."""
    from app.core.database import AsyncSessionLocal, with_retry_on_lock
    from app.repositories.experiment import ExperimentRepository

    async def _write() -> None:
        async with AsyncSessionLocal() as session:
            repo = ExperimentRepository(session)
            exp = await repo.get(experiment_id)
            if exp is not None and exp.status == "running":
                await repo.update(exp, {"status": "cancelled"})
                await session.commit()

    try:
        await with_retry_on_lock(_write)
    except Exception:  # noqa: BLE001
        logger.exception("failed to mark experiment %s as cancelled", experiment_id)


def _create_task_queue() -> TaskQueue:
    if settings.task_queue_backend == "arq":
        return ArqTaskQueue()
    return AsyncioTaskQueue()


# Singleton, selected by settings.task_queue_backend ("asyncio" | "arq").
task_queue: TaskQueue = _create_task_queue()
