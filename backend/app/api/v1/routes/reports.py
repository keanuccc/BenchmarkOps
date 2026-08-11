"""AI Report API: generate, list, fetch, export (md/html/pdf), and delete."""
from __future__ import annotations

import logging
import re

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import HTMLResponse, PlainTextResponse, StreamingResponse

from app.core.security import require_auth
from app.report.exporter import markdown_to_html, markdown_to_pdf
from app.schemas.common import ListResponse
from app.schemas.report import ReportGenerateRequest, ReportRead
from app.services.report_service import ReportService, get_report_service

router = APIRouter(prefix="/reports", tags=["reports"])

logger = logging.getLogger(__name__)


@router.post("/generate", response_model=ReportRead, status_code=status.HTTP_201_CREATED)
async def generate_report(
    payload: ReportGenerateRequest,
    service: ReportService = Depends(get_report_service),
    _: None = Depends(require_auth),
):
    return await service.generate(payload)


@router.get("/", response_model=ListResponse[ReportRead])
async def list_reports(
    project_id: str,
    q: str | None = None,
    offset: int = 0,
    limit: int = 100,
    service: ReportService = Depends(get_report_service),
):
    items = await service.list(project_id, q=q, offset=offset, limit=limit)
    total = await service.count(project_id, q=q)
    return ListResponse[ReportRead](items=items, total=total)


@router.get("/{report_id}", response_model=ReportRead)
async def get_report(
    report_id: str,
    service: ReportService = Depends(get_report_service),
):
    return await service.get(report_id)


@router.get("/{report_id}/export")
async def export_report(
    report_id: str,
    format: str = "md",
    service: ReportService = Depends(get_report_service),
):
    """Export a report as Markdown (default), styled HTML, or PDF."""
    report = await service.get(report_id)
    raw = report.title or str(report.id)
    base = re.sub(r"[^A-Za-z0-9_.-]", "_", raw)
    if format == "html":
        return HTMLResponse(
            markdown_to_html(report.content_markdown or "", title=raw),
            headers={"Content-Disposition": f'attachment; filename="{base}.html"'},
        )
    headers = {"Content-Disposition": f'attachment; filename="{base}.md"'}
    return PlainTextResponse(
        report.content_markdown or "", media_type="text/markdown", headers=headers
    )


@router.get("/{report_id}/export/pdf")
async def export_report_pdf(
    report_id: str,
    service: ReportService = Depends(get_report_service),
):
    """Export report as PDF via reportlab (pure Python, no native deps)."""
    report = await service.get(report_id)
    title = report.title or str(report.id)
    pdf_filename = re.sub(r"[^A-Za-z0-9_.-]", "_", title) + ".pdf"
    try:
        pdf_bytes = markdown_to_pdf(report.content_markdown or "", title=title)
    except Exception:
        logger.exception("PDF export failed for report %s", report_id)
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="PDF export failed",
        )
    headers = {"Content-Disposition": f'attachment; filename="{pdf_filename}"'}
    return StreamingResponse(
        iter([pdf_bytes]),
        media_type="application/pdf",
        headers=headers,
    )


@router.delete("/{report_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_report(
    report_id: str,
    service: ReportService = Depends(get_report_service),
    _: None = Depends(require_auth),
):
    await service.delete(report_id)
