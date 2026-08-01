"""Best-effort persistence + lifecycle updates for evaluation task records.

Every run submission creates one row in ``evaluation_tasks`` and the runner /
queue update it as the task progresses. All writes are best-effort: a failure
is logged, never raised, so a broken task log can never take down a run.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.core.database import AsyncSessionLocal, with_retry_on_lock
from app.models.task import EvaluationTask
from app.repositories.task import TaskRepository

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def create_task(experiment_id: str, action: str = "run") -> EvaluationTask | None:
    """Insert a queued task record for a run submission."""
    try:
        async with AsyncSessionLocal() as session:
            task = EvaluationTask(
                experiment_id=experiment_id,
                action=action,
                status="queued",
                attempts=1,
            )
            created = await TaskRepository(session).create(task)
            await session.commit()
            return created
    except Exception:  # noqa: BLE001
        logger.exception(
            "failed to create task record for experiment %s", experiment_id
        )
        return None


async def _update_latest(
    experiment_id: str, values: dict, error: str | None = None
) -> None:
    async def _write() -> None:
        async with AsyncSessionLocal() as session:
            repo = TaskRepository(session)
            task = await repo.get_latest_active(experiment_id)
            if task is None:
                return
            payload = dict(values)
            if error is not None:
                payload["error"] = (error or "")[:500] or None
            await repo.update(task, payload)
            await session.commit()

    try:
        await with_retry_on_lock(_write)
    except Exception:  # noqa: BLE001
        logger.debug("task record update skipped for experiment %s", experiment_id)


async def mark_running(experiment_id: str) -> None:
    await _update_latest(experiment_id, {"status": "running", "started_at": _now()})


async def mark_done(
    experiment_id: str, *, status: str, error: str | None = None
) -> None:
    if status not in ("succeeded", "failed", "cancelled"):
        raise ValueError(f"invalid terminal task status: {status}")
    await _update_latest(
        experiment_id,
        {"status": status, "finished_at": _now()},
        error=error,
    )


async def mark_failed_after_restart(experiment_id: str, reason: str) -> None:
    """Mark the active task failed during startup recovery."""
    await _update_latest(
        experiment_id,
        {"status": "failed", "finished_at": _now()},
        error=reason,
    )
