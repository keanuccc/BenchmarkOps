"""Read-only analytics aggregation over existing Experiment data.

All queries run against the experiments / experiment_results / models tables.
No mutations, no new tables.
"""
from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import aliased
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
from app.models.benchmark import Benchmark
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

    @staticmethod
    def _require_comparable_pair(exp_a: Experiment, exp_b: Experiment) -> None:
        """Ensure two experiments can be paired meaningfully by row_idx."""
        mismatch = [
            field
            for field in ("dataset_id", "dataset_version", "benchmark_id")
            if getattr(exp_a, field) != getattr(exp_b, field)
        ]
        if mismatch:
            raise ValidationError(
                "Experiments must share the same dataset, dataset version and "
                "benchmark to be compared; mismatched fields: "
                + ", ".join(mismatch)
            )

    @classmethod
    def _require_comparable_set(cls, experiments: list[Experiment]) -> None:
        if len(experiments) < 2:
            return
        baseline = experiments[0]
        for exp in experiments[1:]:
            cls._require_comparable_pair(baseline, exp)

    async def _experiment_bootstrap_ci(
        self, experiment_id: str
    ) -> tuple[float | None, float | None]:
        """Return a 95% bootstrap CI for one experiment's error-free scores."""
        result = await self.session.execute(
            select(ExperimentResult.score).where(
                ExperimentResult.experiment_id == experiment_id,
                ExperimentResult.error.is_(None),
            )
        )
        scores = [float(score or 0.0) for score in result.scalars().all()]
        if not scores:
            return None, None
        ci = bootstrap_ci(scores, n_iterations=500, confidence=0.95, seed=0)
        return ci["lower"], ci["upper"]

    async def leaderboard(
        self,
        project_id: str | None = None,
        benchmark_id: str | None = None,
        dataset_id: str | None = None,
        dataset_version: int | None = None,
        limit: int = 50,
        with_confidence: bool = False,
    ) -> list[LeaderboardEntry]:
        stmt = select(Experiment).where(Experiment.status.in_(("completed", "partial")))
        org_id = self._org_id()
        if org_id is not None:
            stmt = stmt.where(Experiment.organization_id == org_id)
        if project_id is not None:
            stmt = stmt.where(Experiment.project_id == project_id)
        if benchmark_id is not None:
            stmt = stmt.where(Experiment.benchmark_id == benchmark_id)
        if dataset_id is not None:
            stmt = stmt.where(Experiment.dataset_id == dataset_id)
        if dataset_version is not None:
            stmt = stmt.where(Experiment.dataset_version == dataset_version)
        result = await self.session.execute(stmt)
        experiments: Sequence[Experiment] = result.scalars().all()

        dataset_ids = {exp.dataset_id for exp in experiments}
        benchmark_ids = {exp.benchmark_id for exp in experiments}
        dataset_names: dict[str, str] = {}
        benchmark_names: dict[str, str] = {}
        if dataset_ids:
            dataset_rows = (
                await self.session.execute(
                    select(Dataset.id, Dataset.name).where(
                        Dataset.id.in_(dataset_ids)
                    )
                )
            ).all()
            dataset_names = {id_: name for id_, name in dataset_rows}
        if benchmark_ids:
            benchmark_rows = (
                await self.session.execute(
                    select(Benchmark.id, Benchmark.name).where(
                        Benchmark.id.in_(benchmark_ids)
                    )
                )
            ).all()
            benchmark_names = {id_: name for id_, name in benchmark_rows}

        entries: list[LeaderboardEntry] = []
        for exp in experiments:
            metrics = exp.metrics or {}
            normalized = _normalized_metrics(metrics)
            # Prefer the materialized accuracy column for consistency with the
            # ORDER BY below, but fall back to the metrics blob for parity.
            accuracy = exp.accuracy if exp.accuracy else metrics.get("accuracy", 0.0)
            ci_lower: float | None = None
            ci_upper: float | None = None
            if with_confidence:
                ci_lower, ci_upper = await self._experiment_bootstrap_ci(exp.id)
            entries.append(
                LeaderboardEntry(
                    experiment_id=exp.id,
                    experiment_name=exp.name,
                    model_id=exp.model_id,
                    model_name=await self._model_name(exp.model_id),
                    benchmark_id=exp.benchmark_id,
                    dataset_id=exp.dataset_id,
                    dataset_version=exp.dataset_version,
                    benchmark_name=benchmark_names.get(exp.benchmark_id, exp.benchmark_id),
                    dataset_name=dataset_names.get(exp.dataset_id, exp.dataset_id),
                    accuracy=accuracy,
                    avg_latency_ms=metrics.get("avg_latency_ms", 0.0),
                    total_cost=float(exp.total_cost),
                    total_tokens=int(exp.total_tokens),
                    rows_total=int(normalized["rows_total"]),
                    dataset_rows_total=int(normalized["dataset_rows_total"]),
                    coverage=float(normalized["coverage"]),
                    failure_rate=float(normalized["failure_rate"]),
                    status=exp.status,
                    ci_lower=ci_lower,
                    ci_upper=ci_upper,
                )
            )

        # Keep comparable runs adjacent; within a cohort rank by accuracy then
        # cost. This does not force one cross-cohort ranking, but makes it clear
        # when the board spans multiple datasets/benchmarks.
        entries.sort(
            key=lambda e: (
                e.dataset_id,
                e.dataset_version or 0,
                e.benchmark_id,
                -e.accuracy,
                e.total_cost,
            )
        )
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
        self._require_comparable_set(experiments)

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
        stmt = (
            select(ExperimentResult)
            .where(
                ExperimentResult.experiment_id == experiment_id,
                or_(
                    ExperimentResult.score < 1.0,
                    ExperimentResult.error.is_not(None),
                ),
            )
            .order_by(ExperimentResult.score.asc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        rows: Sequence[ExperimentResult] = result.scalars().all()

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
            for r in rows
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
            select(
                ExperimentResult.input,
                ExperimentResult.score,
                ExperimentResult.error,
            ).where(
                ExperimentResult.experiment_id == experiment_id
            )
        )
        rows = result.all()
        buckets: dict[str, list[tuple[dict, float, str | None]]] = {}
        for raw_input, score, error in rows:
            raw_input = raw_input or {}
            metadata = raw_input.get("_metadata") or {}
            value = raw_input.get(group_field, metadata.get(group_field))
            key = str(value).strip() if value not in (None, "") else "(未标注)"
            buckets.setdefault(key, []).append((raw_input, score, error))
        groups = []
        for key, items in sorted(buckets.items(), key=lambda kv: -len(kv[1])):
            scores = [float(score or 0.0) for _raw, score, error in items if error is None]
            errors = [error for _raw, _score, error in items if error]
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
        self,
        experiment_a: str,
        experiment_b: str,
        *,
        limit: int = 500,
    ) -> CompareFailuresResponse:
        """Diff the per-row outcomes of two experiments.

        Returns three buckets: wrong only in A, wrong only in B, wrong in both.
        The ``limit`` caps how many paired rows are loaded and returned, so a
        large benchmark cannot exhaust memory while building the diff view.
        """
        if experiment_a == experiment_b:
            raise ValidationError("experiment_ids must differ")
        exp_a = await self._get_experiment(experiment_a)
        exp_b = await self._get_experiment(experiment_b)
        if exp_a is None or exp_b is None:
            raise ValidationError("Both experiments must exist")
        self._require_comparable_pair(exp_a, exp_b)

        A = ExperimentResult
        B = aliased(ExperimentResult)
        result = await self.session.execute(
            select(
                A.row_idx,
                A.input,
                A.expected,
                A.output,
                A.score,
                A.error,
                B.output,
                B.score,
                B.error,
            )
            .select_from(A)
            .join(
                B,
                and_(
                    A.experiment_id == experiment_a,
                    B.experiment_id == experiment_b,
                    A.row_idx == B.row_idx,
                ),
            )
            .order_by(A.row_idx.asc())
            .limit(limit)
        )
        paired_rows = result.all()
        sensitive = await self._sensitive_fields(experiment_a)

        a_only_wrong: list[CompareFailureCase] = []
        b_only_wrong: list[CompareFailureCase] = []
        both_wrong: list[CompareFailureCase] = []
        for (
            row_idx,
            a_input,
            a_expected,
            a_output,
            a_score,
            a_error,
            b_output,
            b_score,
            b_error,
        ) in paired_rows:
            a_ok = a_error is None and float(a_score or 0.0) >= 1.0
            b_ok = b_error is None and float(b_score or 0.0) >= 1.0
            if a_ok and b_ok:
                continue
            case = CompareFailureCase(
                row_idx=row_idx,
                input=redact_values(a_input or {}, sensitive),
                expected=redact_values(a_expected, sensitive) if a_expected else None,
                a_output=redact_text(a_output or ""),
                a_score=float(a_score or 0.0),
                b_output=redact_text(b_output or ""),
                b_score=float(b_score or 0.0),
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
        benchmark_id: str | None = None,
        dataset_id: str | None = None,
        dataset_version: int | None = None,
    ) -> list[ModelRoutingEntry]:
        """Recommend the cheapest model that still meets an accuracy floor.

        Comparisons are only meaningful within one (dataset, dataset version,
        benchmark) cohort. When no cohort is supplied, the most common cohort
        in the project is used so we do not rank models against different
        evaluation protocols. Cost is normalized per scored row.
        """
        stmt = select(Experiment).where(
            Experiment.status.in_(("completed", "partial")),
            Experiment.project_id == project_id,
        )
        if benchmark_id is not None:
            stmt = stmt.where(Experiment.benchmark_id == benchmark_id)
        if dataset_id is not None:
            stmt = stmt.where(Experiment.dataset_id == dataset_id)
        if dataset_version is not None:
            stmt = stmt.where(Experiment.dataset_version == dataset_version)
        org_id = self._org_id()
        if org_id is not None:
            stmt = stmt.where(Experiment.organization_id == org_id)
        result = await self.session.execute(stmt)
        experiments: Sequence[Experiment] = result.scalars().all()

        if not experiments:
            return []

        if benchmark_id is None and dataset_id is None and dataset_version is None:
            experiments = self._dominant_comparable_cohort(list(experiments))

        best_by_model: dict[str, Experiment] = {}
        for exp in experiments:
            current = best_by_model.get(exp.model_id)
            exp_accuracy = float(exp.accuracy or 0.0)
            if current is None or exp_accuracy > float(current.accuracy or 0.0):
                best_by_model[exp.model_id] = exp

        entries: list[ModelRoutingEntry] = []
        for model_id, exp in best_by_model.items():
            accuracy = float(exp.accuracy or 0.0)
            rows_total = int(_normalized_metrics(exp.metrics)["rows_total"])
            cost_per_row = (
                float(exp.total_cost) / rows_total if rows_total > 0 else 0.0
            )
            cost_unknown = bool((exp.metrics or {}).get("cost_unknown"))
            model = await self._model_name(model_id)
            entries.append(
                ModelRoutingEntry(
                    model_id=model_id,
                    model_name=model,
                    experiment_id=exp.id,
                    accuracy=accuracy,
                    avg_latency_ms=float((exp.metrics or {}).get("avg_latency_ms", 0.0)),
                    total_cost=float(exp.total_cost),
                    cost_per_row=cost_per_row,
                    cost_unknown=cost_unknown,
                    total_tokens=int(exp.total_tokens),
                    rows_total=rows_total,
                    benchmark_id=exp.benchmark_id,
                    dataset_id=exp.dataset_id,
                    dataset_version=exp.dataset_version,
                )
            )

        qualifying = [e for e in entries if e.accuracy >= min_accuracy]
        below = [e for e in entries if e.accuracy < min_accuracy]
        qualifying.sort(key=lambda e: (e.cost_unknown, e.cost_per_row, -e.accuracy))
        below.sort(key=lambda e: -e.accuracy)
        ranked = qualifying + below
        if qualifying:
            ranked[0].recommended = True
        return ranked[:limit]

    @staticmethod
    def _dominant_comparable_cohort(
        experiments: list[Experiment],
    ) -> list[Experiment]:
        """Select the most common comparable cohort among a project's runs."""
        cohorts: dict[tuple, list[Experiment]] = {}
        for exp in experiments:
            key = (exp.dataset_id, exp.dataset_version, exp.benchmark_id)
            cohorts.setdefault(key, []).append(exp)
        if not cohorts:
            return []
        return max(cohorts.values(), key=lambda group: (len(group),))

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
        self._require_comparable_pair(exp_a, exp_b)

        async def _rows(eid: str) -> dict[int, tuple[float, str | None]]:
            result = await self.session.execute(
                select(
                    ExperimentResult.row_idx,
                    ExperimentResult.score,
                    ExperimentResult.error,
                ).where(
                    ExperimentResult.experiment_id == eid
                )
            )
            return {
                row_idx: (float(score or 0.0), error)
                for row_idx, score, error in result.all()
            }

        rows_a = await _rows(experiment_a)
        rows_b = await _rows(experiment_b)
        common = sorted(set(rows_a) & set(rows_b))
        scores_a: list[float] = []
        scores_b: list[float] = []
        pass_a: list[bool] = []
        pass_b: list[bool] = []
        for idx in common:
            score_a, error_a = rows_a[idx]
            score_b, error_b = rows_b[idx]
            if error_a or error_b:
                continue
            sa = float(score_a or 0.0)
            sb = float(score_b or 0.0)
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
