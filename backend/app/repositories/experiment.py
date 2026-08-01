"""Repositories for the Experiment aggregate."""
from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import func, select, update

from app.models.experiment import Experiment, ExperimentResult
from app.repositories.base import BaseRepository


class ExperimentRepository(BaseRepository[Experiment]):
    model = Experiment

    async def count_by_component(
        self,
        *,
        dataset_id: str | None = None,
        benchmark_id: str | None = None,
        prompt_id: str | None = None,
        model_id: str | None = None,
    ) -> int:
        """Count experiments referencing the given component(s).

        Used by delete guards: a component that is still referenced by an
        experiment must not be deleted, otherwise leaderboards/recomputes break.
        """
        stmt = select(func.count()).select_from(Experiment)
        if dataset_id:
            stmt = stmt.where(Experiment.dataset_id == dataset_id)
        if benchmark_id:
            stmt = stmt.where(Experiment.benchmark_id == benchmark_id)
        if prompt_id:
            stmt = stmt.where(Experiment.prompt_id == prompt_id)
        if model_id:
            stmt = stmt.where(Experiment.model_id == model_id)
        result = await self.session.execute(stmt)
        return int(result.scalar_one())

    async def set_running_if_not_running(self, experiment_id: str) -> bool:
        """Atomically flip status to 'running' iff it currently isn't.

        Returns True only if a row was actually changed (CAS), so concurrent
        runners can detect they lost the race and bail out.
        """
        stmt = (
            update(Experiment)
            .where(Experiment.id == experiment_id, Experiment.status != "running")
            .values(status="running", error=None)
        )
        result = await self.session.execute(stmt)
        await self.session.flush()
        return result.rowcount > 0

    async def finish_if_running(
        self, experiment_id: str, *, status: str, error: str | None = None
    ) -> bool:
        """Atomically advance status from 'running' to a terminal state.

        Returns True only if a row was actually changed. This is the mirror of
        `set_running_if_not_running`: the Persist phase must not blindly overwrite
        the terminal status, otherwise two concurrent runners (which both cleared
        the start-gate CAS under WAL) would each run delete+bulk_create and clobber
        each other's results. The loser sees rowcount==0 and discards its work.
        """
        stmt = (
            update(Experiment)
            .where(Experiment.id == experiment_id, Experiment.status == "running")
            .values(status=status, error=error)
        )
        result = await self.session.execute(stmt)
        await self.session.flush()
        return result.rowcount > 0


class ExperimentResultRepository(BaseRepository[ExperimentResult]):
    model = ExperimentResult

    async def list_by_experiment(
        self, experiment_id: str, *, offset: int = 0, limit: int = 1000
    ) -> Sequence[ExperimentResult]:
        stmt = (
            select(ExperimentResult)
            .where(ExperimentResult.experiment_id == experiment_id)
            .order_by(ExperimentResult.row_idx.asc())
            .offset(offset)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def bulk_create(self, rows: list[ExperimentResult]) -> None:
        self.session.add_all(rows)
        await self.session.flush()

    async def delete_by_experiment(self, experiment_id: str) -> None:
        from sqlalchemy import delete

        await self.session.execute(
            delete(ExperimentResult).where(
                ExperimentResult.experiment_id == experiment_id
            )
        )
        await self.session.flush()
