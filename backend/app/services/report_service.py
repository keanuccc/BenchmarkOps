"""Business logic for the AI Report module.

Generates a structured Markdown report for one or more experiments. Prefers the
configured LLM provider when available, and falls back to a deterministic template
when no key is set or any provider call fails.
"""
from __future__ import annotations

from collections.abc import AsyncGenerator, Sequence

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_session
from app.core.exceptions import NotFoundError, ValidationError
from app.models.experiment import Experiment, ExperimentResult
from app.models.model import Model
from app.models.report import Report
from app.providers.registry import active_provider_name, get_provider
from app.report.generator import ai_report, build_context, template_report
from app.repositories.experiment import (
    ExperimentRepository,
    ExperimentResultRepository,
)
from app.repositories.report import ReportRepository
from app.schemas.report import ReportGenerateRequest

# Runtime default model slug used ONLY as a provider call argument when no other
# default is configured. This is a runtime model choice, not application config.
DEFAULT_REPORT_MODEL_ID = "openai/gpt-4o-mini"


class ReportService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.reports = ReportRepository(session)
        self.experiments = ExperimentRepository(session)
        self.results = ExperimentResultRepository(session)

    async def generate(self, req: ReportGenerateRequest) -> Report:
        if not req.experiment_ids:
            raise ValidationError("At least one experiment_id is required")

        experiments: list[Experiment] = []
        for eid in req.experiment_ids:
            exp = await self.experiments.get(eid)
            if exp is None:
                raise ValidationError(f"Experiment '{eid}' not found")
            experiments.append(exp)
        if not experiments:
            raise ValidationError("No valid experiments found")

        results_by_exp: dict[str, list[ExperimentResult]] = {}
        for exp in experiments:
            results_by_exp[exp.id] = list(
                await self.results.list_by_experiment(exp.id)
            )

        model_names = await self._resolve_model_names(experiments)
        context = build_context(experiments, results_by_exp, model_names)

        generated_by = "template"
        try:
            if settings.provider_enabled:
                provider = get_provider()
                model_id = getattr(settings, "report_model_id", None) or DEFAULT_REPORT_MODEL_ID
                content_markdown, sections = await ai_report(context, provider, model_id)
                generated_by = active_provider_name()
            else:
                raise RuntimeError("provider disabled")
        except Exception:
            # Deterministic fallback — always works with zero LLM.
            content_markdown, sections = template_report(context)

        title = req.title or f"AI Report · {len(experiments)} experiment(s)"

        report = Report(
            project_id=req.project_id,
            title=title,
            experiment_ids=req.experiment_ids,
            content_markdown=content_markdown,
            sections=sections,
            generated_by=generated_by,
        )
        return await self.reports.create(report)

    async def _resolve_model_names(
        self, experiments: list[Experiment]
    ) -> dict[str, str]:
        """Map each Experiment.model_id to a human-readable Model.name (cached)."""
        names: dict[str, str] = {}
        seen: set[str] = set()
        for exp in experiments:
            if exp.model_id in seen:
                continue
            seen.add(exp.model_id)
            model = await self.session.get(Model, exp.model_id)
            if model is not None:
                names[exp.model_id] = model.name
        return names

    async def get(self, report_id: str) -> Report:
        report = await self.reports.get(report_id)
        if report is None:
            raise NotFoundError(f"Report {report_id} not found")
        return report

    async def list(
        self, project_id: str, *, offset: int = 0, limit: int = 100
    ) -> Sequence[Report]:
        return await self.reports.list(
            offset=offset, limit=limit, filters={"project_id": project_id}
        )

    async def delete(self, report_id: str) -> None:
        report = await self.get(report_id)
        await self.reports.delete(report)


async def get_report_service(
    session: AsyncSession = Depends(get_session),
) -> AsyncGenerator[ReportService, None]:
    yield ReportService(session)
