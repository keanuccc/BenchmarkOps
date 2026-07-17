"""Repositories for the Dataset Center module."""
from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import select

from app.models.dataset import Dataset, DatasetRow
from app.repositories.base import BaseRepository


class DatasetRepository(BaseRepository[Dataset]):
    model = Dataset


class DatasetRowRepository(BaseRepository[DatasetRow]):
    model = DatasetRow

    async def list_by_dataset(
        self, dataset_id: str, offset: int = 0, limit: int = 20
    ) -> Sequence[DatasetRow]:
        stmt = (
            select(DatasetRow)
            .where(DatasetRow.dataset_id == dataset_id)
            .order_by(DatasetRow.idx)
            .offset(offset)
            .limit(limit)
        )
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
