"""Business logic for the Experiment module + Evaluation Engine entrypoint."""
from __future__ import annotations

import logging
from collections.abc import AsyncGenerator, Sequence

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.evaluation.runner import run_experiment
from app.evaluation.task_queue import task_queue
from app.models.benchmark import Benchmark
from app.models.dataset import Dataset
from app.models.experiment import Experiment, ExperimentResult
from app.models.model import Model
from app.models.prompt import Prompt
from app.repositories.experiment import (
    ExperimentRepository,
    ExperimentResultRepository,
)
from app.schemas.experiment import ExperimentCreate, ExperimentUpdate
from app.services.benchmark_service import build_benchmark_snapshot

logger = logging.getLogger(__name__)


class ExperimentService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.experiments = ExperimentRepository(session)
        self.results = ExperimentResultRepository(session)

    async def _validate_components(self, data: ExperimentCreate) -> None:
        """Ensure all referenced aggregates exist before creating an experiment."""
        checks = {
            "dataset": (Dataset, data.dataset_id),
            "benchmark": (Benchmark, data.benchmark_id),
            "prompt": (Prompt, data.prompt_id),
            "model": (Model, data.model_id),
        }
        for label, (model_cls, oid) in checks.items():
            if await self.session.get(model_cls, oid) is None:
                raise ValidationError(f"Referenced {label} '{oid}' does not exist")

    async def create(self, data: ExperimentCreate) -> Experiment:
        await self._validate_components(data)

        # Snapshot the referenced components' current content so a later edit to a
        # prompt/benchmark/model does not change how this experiment reproduces.
        prompt = await self.session.get(Prompt, data.prompt_id)
        benchmark = await self.session.get(Benchmark, data.benchmark_id)
        model = await self.session.get(Model, data.model_id)
        prompt_snapshot = {
            "template": prompt.template,
            "variables": prompt.variables,
            "version": prompt.version,
        }
        benchmark_snapshot = build_benchmark_snapshot(benchmark)
        model_snapshot = {
            "model_id": model.model_id,
            "name": model.name,
            "pricing": model.pricing,
        }

        experiment = Experiment(
            project_id=data.project_id,
            name=data.name,
            dataset_id=data.dataset_id,
            benchmark_id=data.benchmark_id,
            prompt_id=data.prompt_id,
            model_id=data.model_id,
            params=data.params or {},
            prompt_snapshot=prompt_snapshot,
            benchmark_snapshot=benchmark_snapshot,
            model_snapshot=model_snapshot,
            status="pending",
        )
        created = await self.experiments.create(experiment)
        logger.info("experiment %s created (project %s)", created.id, data.project_id)
        return created

    async def get(self, experiment_id: str) -> Experiment:
        exp = await self.experiments.get(experiment_id)
        if exp is None:
            raise NotFoundError(f"Experiment {experiment_id} not found")
        return exp

    async def list(
        self,
        *,
        project_id: str | None = None,
        status: str | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> Sequence[Experiment]:
        return await self.experiments.list(
            offset=offset,
            limit=limit,
            filters={"project_id": project_id, "status": status},
        )

    async def update(self, experiment_id: str, data: ExperimentUpdate) -> Experiment:
        exp = await self.get(experiment_id)
        return await self.experiments.update(exp, data.model_dump(exclude_unset=True))

    async def delete(self, experiment_id: str) -> None:
        exp = await self.get(experiment_id)
        await self.results.delete_by_experiment(experiment_id)
        await self.experiments.delete(exp)
        logger.info("experiment %s deleted", experiment_id)

    async def list_results(
        self, experiment_id: str, *, offset: int = 0, limit: int = 1000
    ) -> Sequence[ExperimentResult]:
        await self.get(experiment_id)
        return await self.results.list_by_experiment(
            experiment_id, offset=offset, limit=limit
        )

    async def run(self, experiment_id: str) -> Experiment:
        """Queue a background evaluation run. Guard against in-flight/dup submissions."""
        exp = await self.get(experiment_id)
        if exp.status in ("running", "queued"):
            raise ConflictError("Experiment is already running")
        # Mark queued immediately so the UI reflects receipt before work begins.
        await self.experiments.update(exp, {"status": "queued", "error": None})
        await self.session.commit()
        task_queue.submit(lambda: run_experiment(experiment_id), experiment_id=experiment_id)
        return exp

    async def retry(self, experiment_id: str) -> Experiment:
        """Re-run a completed/failed experiment (results are cleared by the runner)."""
        exp = await self.get(experiment_id)
        if exp.status in ("running", "queued"):
            raise ConflictError("Experiment is already running")
        return await self.run(experiment_id)

    async def duplicate(self, experiment_id: str, name: str | None = None) -> Experiment:
        src = await self.get(experiment_id)
        clone = Experiment(
            project_id=src.project_id,
            name=name or f"{src.name} (copy)",
            dataset_id=src.dataset_id,
            benchmark_id=src.benchmark_id,
            prompt_id=src.prompt_id,
            model_id=src.model_id,
            params=dict(src.params or {}),
            prompt_snapshot=src.prompt_snapshot,
            benchmark_snapshot=src.benchmark_snapshot,
            model_snapshot=src.model_snapshot,
            status="pending",
        )
        return await self.experiments.create(clone)


async def get_experiment_service(
    session: AsyncSession = Depends(get_session),
) -> AsyncGenerator[ExperimentService, None]:
    yield ExperimentService(session)
