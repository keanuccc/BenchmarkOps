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
from app.core.tenant import get_tenant
from app.evaluation.statistics import (
    bootstrap_ci,
    mcnemar_p_value,
    paired_bootstrap_test,
)
from app.models.experiment import Experiment, ExperimentResult
from app.models.dataset import Dataset
from app.models.model import Model
from app.services.redaction import redact_text, redact_values
from app.schemas.analytics import (
    ComparisonResponse,
    CompareFailureCase,
    CompareFailuresResponse,
    FailureCase,
    LeaderboardEntry,
    ModelRoutingEntry,
    ProjectAnalyticsSummary,
    SignificanceResponse,
    SubgroupEntry,
    SubgroupResponse,
    TrendPoint,
)


def _normalized_metrics(metrics: dict | None) -> dict[str, float | int]:
    """Derive one consistent coverage/failure view for old and new runs."""
    source = metrics or {}
    rows_total = int(source.get("rows_total", 0) or 0)
    dataset_rows_total = int(source.get("dataset_rows_total") or rows_total)
    if "rows_scored" in source:
        rows_scored = int(source.get("rows_scored") or 0)
    elif "coverage" in source:
        rows_scored = round(dataset_rows_total * float(source.get("coverage") or 0.0))
    else:
        rows_scored = rows_total
    if "rows_failed" in source:
        rows_failed = int(source.get("rows_failed") or 0)
    elif "failure_rate" in source:
        rows_failed = round(dataset_rows_total * float(source.get("failure_rate") or 0.0))
    else:
        rows_failed = max(rows_total - rows_scored, 0)
    return {
        "rows_total": rows_total,
        "dataset_rows_total": dataset_rows_total,
        "rows_scored": rows_scored,
        "rows_failed": rows_failed,
        "coverage": rows_scored / dataset_rows_total if dataset_rows_total else 0.0,
        "failure_rate": rows_failed / dataset_rows_total if dataset_rows_total else 0.0,
    }


