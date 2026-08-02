"""Repository for background dataset import jobs."""
from __future__ import annotations

from sqlalchemy import select

from app.models.import_job import ImportJob
from app.repositories.base import BaseRepository


class ImportJobRepository(BaseRepository[ImportJob]):
    model = ImportJob

    async def get_by_idempotency_key(
        self, project_id: str, key: str
    ) -> ImportJob | None:
        stmt = select(ImportJob).where(
            ImportJob.project_id == project_id,
            ImportJob.idempotency_key == key,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_by_project(
        self, project_id: str, *, limit: int = 100
    ) -> list[ImportJob]:
        stmt = (
            select(ImportJob)
            .where(ImportJob.project_id == project_id)
            .order_by(ImportJob.created_at.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_stale(self) -> list[ImportJob]:
        stmt = select(ImportJob).where(ImportJob.status.in_(("queued", "running")))
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
