"""Repository for evaluation task records."""
from __future__ import annotations

from sqlalchemy import select

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
            )
            .order_by(EvaluationTask.created_at.desc())
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()
