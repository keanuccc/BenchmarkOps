"""AI Report API — generate, list, fetch, export (md/pdf), and delete reports."""
from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import PlainTextResponse, StreamingResponse

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
    report = await service.get(report_id)
    raw = report.title or str(report.id)
    ascii_name = re.sub(r"[^A-Za-z0-9_.-]", "_", raw) + ".md"
    headers = {"Content-Disposition": f'attachment; filename="{ascii_name}"'}
    return PlainTextResponse(
        report.content_markdown or "", media_type="text/markdown", headers=headers
    )


@router.get("/{report_id}/export/pdf")
async def export_report_pdf(
    report_id: str,
    service: ReportService = Depends(get_report_service),
):
    """Export report as PDF via weasyprint. Falls back to 501 if unavailable."""
    try:
        from weasyprint import HTML
    except ImportError:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="PDF export requires weasyprint",
        )

    report = await service.get(report_id)
    content = report.content_markdown or ""
    title = report.title or str(report.id)
    pdf_filename = title.replace(" ", "_") + ".pdf"

    # Markdown → HTML using Python markdown library
    try:
        import markdown
        html_body = markdown.markdown(
            content,
            extensions=["tables", "fenced_code", "codehilite", "toc"],
        )
    except ImportError:
        # Fallback: basic HTML wrapping
        html_body = "<p>" + content.replace("\n\n", "</p><p>").replace("\n", "<br/>") + "</p>"

    full_html = f"""
    <html>
    <head>
        <meta charset="utf-8"/>
        <style>
            body {{ font-family: sans-serif; padding: 2em; line-height: 1.6; }}
            table {{ border-collapse: collapse; width: 100%; margin: 1em 0; }}
            th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
            th {{ background-color: #f5f5f5; }}
            pre {{ background: #f5f5f5; padding: 1em; overflow-x: auto; }}
            code {{ background: #f5f5f5; padding: 2px 4px; border-radius: 3px; }}
        </style>
    </head>
    <body>{html_body}</body>
    </html>
    """

    try:
        pdf_bytes = HTML(string=full_html).write_pdf()
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="PDF export requires weasyprint",
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
