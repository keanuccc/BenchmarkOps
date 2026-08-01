"""Project service — business logic for the Project module."""
from __future__ import annotations

from sqlalchemy import delete, func, select

from app.core.database import get_session
from app.core.exceptions import NotFoundError
from app.models.benchmark import Benchmark
from app.models.dataset import Dataset, DatasetRow
from app.models.experiment import Experiment, ExperimentResult
from app.models.project import Project
from app.models.prompt import Prompt
from app.models.report import Report
from app.repositories.project import ProjectRepository
from app.repositories.task import TaskRepository
from app.schemas.project import ProjectCreate, ProjectUpdate

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession


class ProjectService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = ProjectRepository(session)

    async def create(self, data: ProjectCreate) -> Project:
        obj = Project(name=data.name, description=data.description)
        return await self.repo.create(obj)

    async def get(self, project_id: str) -> Project:
        obj = await self.repo.get(project_id)
        if obj is None:
            raise NotFoundError(f"Project {project_id} not found")
        return obj

    async def list(
        self,
        *,
        status: str | None = None,
        q: str | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> list[Project]:
        stmt = select(Project)
        if status is not None:
            stmt = stmt.where(Project.status == status)
        if q:
            stmt = stmt.where(Project.name.ilike(f"%{q}%"))
        stmt = stmt.order_by(Project.created_at.desc())
        stmt = stmt.offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def count(
        self,
        *,
        status: str | None = None,
        q: str | None = None,
    ) -> int:
        stmt = select(func.count()).select_from(Project)
        if status:
            stmt = stmt.where(Project.status == status)
        if q:
            stmt = stmt.where(Project.name.ilike(f"%{q}%"))
        result = await self.session.execute(stmt)
        return int(result.scalar_one())

    async def update(self, project_id: str, data: ProjectUpdate) -> Project:
        obj = await self.get(project_id)
        payload = data.model_dump(exclude_unset=True)
        return await self.repo.update(obj, payload)

    async def archive(self, project_id: str) -> Project:
        obj = await self.get(project_id)
        return await self.repo.update(obj, {"status": "archived"})

    async def delete(self, project_id: str) -> None:
        obj = await self.get(project_id)

        # Cascade-delete everything owned by the project in one transaction so
        # a deleted project cannot leave orphaned datasets / experiments /
        # reports behind. Models are global (no project_id) and are untouched.
        experiment_ids = (
            await self.session.execute(
                select(Experiment.id).where(Experiment.project_id == project_id)
            )
        ).scalars().all()
        if experiment_ids:
            # Keep the task audit trail, but mark rows for deleted experiments.
            await TaskRepository(self.session).mark_experiment_deleted(
                list(experiment_ids)
            )
            await self.session.execute(
                delete(ExperimentResult).where(
                    ExperimentResult.experiment_id.in_(experiment_ids)
                )
            )
            await self.session.execute(
                delete(Experiment).where(Experiment.id.in_(experiment_ids))
            )

        dataset_ids = (
            await self.session.execute(
                select(Dataset.id).where(Dataset.project_id == project_id)
            )
        ).scalars().all()
        if dataset_ids:
            await self.session.execute(
                delete(DatasetRow).where(DatasetRow.dataset_id.in_(dataset_ids))
            )
            await self.session.execute(
                delete(Dataset).where(Dataset.id.in_(dataset_ids))
            )

        await self.session.execute(
            delete(Benchmark).where(Benchmark.project_id == project_id)
        )
        await self.session.execute(
            delete(Prompt).where(Prompt.project_id == project_id)
        )
        await self.session.execute(
            delete(Report).where(Report.project_id == project_id)
        )

        await self.repo.delete(obj)


def get_project_service(session: AsyncSession = Depends(get_session)) -> ProjectService:
    return ProjectService(session)
