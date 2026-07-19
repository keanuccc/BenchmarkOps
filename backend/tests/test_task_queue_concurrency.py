"""Concurrency guard for the background task queue.

Submits more coroutines than `eval_max_workers` and asserts the number of
simultaneously-running jobs never exceeds the configured cap. The pool uses an
asyncio.Semaphore, so we track concurrency with our own counter and let each job
wait a moment while holding its slot.
"""
from __future__ import annotations

import asyncio

from app.core.config import settings
from app.evaluation.task_queue import AsyncioTaskQueue


async def test_concurrency_bounded_by_eval_max_workers():
    # Use a low cap so the test is fast and deterministic regardless of config.
    queue = AsyncioTaskQueue()
    queue._sem = asyncio.Semaphore(2)

    current = 0
    peak = 0
    gate = asyncio.Event()

    async def job(i: int) -> None:
        nonlocal current, peak
        current += 1
        peak = max(peak, current)
        # Hold the slot so overlapping jobs actually contend for the semaphore.
        await gate.wait()
        current -= 1

    for i in range(8):
        queue.submit(lambda i=i: job(i))

    # Let all tasks start contending; sleepy but bounded.
    await asyncio.sleep(0.2)
    gate.set()
    # Give every task time to acquire (capped), run, and release.
    await asyncio.sleep(0.2)

    assert peak <= 2
    assert peak == 2, "expected the cap (2) to be reached at peak"
    assert settings.eval_max_workers >= 1


async def test_slot_always_released_on_failure():
    queue = AsyncioTaskQueue()
    queue._sem = asyncio.Semaphore(1)

    done = asyncio.Event()

    async def job() -> None:
        raise RuntimeError("boom")

    async def watch():
        await job()

    async def wrapped():
        try:
            await watch()
        finally:
            done.set()

    # The guard swallows the exception; we verify the slot is returned for reuse.
    queue.submit(wrapped)
    await done.wait()
    await asyncio.sleep(0.05)
    # Capacity-1 semaphore back to full after the failing job released it.
    assert queue._sem._value == 1
