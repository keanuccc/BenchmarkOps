"""Benchmark service — business logic for the Benchmark module."""
from __future__ import annotations

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from app.core.database import get_session
from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.evaluation.metrics import (
    DEFAULT_METRIC_FOR_TYPE,
    get_metric,
    normalize_metric_suite,
    validate_metric_suite,
)
from app.models.benchmark import Benchmark
from app.repositories.benchmark import BenchmarkRepository
from app.repositories.experiment import ExperimentRepository
from app.schemas.benchmark import BenchmarkCreate, BenchmarkUpdate

BENCHMARK_TYPES = {"qa", "coding", "agent", "classification", "generation"}


def _benchmark_version(metric_config: dict | None) -> int:
    config = metric_config or {}
    spec = config.get("spec") if isinstance(config.get("spec"), dict) else {}
    version = spec.get("version", config.get("version", 1))
    try:
        return int(version)
    except (TypeError, ValueError):
        return 1


def build_benchmark_spec(benchmark: Benchmark) -> dict:
    metric_config = benchmark.metric_config or {}
    embedded = metric_config.get("spec") if isinstance(metric_config.get("spec"), dict) else {}
    spec = dict(embedded)
    version = _benchmark_version(metric_config)
    spec["version"] = version
    spec["task_type"] = spec.get("task_type") or benchmark.type
    spec["metric_suite_explicit"] = bool(
        isinstance(metric_config.get("metric_suite"), list)
        or isinstance(embedded.get("metric_suite"), list)
    )
    spec["metric_suite"] = normalize_metric_suite(
        benchmark.metric,
        metric_config,
        spec,
    )
    for key in ("pass_policy", "reporting_policy"):
        if key not in spec and key in metric_config:
            spec[key] = metric_config[key]
    return spec


def build_benchmark_snapshot(benchmark: Benchmark) -> dict:
    metric_config = benchmark.metric_config or {}
    version = _benchmark_version(metric_config)
    return {
        "type": benchmark.type,
        "name": benchmark.name,
        "version": version,
        "metric": benchmark.metric,
        "metric_config": metric_config,
        "spec": build_benchmark_spec(benchmark),
    }


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
        from app.repositories.project import ProjectRepository

        if await ProjectRepository(self.session).get(data.project_id) is None:
            raise ValidationError(f"Project '{data.project_id}' does not exist")
        suite = (data.metric_config or {}).get("metric_suite")
        if data.metric is None and isinstance(suite, list) and suite:
            metric = suite[0].get("name")
        else:
            metric = data.metric or DEFAULT_METRIC_FOR_TYPE.get(data.type)
        if metric is None:
            raise ValidationError(f"No default metric for benchmark type {data.type!r}")
        self._validate_metric(metric)
        validate_metric_suite(metric, data.metric_config)

        obj = Benchmark(
            project_id=data.project_id,
            name=data.name,
            description=data.description,
            type=data.type,
            metric=metric,
            metric_config=data.metric_config,
        )
        try:
            return await self.repo.create(obj)
        except IntegrityError:
            await self.session.rollback()
            raise ConflictError(
                f"Benchmark '{data.name}' already exists in project '{data.project_id}'"
            ) from None

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
        q: str | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> list[Benchmark]:
        return list(
            await self.repo.list(
                offset=offset,
                limit=limit,
                filters={"project_id": project_id, "type": type},
                search=q,
            )
        )

    async def count(
        self,
        *,
        project_id: str | None = None,
        type: str | None = None,
        q: str | None = None,
    ) -> int:
        return await self.repo.count(
            filters={"project_id": project_id, "type": type}, search=q
        )

    async def update(self, benchmark_id: str, data: BenchmarkUpdate) -> Benchmark:
        obj = await self.get(benchmark_id)
        payload = data.model_dump(exclude_unset=True)
        if "metric" in payload and payload["metric"] is not None:
            self._validate_metric(payload["metric"])
        metric = payload.get("metric") or obj.metric
        metric_config = payload.get("metric_config", obj.metric_config)
        validate_metric_suite(metric, metric_config)
        old_name = obj.name
        old_project_id = obj.project_id
        try:
            return await self.repo.update(obj, payload)
        except IntegrityError:
            await self.session.rollback()
            raise ConflictError(
                f"Benchmark '{payload.get('name', old_name)}' already exists "
                f"in project '{old_project_id}'"
            ) from None

    async def archive(self, benchmark_id: str) -> Benchmark:
        obj = await self.get(benchmark_id)
        return await self.repo.update(obj, {"is_archived": True})

    async def unarchive(self, benchmark_id: str) -> Benchmark:
        obj = await self.get(benchmark_id)
        return await self.repo.update(obj, {"is_archived": False})

    async def delete(self, benchmark_id: str) -> None:
        obj = await self.get(benchmark_id)
        references = await ExperimentRepository(self.session).count_by_component(
            benchmark_id=benchmark_id
        )
        if references:
            raise ConflictError(
                f"Benchmark is referenced by {references} experiment(s); "
                "delete those experiments first"
            )
        await self.repo.delete(obj)


def get_benchmark_service(
    session: AsyncSession = Depends(get_session),
) -> BenchmarkService:
    return BenchmarkService(session)
