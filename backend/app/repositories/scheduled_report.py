"""Repository for scheduled reports."""
from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import select

from app.models.scheduled_report import ScheduledReport
from app.repositories.base import BaseRepository


class ScheduledReportRepository(BaseRepository[ScheduledReport]):
    model = ScheduledReport

    async def list_due(self, now: datetime) -> Sequence[ScheduledReport]:
        stmt = (
            select(ScheduledReport)
            .where(ScheduledReport.is_active.is_(True))
            .where(ScheduledReport.next_run_at.is_not(None))
            .where(ScheduledReport.next_run_at <= now)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()
