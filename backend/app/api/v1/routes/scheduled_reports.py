"""Scheduled (continuous) report endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.core.security import require_auth
from app.schemas.scheduled_report import (
    ScheduledReportCreate,
    ScheduledReportRead,
    ScheduledReportUpdate,
)
from app.services.scheduled_report_service import (
    ScheduledReportService,
    get_scheduled_report_service,
)

router = APIRouter(prefix="/scheduled-reports", tags=["scheduled-reports"])


@router.post("/", response_model=ScheduledReportRead, status_code=201)
async def create_scheduled_report(
    data: ScheduledReportCreate,
    service: ScheduledReportService = Depends(get_scheduled_report_service),
    _: None = Depends(require_auth),
):
    return await service.create(data)


@router.get("/", response_model=list[ScheduledReportRead])
async def list_scheduled_reports(
    project_id: str,
    service: ScheduledReportService = Depends(get_scheduled_report_service),
):
    return await service.list(project_id)


@router.get("/{report_id}", response_model=ScheduledReportRead)
async def get_scheduled_report(
    report_id: str,
    service: ScheduledReportService = Depends(get_scheduled_report_service),
):
    return await service.get(report_id)


@router.patch("/{report_id}", response_model=ScheduledReportRead)
async def update_scheduled_report(
    report_id: str,
    data: ScheduledReportUpdate,
    service: ScheduledReportService = Depends(get_scheduled_report_service),
    _: None = Depends(require_auth),
):
    return await service.update(report_id, data)


@router.delete("/{report_id}", status_code=204, response_model=None)
async def delete_scheduled_report(
    report_id: str,
    service: ScheduledReportService = Depends(get_scheduled_report_service),
    _: None = Depends(require_auth),
):
    await service.delete(report_id)


@router.post("/{report_id}/run", response_model=ScheduledReportRead)
async def run_scheduled_report_now(
    report_id: str,
    service: ScheduledReportService = Depends(get_scheduled_report_service),
    _: None = Depends(require_auth),
):
    return await service.run_now(report_id)
