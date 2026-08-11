"""Business logic for scheduled (continuous) reports."""
from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta, timezone

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.core.exceptions import NotFoundError, ValidationError
from app.core.tenant import get_tenant
from app.models.scheduled_report import ScheduledReport
from app.repositories.project import ProjectRepository
from app.repositories.scheduled_report import ScheduledReportRepository
from app.schemas.report import ReportGenerateRequest
from app.schemas.scheduled_report import (
    ScheduledReportCreate,
    ScheduledReportUpdate,
)


def next_run_at(schedule: str, now: datetime | None = None) -> datetime:
    """Compute the next run time for a simple daily/weekly/monthly cadence."""
    base = now or datetime.now(timezone.utc)
    if schedule == "weekly":
        return base + timedelta(days=7)
    if schedule == "monthly":
        return base + timedelta(days=30)
    return base + timedelta(days=1)


class ScheduledReportService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = ScheduledReportRepository(session)

    def _org_id(self) -> str | None:
        tenant = get_tenant()
        return tenant.organization_id if tenant is not None else None

    async def create(self, data: ScheduledReportCreate) -> ScheduledReport:
        if await ProjectRepository(self.session).get(data.project_id) is None:
            raise ValidationError(f"Project '{data.project_id}' does not exist")
        obj = ScheduledReport(
            project_id=data.project_id,
            name=data.name,
            experiment_ids=data.experiment_ids,
            schedule=data.schedule,
            format=data.format,
            next_run_at=next_run_at(data.schedule),
        )
        return await self.repo.create(obj)

    async def get(self, report_id: str) -> ScheduledReport:
        obj = await self.repo.get(report_id)
        if obj is None:
            raise NotFoundError(f"Scheduled report {report_id} not found")
        return obj

    async def list(
        self, project_id: str, *, limit: int = 100
    ) -> Sequence[ScheduledReport]:
        return await self.repo.list(
            filters={"project_id": project_id}, limit=limit
        )

    async def update(
        self, report_id: str, data: ScheduledReportUpdate
    ) -> ScheduledReport:
        obj = await self.get(report_id)
        payload = data.model_dump(exclude_unset=True)
        if "schedule" in payload:
            obj.schedule = payload["schedule"]
            obj.next_run_at = next_run_at(payload["schedule"])
            payload.pop("schedule", None)
        return await self.repo.update(obj, payload)

    async def delete(self, report_id: str) -> None:
        obj = await self.get(report_id)
        await self.repo.delete(obj)

    async def run_now(self, report_id: str) -> ScheduledReport:
        """Generate the report immediately (used by the scheduler and API)."""
        obj = await self.get(report_id)
        from app.services.report_service import ReportService

        service = ReportService(self.session)
        req = ReportGenerateRequest(
            project_id=obj.project_id,
            experiment_ids=list(obj.experiment_ids),
            title=f"{obj.name} ({datetime.now(timezone.utc).strftime('%Y-%m-%d')})",
        )
        try:
            if not obj.experiment_ids:
                raise ValidationError("Scheduled report has no experiment_ids")
            await service.generate(req)
            obj.last_status = "success"
        except Exception as exc:  # noqa: BLE001
            obj.last_status = f"failed: {type(exc).__name__}"
        obj.last_run_at = datetime.now(timezone.utc)
        obj.next_run_at = next_run_at(obj.schedule)
        await self.session.commit()
        await self.session.refresh(obj)
        return obj


def get_scheduled_report_service(
    session: AsyncSession = Depends(get_session),
) -> ScheduledReportService:
    return ScheduledReportService(session)
