"""AI Report API — generate, list, fetch, export, and delete reports."""
from __future__ import annotations

from fastapi import APIRouter, Depends, status
from fastapi.responses import PlainTextResponse

from app.core.security import require_auth
from app.schemas.report import ReportGenerateRequest, ReportRead
from app.services.report_service import ReportService, get_report_service

router = APIRouter(prefix="/reports", tags=["reports"])


@router.post("/generate", response_model=ReportRead, status_code=status.HTTP_201_CREATED)
async def generate_report(
    payload: ReportGenerateRequest,
    service: ReportService = Depends(get_report_service),
    _: None = Depends(require_auth),
):
    return await service.generate(payload)


@router.get("/", response_model=list[ReportRead])
async def list_reports(
    project_id: str,
    offset: int = 0,
    limit: int = 100,
    service: ReportService = Depends(get_report_service),
):
    return await service.list(project_id, offset=offset, limit=limit)


@router.get("/{report_id}", response_model=ReportRead)
async def get_report(
    report_id: str,
    service: ReportService = Depends(get_report_service),
):
    return await service.get(report_id)


@router.get("/{report_id}/export")
async def export_report(
    report_id: str,
    service: ReportService = Depends(get_report_service),
):
    import re

    report = await service.get(report_id)
    # HTTP headers must be latin-1; use an ASCII-safe filename. The real
    # (possibly non-ASCII) title is applied client-side via the <a download>
    # attribute, so we only emit an ASCII `filename` here.
    raw = report.title or str(report.id)
    ascii_name = re.sub(r"[^A-Za-z0-9_.-]", "_", raw) + ".md"
    headers = {"Content-Disposition": f'attachment; filename="{ascii_name}"'}
    return PlainTextResponse(
        report.content_markdown or "", media_type="text/markdown", headers=headers
    )


@router.delete("/{report_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_report(
    report_id: str,
    service: ReportService = Depends(get_report_service),
    _: None = Depends(require_auth),
):
    await service.delete(report_id)
