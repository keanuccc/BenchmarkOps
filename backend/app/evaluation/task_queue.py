"""Task queue abstraction for background evaluation runs.

v1 uses an in-process asyncio task runner (`AsyncioTaskQueue`) so no Redis/Celery
is required. The Evaluation Engine depends only on `TaskQueue`, so swapping to
Celery later means implementing one class and changing a single wiring line.
"""
from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable

logger = logging.getLogger("benchmarkops.tasks")


class TaskQueue(ABC):
    @abstractmethod
    def submit(self, coro_factory: Callable[[], Awaitable[None]]) -> None:
        """Schedule background work. Must not block the caller."""
        raise NotImplementedError


class AsyncioTaskQueue(TaskQueue):
    """Runs each job as a detached asyncio Task on the running event loop.

    Keeps strong references so tasks aren't garbage-collected mid-flight, and logs
    unhandled exceptions instead of crashing the request that submitted them.
    """

    def __init__(self) -> None:
        self._tasks: set[asyncio.Task] = set()

    def submit(self, coro_factory: Callable[[], Awaitable[None]]) -> None:
        task = asyncio.create_task(self._guard(coro_factory))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    @staticmethod
    async def _guard(coro_factory: Callable[[], Awaitable[None]]) -> None:
        try:
            await coro_factory()
        except Exception:  # noqa: BLE001
            logger.exception("Background evaluation task failed")


# Singleton for v1 (swap for a Celery-backed impl later).
task_queue: TaskQueue = AsyncioTaskQueue()
