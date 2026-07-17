"""Benchmark service — business logic for the Benchmark module."""
from __future__ import annotations

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.core.exceptions import NotFoundError, ValidationError
from app.evaluation.metrics import DEFAULT_METRIC_FOR_TYPE, get_metric
from app.models.benchmark import Benchmark
from app.repositories.benchmark import BenchmarkRepository
from app.schemas.benchmark import BenchmarkCreate, BenchmarkUpdate

BENCHMARK_TYPES = {"qa", "coding", "agent", "classification", "generation"}


class BenchmarkService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = BenchmarkRepository(session)

    def _validate_metric(self, metric: str) -> None:
        try:
            get_metric(metric)
        except ValidationError as exc:
            raise ValidationError(f"Invalid metric {metric!r}: {exc.message}")

    async def create(self, data: BenchmarkCreate) -> Benchmark:
        metric = data.metric or DEFAULT_METRIC_FOR_TYPE.get(data.type)
        if metric is None:
            raise ValidationError(f"No default metric for benchmark type {data.type!r}")
        self._validate_metric(metric)

        obj = Benchmark(
            project_id=data.project_id,
            name=data.name,
            description=data.description,
            type=data.type,
            metric=metric,
            metric_config=data.metric_config,
        )
        return await self.repo.create(obj)

    async def get(self, benchmark_id: str) -> Benchmark:
        obj = await self.repo.get(benchmark_id)
        if obj is None:
            raise NotFoundError(f"Benchmark {benchmark_id} not found")
        return obj

    async def list(
        self,
        *,
        project_id: str | None = None,
        type: str | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> list[Benchmark]:
        return list(
            await self.repo.list(
                offset=offset,
                limit=limit,
                filters={"project_id": project_id, "type": type},
            )
        )

    async def update(self, benchmark_id: str, data: BenchmarkUpdate) -> Benchmark:
        obj = await self.get(benchmark_id)
        payload = data.model_dump(exclude_unset=True)
        if "metric" in payload and payload["metric"] is not None:
            self._validate_metric(payload["metric"])
        return await self.repo.update(obj, payload)

    async def delete(self, benchmark_id: str) -> None:
        obj = await self.get(benchmark_id)
        await self.repo.delete(obj)


def get_benchmark_service(
    session: AsyncSession = Depends(get_session),
) -> BenchmarkService:
    return BenchmarkService(session)