class AnalyticsService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self._model_cache: dict[str, Model | None] = {}

    def _org_id(self) -> str | None:
        tenant = get_tenant()
        return tenant.organization_id if tenant is not None else None

    async def _get_experiment(self, experiment_id: str) -> Experiment | None:
        org_id = self._org_id()
        if org_id is None:
            return await self.session.get(Experiment, experiment_id)
        result = await self.session.execute(
            select(Experiment).where(
                Experiment.id == experiment_id,
                Experiment.organization_id == org_id,
            )
        )
        return result.scalar_one_or_none()

    async def _sensitive_fields(self, experiment_id: str) -> set[str]:
        exp = await self._get_experiment(experiment_id)
        if exp is None:
            return set()
        result = await self.session.execute(
            select(Dataset).where(Dataset.id == exp.dataset_id)
        )
        dataset = result.scalar_one_or_none()
        if dataset is None:
            return set()
        return set((dataset.contract or {}).get("sensitive_fields", []) or [])

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
        stmt = select(Experiment).where(Experiment.status.in_(("completed", "partial")))
        org_id = self._org_id()
        if org_id is not None:
            stmt = stmt.where(Experiment.organization_id == org_id)
        if project_id is not None:
            stmt = stmt.where(Experiment.project_id == project_id)
        if benchmark_id is not None:
            stmt = stmt.where(Experiment.benchmark_id == benchmark_id)
        result = await self.session.execute(stmt)
        experiments: Sequence[Experiment] = result.scalars().all()

        entries: list[LeaderboardEntry] = []
        for exp in experiments:
            metrics = exp.metrics or {}
            normalized = _normalized_metrics(metrics)
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
                    rows_total=int(normalized["rows_total"]),
                    dataset_rows_total=int(normalized["dataset_rows_total"]),
                    coverage=float(normalized["coverage"]),
                    failure_rate=float(normalized["failure_rate"]),
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
            exp = await self._get_experiment(eid)
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
            "coverage": [],
            "failure_rate": [],
        }

        for exp in experiments:
            metrics = exp.metrics or {}
            normalized = _normalized_metrics(metrics)
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
            dimensions["coverage"].append(float(normalized["coverage"]))
            dimensions["failure_rate"].append(float(normalized["failure_rate"]))

        return ComparisonResponse(experiments=exp_list, dimensions=dimensions)

    async def failure_cases(
        self, experiment_id: str, limit: int = 50
    ) -> list[FailureCase]:
        exp = await self._get_experiment(experiment_id)
        if exp is None:
            return []
        stmt = select(ExperimentResult).where(
            ExperimentResult.experiment_id == experiment_id
        )
        result = await self.session.execute(stmt)
        rows: Sequence[ExperimentResult] = result.scalars().all()

        failures = [
            r for r in rows if (r.score is not None and r.score < 1.0) or r.error
        ]
        failures.sort(key=lambda r: r.score if r.score is not None else 0.0)
        sensitive = await self._sensitive_fields(experiment_id)

        return [
            FailureCase(
                experiment_id=r.experiment_id,
                row_idx=r.row_idx,
                input=redact_values(r.input, sensitive),
                expected=redact_values(r.expected, sensitive) if r.expected else None,
                output=redact_text(r.output or ""),
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
            .where(Experiment.status.in_(("completed", "partial")))
            .where(Experiment.project_id == project_id)
        )
        org_id = self._org_id()
        if org_id is not None:
            stmt = stmt.where(Experiment.organization_id == org_id)
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
                coverage=float(_normalized_metrics(exp.metrics)["coverage"]),
                failure_rate=float(_normalized_metrics(exp.metrics)["failure_rate"]),
            )
            for exp in experiments
        ]
        return points[:limit]

    async def project_summary(self, project_id: str) -> ProjectAnalyticsSummary:
        count_stmt = select(Experiment).where(
            Experiment.project_id == project_id
        )
        org_id = self._org_id()
        if org_id is not None:
            count_stmt = count_stmt.where(Experiment.organization_id == org_id)
        result = await self.session.execute(count_stmt)
        all_exp: Sequence[Experiment] = result.scalars().all()

        completed = [e for e in all_exp if e.status in ("completed", "partial")]

        accuracies = [(_normalized_metrics(e.metrics), (e.metrics or {}).get("accuracy", 0.0)) for e in completed]
        avg_accuracy = sum(accuracy for _, accuracy in accuracies) / len(accuracies) if accuracies else 0.0

        total_cost = sum(float(e.total_cost) for e in all_exp)
        total_tokens = sum(int(e.total_tokens) for e in all_exp)

        dataset_rows_total = 0
        rows_scored = 0
        rows_failed = 0
        for experiment in completed:
            normalized = _normalized_metrics(experiment.metrics)
            dataset_rows_total += int(normalized["dataset_rows_total"])
            rows_scored += int(normalized["rows_scored"])
            rows_failed += int(normalized["rows_failed"])

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
            coverage=rows_scored / dataset_rows_total if dataset_rows_total else 0.0,
            failure_rate=rows_failed / dataset_rows_total if dataset_rows_total else 0.0,
        )

    async def subgroups(
        self, experiment_id: str, group_field: str
    ) -> SubgroupResponse:
        """Break one experiment's results down by a dataset input field."""
        if not group_field:
            raise ValidationError("group_field is required")
        exp = await self._get_experiment(experiment_id)
        if exp is None:
            raise ValidationError(f"Experiment '{experiment_id}' not found")
        result = await self.session.execute(
            select(ExperimentResult).where(
                ExperimentResult.experiment_id == experiment_id
            )
        )
        rows: Sequence[ExperimentResult] = result.scalars().all()
        buckets: dict[str, list[ExperimentResult]] = {}
        for row in rows:
            raw_input = row.input or {}
            metadata = raw_input.get("_metadata") or {}
            value = raw_input.get(group_field, metadata.get(group_field))
            key = str(value).strip() if value not in (None, "") else "(未标注)"
            buckets.setdefault(key, []).append(row)
        groups = []
        for key, items in sorted(buckets.items(), key=lambda kv: -len(kv[1])):
            scores = [float(r.score or 0.0) for r in items if r.error is None]
            errors = [r for r in items if r.error]
            groups.append(
                SubgroupEntry(
                    group=key,
                    row_count=len(items),
                    avg_score=sum(scores) / len(scores) if scores else 0.0,
                    pass_count=sum(1 for s in scores if s >= 1.0),
                    fail_count=sum(1 for s in scores if s < 1.0),
                    error_count=len(errors),
                )
            )
        return SubgroupResponse(
            experiment_id=experiment_id,
            group_field=group_field,
            total_rows=len(rows),
            groups=groups,
        )

    async def compare_failures(
        self, experiment_a: str, experiment_b: str
    ) -> CompareFailuresResponse:
        """Diff the per-row outcomes of two experiments.

        Returns three buckets: wrong only in A, wrong only in B, wrong in both.
        """
        if experiment_a == experiment_b:
            raise ValidationError("experiment_ids must differ")
        exp_a = await self._get_experiment(experiment_a)
        exp_b = await self._get_experiment(experiment_b)
        if exp_a is None or exp_b is None:
            raise ValidationError("Both experiments must exist")

        async def _rows(eid: str) -> dict[int, ExperimentResult]:
            result = await self.session.execute(
                select(ExperimentResult).where(
                    ExperimentResult.experiment_id == eid
                )
            )
            return {r.row_idx: r for r in result.scalars().all()}

        rows_a = await _rows(experiment_a)
        rows_b = await _rows(experiment_b)
        common = sorted(set(rows_a) & set(rows_b))
        sensitive = await self._sensitive_fields(experiment_a)

        a_only_wrong: list[CompareFailureCase] = []
        b_only_wrong: list[CompareFailureCase] = []
        both_wrong: list[CompareFailureCase] = []
        for idx in common:
            ra, rb = rows_a[idx], rows_b[idx]
            a_ok = ra.error is None and float(ra.score or 0.0) >= 1.0
            b_ok = rb.error is None and float(rb.score or 0.0) >= 1.0
            if a_ok and b_ok:
                continue
            case = CompareFailureCase(
                row_idx=idx,
                input=redact_values(ra.input or {}, sensitive),
                expected=redact_values(ra.expected, sensitive) if ra.expected else None,
                a_output=redact_text(ra.output or ""),
                a_score=float(ra.score or 0.0),
                b_output=redact_text(rb.output or ""),
                b_score=float(rb.score or 0.0),
            )
            if not a_ok and not b_ok:
                both_wrong.append(case)
            elif not a_ok:
                a_only_wrong.append(case)
            else:
                b_only_wrong.append(case)

        return CompareFailuresResponse(
            experiment_a=experiment_a,
            experiment_b=experiment_b,
            a_only_wrong=a_only_wrong,
            b_only_wrong=b_only_wrong,
            both_wrong=both_wrong,
        )

    async def model_routing(
        self,
        project_id: str,
        *,
        min_accuracy: float = 0.8,
        limit: int = 10,
    ) -> list[ModelRoutingEntry]:
        """Recommend the most cost-effective model per evaluation run.

        For each model, take its best completed experiment and rank by a simple
        cost-aware score. Models meeting the accuracy floor are sorted by cost
        (cheapest first); the cheapest qualifying model is flagged recommended.
        Models below the floor are listed after them by accuracy.
        """
        stmt = select(Experiment).where(
            Experiment.status.in_(("completed", "partial")),
            Experiment.project_id == project_id,
        )
        org_id = self._org_id()
        if org_id is not None:
            stmt = stmt.where(Experiment.organization_id == org_id)
        result = await self.session.execute(stmt)
        experiments: Sequence[Experiment] = result.scalars().all()

        best_by_model: dict[str, Experiment] = {}
        for exp in experiments:
            current = best_by_model.get(exp.model_id)
            exp_accuracy = float(exp.accuracy or 0.0)
            if current is None or exp_accuracy > float(current.accuracy or 0.0):
                best_by_model[exp.model_id] = exp

        entries: list[ModelRoutingEntry] = []
        for model_id, exp in best_by_model.items():
            accuracy = float(exp.accuracy or 0.0)
            model = await self._model_name(model_id)
            entries.append(
                ModelRoutingEntry(
                    model_id=model_id,
                    model_name=model,
                    experiment_id=exp.id,
                    accuracy=accuracy,
                    avg_latency_ms=float((exp.metrics or {}).get("avg_latency_ms", 0.0)),
                    total_cost=float(exp.total_cost),
                    total_tokens=int(exp.total_tokens),
                )
            )

        qualifying = [e for e in entries if e.accuracy >= min_accuracy]
        below = [e for e in entries if e.accuracy < min_accuracy]
        qualifying.sort(key=lambda e: (e.total_cost, -e.accuracy))
        below.sort(key=lambda e: -e.accuracy)
        ranked = qualifying + below
        if qualifying:
            ranked[0].recommended = True
        return ranked[:limit]

    async def significance(
        self,
        experiment_a: str,
        experiment_b: str,
        *,
        n_iterations: int = 2000,
        confidence: float = 0.95,
        seed: int | None = None,
    ) -> SignificanceResponse:
        """Statistical comparison of two experiments on the same dataset.

        Pairs per-row scores by ``row_idx``, drops rows with an error on either
        side, then reports bootstrap confidence intervals for each experiment,
        a paired bootstrap test for the mean difference, and a McNemar test on
        paired pass/fail outcomes.
        """
        if experiment_a == experiment_b:
            raise ValidationError("experiment_ids must differ")
        exp_a = await self._get_experiment(experiment_a)
        exp_b = await self._get_experiment(experiment_b)
        if exp_a is None or exp_b is None:
            raise ValidationError("Both experiments must exist")

        async def _rows(eid: str) -> dict[int, ExperimentResult]:
            result = await self.session.execute(
                select(ExperimentResult).where(
                    ExperimentResult.experiment_id == eid
                )
            )
            return {r.row_idx: r for r in result.scalars().all()}

        rows_a = await _rows(experiment_a)
        rows_b = await _rows(experiment_b)
        common = sorted(set(rows_a) & set(rows_b))
        scores_a: list[float] = []
        scores_b: list[float] = []
        pass_a: list[bool] = []
        pass_b: list[bool] = []
        for idx in common:
            ra, rb = rows_a[idx], rows_b[idx]
            if ra.error or rb.error:
                continue
            sa = float(ra.score or 0.0)
            sb = float(rb.score or 0.0)
            scores_a.append(sa)
            scores_b.append(sb)
            pass_a.append(sa >= 1.0)
            pass_b.append(sb >= 1.0)

        if not scores_a:
            raise ValidationError(
                "The two experiments have no paired error-free rows to compare"
            )

        ci_a = bootstrap_ci(
            scores_a, n_iterations=n_iterations, confidence=confidence, seed=seed
        )
        ci_b = bootstrap_ci(
            scores_b, n_iterations=n_iterations, confidence=confidence, seed=seed
        )
        paired = paired_bootstrap_test(
            scores_a,
            scores_b,
            n_iterations=n_iterations,
            confidence=confidence,
            seed=seed,
        )
        mcnemar_p = mcnemar_p_value(pass_a, pass_b)
        return SignificanceResponse(
            experiment_a=experiment_a,
            experiment_b=experiment_b,
            paired_rows=len(scores_a),
            a={
                "mean": ci_a["mean"],
                "lower": ci_a["lower"],
                "upper": ci_a["upper"],
                "n": ci_a["n"],
            },
            b={
                "mean": ci_b["mean"],
                "lower": ci_b["lower"],
                "upper": ci_b["upper"],
                "n": ci_b["n"],
            },
            mean_diff=paired["mean_diff"],
            diff_ci_lower=paired["ci_lower"],
            diff_ci_upper=paired["ci_upper"],
            p_value=paired["p_value"],
            significant=paired["significant"],
            mcnemar_p_value=mcnemar_p,
            mcnemar_significant=mcnemar_p < (1.0 - confidence),
        )


def get_analytics_service(
    session: AsyncSession = Depends(get_session),
) -> AnalyticsService:
    return AnalyticsService(session)
