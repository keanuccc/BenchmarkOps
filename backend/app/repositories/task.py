"""Repository for evaluation task records."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select, update

from app.models.task import EvaluationTask
from app.repositories.base import BaseRepository


class TaskRepository(BaseRepository[EvaluationTask]):
    model = EvaluationTask

    async def get_latest_active(
        self, experiment_id: str
    ) -> EvaluationTask | None:
        """Newest queued/running record for an experiment (single active task)."""
        stmt = (
            select(EvaluationTask)
            .where(
                EvaluationTask.experiment_id == experiment_id,
                EvaluationTask.status.in_(("queued", "running")),
                EvaluationTask.experiment_deleted_at.is_(None),
            )
            .order_by(EvaluationTask.created_at.desc())
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def mark_experiment_deleted(self, experiment_ids: list[str]) -> None:
        """Mark all active task rows as belonging to deleted experiments."""
        if not experiment_ids:
            return
        await self.session.execute(
            update(EvaluationTask)
            .where(
                EvaluationTask.experiment_id.in_(experiment_ids),
                EvaluationTask.experiment_deleted_at.is_(None),
            )
            .values(experiment_deleted_at=datetime.now(timezone.utc))
        )
        await self.session.flush()
