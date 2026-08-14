"""Business logic for the AI Report module.

Generates a structured Markdown report for one or more experiments. Prefers the
configured LLM provider when available, and falls back to a deterministic template
when no key is set or any provider call fails.
"""
from __future__ import annotations

from collections.abc import AsyncGenerator, Sequence

from fastapi import Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_session
from app.core.exceptions import NotFoundError, ValidationError
from app.core.tenant import get_tenant
from app.models.dataset import Dataset
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

# Runtime default model slugs used ONLY as a provider call argument when no
# other default is configured. The slug must be valid on the gateway actually
# serving the request: DeepSeek serves deepseek-chat directly, OpenRouter
# exposes openai/gpt-4o-mini, and Qiniu is verified to serve
# deepseek/deepseek-v4-flash and deepseek-v3.
DEEPSEEK_REPORT_MODEL_ID = "deepseek-chat"
DEFAULT_REPORT_MODEL_ID = "openai/gpt-4o-mini"
QINIU_REPORT_MODEL_ID = "deepseek/deepseek-v4-flash"


def resolve_report_model_id(provider_name: str | None = None) -> str:
    """Model id used for AI-generated reports (configurable via REPORT_MODEL_ID)."""
    if settings.report_model_id:
        return settings.report_model_id
    provider = (
        provider_name or settings.report_provider or settings.default_provider
    ).lower()
    if provider == "deepseek":
        return DEEPSEEK_REPORT_MODEL_ID
    if provider == "qiniu":
        return QINIU_REPORT_MODEL_ID
    return DEFAULT_REPORT_MODEL_ID


class ReportService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.reports = ReportRepository(session)
        self.experiments = ExperimentRepository(session)
        self.results = ExperimentResultRepository(session)

    def _org_id(self) -> str | None:
        tenant = get_tenant()
        return tenant.organization_id if tenant is not None else None

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

        sensitive_by_exp: dict[str, set[str]] = {}
        for exp in experiments:
            result = await self.session.execute(
                select(Dataset).where(Dataset.id == exp.dataset_id)
            )
            dataset = result.scalar_one_or_none()
            sensitive_by_exp[exp.id] = (
                set((dataset.contract or {}).get("sensitive_fields", []) or [])
                if dataset is not None
                else set()
            )

        model_names = await self._resolve_model_names(experiments)
        context = build_context(
            experiments,
            results_by_exp,
            model_names,
            sensitive_by_exp=sensitive_by_exp,
        )

        generated_by = "template"
        try:
            if settings.provider_enabled:
                # Prefer an explicit REPORT_PROVIDER, then the active real gateway
                # (default first, then any other configured key). Never generate a
                # fake report through Mock: if no real provider has a key, fall back
                # to the deterministic template below.
                provider_name = settings.report_provider or active_provider_name()
                if provider_name == "mock":
                    raise RuntimeError("no real provider configured for report")
                provider = get_provider(provider_name)
                model_id = resolve_report_model_id(provider_name)
                content_markdown, sections = await ai_report(context, provider, model_id)
                generated_by = getattr(provider, "name", None) or active_provider_name()
            else:
                raise RuntimeError("provider disabled")
        except Exception:
            # Deterministic fallback — always works with zero LLM.
            content_markdown, sections = template_report(context)

        title = req.title or f"AI 评测报告 · {len(experiments)} 个实验"

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
        self,
        project_id: str,
        *,
        q: str | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> Sequence[Report]:
        stmt = select(Report).where(Report.project_id == project_id)
        org_id = self._org_id()
        if org_id is not None:
            stmt = stmt.where(Report.organization_id == org_id)
        if q:
            stmt = stmt.where(Report.title.ilike(f"%{q}%"))
        stmt = stmt.order_by(Report.created_at.desc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def count(self, project_id: str, *, q: str | None = None) -> int:
        stmt = (
            select(func.count())
            .select_from(Report)
            .where(Report.project_id == project_id)
        )
        org_id = self._org_id()
        if org_id is not None:
            stmt = stmt.where(Report.organization_id == org_id)
        if q:
            stmt = stmt.where(Report.title.ilike(f"%{q}%"))
        result = await self.session.execute(stmt)
        return int(result.scalar_one())

    async def delete(self, report_id: str) -> None:
        report = await self.get(report_id)
        await self.reports.delete(report)


async def get_report_service(
    session: AsyncSession = Depends(get_session),
) -> AsyncGenerator[ReportService, None]:
    yield ReportService(session)
