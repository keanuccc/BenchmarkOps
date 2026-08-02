"""Repositories for the Dataset Center module."""
from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import func, select

from app.models.dataset import Dataset, DatasetRow, DatasetVersion
from app.repositories.base import BaseRepository


class DatasetRepository(BaseRepository[Dataset]):
    model = Dataset


class DatasetVersionRepository(BaseRepository[DatasetVersion]):
    """Metadata snapshots for each immutable dataset version."""

    model = DatasetVersion

    async def list_by_dataset(
        self, dataset_id: str, *, limit: int = 100
    ) -> Sequence[DatasetVersion]:
        stmt = (
            select(DatasetVersion)
            .where(DatasetVersion.dataset_id == dataset_id)
            .order_by(DatasetVersion.version.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_by_version(self, dataset_id: str, version: int) -> DatasetVersion | None:
        stmt = select(DatasetVersion).where(
            DatasetVersion.dataset_id == dataset_id,
            DatasetVersion.version == version,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def delete_by_dataset(self, dataset_id: str) -> None:
        stmt = select(DatasetVersion).where(DatasetVersion.dataset_id == dataset_id)
        result = await self.session.execute(stmt)
        for obj in result.scalars().all():
            await self.session.delete(obj)
        await self.session.flush()


class DatasetRowRepository(BaseRepository[DatasetRow]):
    model = DatasetRow

    async def count_by_dataset(self, dataset_id: str) -> int:
        stmt = (
            select(func.count())
            .select_from(DatasetRow)
            .where(DatasetRow.dataset_id == dataset_id)
        )
        result = await self.session.execute(stmt)
        return int(result.scalar_one())

    async def count_by_dataset_version(self, dataset_id: str, version: int) -> int:
        stmt = (
            select(func.count())
            .select_from(DatasetRow)
            .where(DatasetRow.dataset_id == dataset_id)
            .where(DatasetRow.version == version)
        )
        result = await self.session.execute(stmt)
        return int(result.scalar_one())

    async def list_by_dataset(
        self,
        dataset_id: str,
        offset: int = 0,
        limit: int = 20,
        version: int | None = None,
    ) -> Sequence[DatasetRow]:
        stmt = (
            select(DatasetRow)
            .where(DatasetRow.dataset_id == dataset_id)
            .order_by(DatasetRow.idx)
            .offset(offset)
            .limit(limit)
        )
        if version is not None:
            stmt = stmt.where(DatasetRow.version == version)
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def bulk_create(self, rows: list[DatasetRow]) -> None:
        self.session.add_all(rows)
        await self.session.flush()

    async def delete_by_dataset(self, dataset_id: str) -> None:
        stmt = select(DatasetRow).where(DatasetRow.dataset_id == dataset_id)
        result = await self.session.execute(stmt)
        for row in result.scalars().all():
            await self.session.delete(row)
        await self.session.flush()
