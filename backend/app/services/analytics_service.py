"""Read-only analytics aggregation over existing Experiment data.

All queries run against the experiments / experiment_results / models tables.
No mutations, no new tables.
"""
from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi import Depends

from app.core.database import get_session
from app.core.exceptions import ValidationError
from app.models.experiment import Experiment, ExperimentResult
from app.models.model import Model
from app.schemas.analytics import (
    ComparisonResponse,
    FailureCase,
    LeaderboardEntry,
    ProjectAnalyticsSummary,
    TrendPoint,
)


class AnalyticsService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self._model_cache: dict[str, Model | None] = {}

    async def _model_name(self, model_id: str) -> str:
        if model_id not in self._model_cache:
            model = await self.session.get(Model, model_id)
            self._model_cache[model_id] = model
        model = self._model_cache[model_id]
        return model.name if model is not None else model_id

    async def leaderboard(
        self,
        project_id: str | None = None,
        benchmark_id: str | None = None,
        limit: int = 50,
    ) -> list[LeaderboardEntry]:
        stmt = select(Experiment).where(Experiment.status == "completed")
        if project_id is not None:
            stmt = stmt.where(Experiment.project_id == project_id)
        if benchmark_id is not None:
            stmt = stmt.where(Experiment.benchmark_id == benchmark_id)
        result = await self.session.execute(stmt)
        experiments: Sequence[Experiment] = result.scalars().all()

        entries: list[LeaderboardEntry] = []
        for exp in experiments:
            metrics = exp.metrics or {}
            # Prefer the materialized accuracy column for consistency with the
            # ORDER BY below, but fall back to the metrics blob for parity.
            accuracy = exp.accuracy if exp.accuracy else metrics.get("accuracy", 0.0)
            entries.append(
                LeaderboardEntry(
                    experiment_id=exp.id,
                    experiment_name=exp.name,
                    model_id=exp.model_id,
                    model_name=await self._model_name(exp.model_id),
                    accuracy=accuracy,
                    avg_latency_ms=metrics.get("avg_latency_ms", 0.0),
                    total_cost=float(exp.total_cost),
                    total_tokens=int(exp.total_tokens),
                    rows_total=int(metrics.get("rows_total", 0)),
                    status=exp.status,
                )
            )

        entries.sort(key=lambda e: (-e.accuracy, e.total_cost))
        return entries[:limit]

    async def compare(self, experiment_ids: list[str]) -> ComparisonResponse:
        valid = [eid for eid in experiment_ids if eid]
        if len(valid) < 2:
            raise ValidationError("compare requires at least 2 experiment ids")

        experiments: list[Experiment] = []
        for eid in valid:
            exp = await self.session.get(Experiment, eid)
            if exp is not None:
                experiments.append(exp)

        if len(experiments) < 2:
            raise ValidationError(
                "compare requires at least 2 resolvable experiments"
            )

        exp_list: list[dict] = []
        dimensions: dict = {
            "labels": [],
            "accuracy": [],
            "avg_latency_ms": [],
            "total_cost": [],
            "total_tokens": [],
        }

        for exp in experiments:
            metrics = exp.metrics or {}
            exp_list.append(
                {
                    "id": exp.id,
                    "name": exp.name,
                    "model_name": await self._model_name(exp.model_id),
                    "metrics": metrics,
                    "total_cost": float(exp.total_cost),
                    "total_tokens": int(exp.total_tokens),
                    "runtime_ms": int(exp.runtime_ms),
                }
            )
            dimensions["labels"].append(exp.name)
            dimensions["accuracy"].append(metrics.get("accuracy", 0.0))
            dimensions["avg_latency_ms"].append(metrics.get("avg_latency_ms", 0.0))
            dimensions["total_cost"].append(float(exp.total_cost))
            dimensions["total_tokens"].append(int(exp.total_tokens))

        return ComparisonResponse(experiments=exp_list, dimensions=dimensions)

    async def failure_cases(
        self, experiment_id: str, limit: int = 50
    ) -> list[FailureCase]:
        stmt = select(ExperimentResult).where(
            ExperimentResult.experiment_id == experiment_id
        )
        result = await self.session.execute(stmt)
        rows: Sequence[ExperimentResult] = result.scalars().all()

        failures = [
            r for r in rows if (r.score is not None and r.score < 1.0) or r.error
        ]
        failures.sort(key=lambda r: r.score if r.score is not None else 0.0)

        return [
            FailureCase(
                experiment_id=r.experiment_id,
                row_idx=r.row_idx,
                input=r.input,
                expected=r.expected,
                output=r.output,
                score=float(r.score) if r.score is not None else 0.0,
                error=r.error,
            )
            for r in failures[:limit]
        ]

    async def trend(
        self,
        project_id: str,
        benchmark_id: str | None = None,
        limit: int = 50,
    ) -> list[TrendPoint]:
        stmt = (
            select(Experiment)
            .where(Experiment.status == "completed")
            .where(Experiment.project_id == project_id)
        )
        if benchmark_id is not None:
            stmt = stmt.where(Experiment.benchmark_id == benchmark_id)
        stmt = stmt.order_by(Experiment.created_at.asc())
        result = await self.session.execute(stmt)
        experiments: Sequence[Experiment] = result.scalars().all()

        points = [
            TrendPoint(
                created_at=exp.created_at.isoformat() if exp.created_at else "",
                accuracy=(exp.metrics or {}).get("accuracy", 0.0),
                total_cost=float(exp.total_cost),
                experiment_name=exp.name,
            )
            for exp in experiments
        ]
        return points[:limit]

    async def project_summary(self, project_id: str) -> ProjectAnalyticsSummary:
        count_stmt = select(Experiment).where(
            Experiment.project_id == project_id
        )
        result = await self.session.execute(count_stmt)
        all_exp: Sequence[Experiment] = result.scalars().all()

        completed = [e for e in all_exp if e.status == "completed"]

        accuracies = [(e.metrics or {}).get("accuracy", 0.0) for e in completed]
        avg_accuracy = sum(accuracies) / len(accuracies) if accuracies else 0.0

        total_cost = sum(float(e.total_cost) for e in all_exp)
        total_tokens = sum(int(e.total_tokens) for e in all_exp)

        best_exp = None
        best_accuracy = 0.0
        for e in completed:
            acc = (e.metrics or {}).get("accuracy", 0.0)
            if acc > best_accuracy:
                best_accuracy = acc
                best_exp = e

        return ProjectAnalyticsSummary(
            project_id=project_id,
            experiment_count=len(all_exp),
            completed_count=len(completed),
            avg_accuracy=avg_accuracy,
            total_cost=total_cost,
            total_tokens=total_tokens,
            best_experiment_id=best_exp.id if best_exp is not None else None,
            best_accuracy=best_accuracy,
        )


def get_analytics_service(
    session: AsyncSession = Depends(get_session),
) -> AnalyticsService:
    return AnalyticsService(session)
