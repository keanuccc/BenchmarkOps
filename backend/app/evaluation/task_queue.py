"""Task queue abstraction for background evaluation runs.

v1 uses an in-process asyncio task runner (`AsyncioTaskQueue`) so no Redis/Celery
is required. The Evaluation Engine depends only on `TaskQueue`, so swapping to
Celery later means implementing one class and changing a single wiring line.
"""
from __future__ import annotations

import asyncio
import logging
import threading
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable

from app.core.config import settings

logger = logging.getLogger("benchmarkops.tasks")


class TaskQueue(ABC):
    @abstractmethod
    def submit(self, coro_factory: Callable[[], Awaitable[None]]) -> None:
        """Schedule background work. Must not block the caller."""
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
        self._futures: set[asyncio.Future] = set()
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        self._ready.wait()

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._sem = asyncio.Semaphore(settings.eval_max_workers)
        self._ready.set()
        self._loop.run_forever()

    def submit(self, coro_factory: Callable[[], Awaitable[None]]) -> None:
        # Schedule on the queue's own loop, independent of the caller's loop,
        # so the job survives the caller's loop shutting down after the request.
        fut = asyncio.run_coroutine_threadsafe(self._guard(coro_factory), self._loop)
        self._futures.add(fut)
        fut.add_done_callback(self._futures.discard)

    async def _guard(self, coro_factory: Callable[[], Awaitable[None]]) -> None:
        # Acquire the concurrency slot only when work actually begins, then run.
        # try/finally guarantees the slot is always released, even on failure.
        await self._sem.acquire()
        try:
            await coro_factory()
        except Exception:  # noqa: BLE001
            logger.exception("Background evaluation task failed")
        finally:
            self._sem.release()


# Singleton for v1 (swap for a Celery-backed impl later).
task_queue: TaskQueue = AsyncioTaskQueue()
