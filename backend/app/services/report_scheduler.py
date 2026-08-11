"""Background scheduler for continuous (scheduled) reports.

A lightweight asyncio loop checks every minute for due scheduled reports and
generates them. Each run executes inside the owning organization's tenant
context so generated reports stay scoped to the organization.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from app.core.database import AsyncSessionLocal
from app.core.tenant import TenantContext, reset_tenant, set_tenant
from app.repositories.scheduled_report import ScheduledReportRepository
from app.services.scheduled_report_service import ScheduledReportService

logger = logging.getLogger(__name__)

_POLL_SECONDS = 60


async def run_due_reports() -> int:
    """Generate every due scheduled report; returns how many ran."""
    async with AsyncSessionLocal() as session:
        repo = ScheduledReportRepository(session)
        due = await repo.list_due(datetime.now(timezone.utc))
        pending = [(item.id, item.organization_id) for item in due]

    count = 0
    for report_id, org_id in pending:
        token = None
        if org_id:
            token = set_tenant(
                TenantContext(
                    organization_id=org_id,
                    role="owner",
                    key_id="scheduler",
                )
            )
        try:
            async with AsyncSessionLocal() as session:
                service = ScheduledReportService(session)
                await service.run_now(report_id)
            count += 1
            logger.info("scheduled report %s generated", report_id)
        except Exception:  # noqa: BLE001
            logger.exception("scheduled report %s failed", report_id)
        finally:
            if token is not None:
                try:
                    reset_tenant(token)
                except ValueError:
                    pass
    return count


async def scheduler_loop() -> None:
    """Run forever until cancelled; one due-report sweep per minute."""
    while True:
        try:
            await run_due_reports()
        except Exception:  # noqa: BLE001
            logger.exception("scheduled-report sweep failed")
        await asyncio.sleep(_POLL_SECONDS)
