"""Business logic for the Dataset Center module."""
from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Sequence

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.core.exceptions import NotFoundError, ValidationError
from app.models.dataset import Dataset, DatasetRow
from app.repositories.dataset import DatasetRepository, DatasetRowRepository
from app.schemas.dataset import DatasetUpdate
from app.services.dataset_parser import (
    compute_stats,
    infer_schema,
    parse_dataset,
    split_input_expected,
)

_DEFAULT_PAGE_SIZE = 100


class DatasetService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.datasets = DatasetRepository(session)
        self.rows = DatasetRowRepository(session)

    async def create_from_upload(
        self,
        project_id: str,
        name: str,
        description: str | None,
        tags: list[str] | None,
        fmt: str,
        raw_bytes: bytes,
    ) -> Dataset:
        raw_rows = parse_dataset(raw_bytes, fmt)
        parsed = [split_input_expected(r) for r in raw_rows]

        row_objs = [
            DatasetRow(
                dataset_id="",  # assigned after dataset id is known
                idx=i,
                input=inp,
                expected=exp,
            )
            for i, (inp, exp) in enumerate(parsed)
        ]

        stats = compute_stats([inp | (exp or {}) for inp, exp in parsed])
        column_schema = infer_schema([inp | (exp or {}) for inp, exp in parsed])

        dataset = Dataset(
            project_id=project_id,
            name=name,
            description=description,
            format=fmt,
            tags=tags or [],
            row_count=len(parsed),
            stats=stats,
            column_schema=column_schema,
        )
        created = await self.datasets.create(dataset)
        for obj in row_objs:
            obj.dataset_id = created.id
        await self.rows.bulk_create(row_objs)
        return created

    async def get(self, dataset_id: str) -> Dataset:
        dataset = await self.datasets.get(dataset_id)
        if dataset is None:
            raise NotFoundError(f"Dataset {dataset_id} not found")
        return dataset

    async def list(
        self, *, project_id: str | None = None, offset: int = 0, limit: int = _DEFAULT_PAGE_SIZE
    ) -> Sequence[Dataset]:
        filters = {"project_id": project_id}
        return await self.datasets.list(offset=offset, limit=limit, filters=filters)

    async def update(self, dataset_id: str, data: DatasetUpdate) -> Dataset:
        dataset = await self.get(dataset_id)
        payload = data.model_dump(exclude_unset=True)
        return await self.datasets.update(dataset, payload)

    async def delete(self, dataset_id: str) -> None:
        dataset = await self.get(dataset_id)
        await self.rows.delete_by_dataset(dataset_id)
        await self.datasets.delete(dataset)

    async def preview(
        self, dataset_id: str, offset: int = 0, limit: int = 20
    ) -> Sequence[DatasetRow]:
        await self.get(dataset_id)  # ensure exists
        return await self.rows.list_by_dataset(dataset_id, offset=offset, limit=limit)

    async def get_stats(self, dataset_id: str) -> dict:
        dataset = await self.get(dataset_id)
        return dataset.stats

    async def validate(self, dataset_id: str) -> dict:
        await self.get(dataset_id)
        rows = await self.rows.list_by_dataset(dataset_id, offset=0, limit=1_000_000)
        reconstructed = [r.input | (r.expected or {}) for r in rows]
        stats = compute_stats(reconstructed)
        issues: list[str] = []
        expected = len(rows)
        if stats["row_count"] != expected:
            issues.append("Row count mismatch between stored rows and computed stats")
        valid = len(issues) == 0
        return {"valid": valid, "issues": issues, "stats": stats}


async def get_dataset_service(
    session: AsyncSession = Depends(get_session),
) -> AsyncGenerator[DatasetService, None]:
    yield DatasetService(session)
