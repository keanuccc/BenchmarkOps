"""Tests for scheduled reports CRUD, run-now, and the scheduler sweep."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.core.database import AsyncSessionLocal
from app.models.project import Project
from app.models.scheduled_report import ScheduledReport
from app.services.report_scheduler import run_due_reports
from app.services.scheduled_report_service import (
    ScheduledReportService,
    next_run_at,
)


def test_next_run_at_cadences():
    now = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
    assert next_run_at("daily", now) == now + timedelta(days=1)
    assert next_run_at("weekly", now) == now + timedelta(days=7)
    assert next_run_at("monthly", now) == now + timedelta(days=30)


async def test_scheduled_report_crud_and_scheduler():
    async with AsyncSessionLocal() as session:
        project = Project(name="sched-p")
        session.add(project)
        await session.flush()

        service = ScheduledReportService(session)
        created = await service.create(
            __import__(
                "app.schemas.scheduled_report", fromlist=["ScheduledReportCreate"]
            ).ScheduledReportCreate(
                project_id=project.id,
                name="每日评测",
                experiment_ids=[],
                schedule="daily",
                format="md",
            )
        )
        assert created.next_run_at is not None

        listed = await service.list(project.id)
        assert len(listed) == 1

        updated = await service.update(
            created.id,
            __import__(
                "app.schemas.scheduled_report", fromlist=["ScheduledReportUpdate"]
            ).ScheduledReportUpdate(is_active=False),
        )
        assert updated.is_active is False
        await service.delete(created.id)
        await session.commit()


async def test_scheduler_sweep_runs_due_reports():
    async with AsyncSessionLocal() as session:
        project = Project(name="sched-due")
        session.add(project)
        await session.flush()
        due = ScheduledReport(
            project_id=project.id,
            name="due",
            experiment_ids=[],
            schedule="daily",
            format="md",
            is_active=True,
            next_run_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        )
        session.add(due)
        await session.commit()

    # No experiment_ids -> run_now raises; the sweep still advances the schedule
    # and records a failed status instead of crashing the loop.
    await run_due_reports()

    async with AsyncSessionLocal() as session:
        from app.repositories.scheduled_report import ScheduledReportRepository

        refreshed = await ScheduledReportRepository(session).get(due.id)
        assert refreshed is not None
        assert refreshed.last_status is not None
        assert refreshed.last_run_at is not None
        assert refreshed.next_run_at is not None
