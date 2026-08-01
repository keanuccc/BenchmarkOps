"""Task queue abstraction for background evaluation runs.

v1 uses an in-process asyncio task runner (`AsyncioTaskQueue`) so no Redis/Celery
is required. The Evaluation Engine depends only on `TaskQueue`, so swapping to
Celery later means implementing one class and changing a single wiring line.

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

from app.core.config import settings
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
        """Cancel a running task by experiment_id. Returns True if found and cancelled."""
        fut = self._futures.get(experiment_id)
        if fut and not fut.done():
            fut.cancel()
            return True
        return False


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


# Singleton for v1 (swap for a Celery-backed impl later).
task_queue: TaskQueue = AsyncioTaskQueue()
