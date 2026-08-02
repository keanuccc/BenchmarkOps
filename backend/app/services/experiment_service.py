"""Business logic for the Experiment module + Evaluation Engine entrypoint."""
from __future__ import annotations

import logging
from collections.abc import AsyncGenerator, Sequence

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_session
from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.evaluation.metrics import (
    MetricEvaluationError,
    _call_metric,
    get_metric,
    has_metric_suite,
    normalize_metric_suite,
)
from app.evaluation.runner import _extract_answer, _first_value, _score_reason
from app.evaluation.runner import run_experiment
from app.evaluation.task_records import create_task, mark_done
from app.evaluation.task_queue import task_queue
from app.models.benchmark import Benchmark
from app.models.dataset import Dataset
from app.models.experiment import Experiment, ExperimentResult
from app.models.model import Model
from app.models.prompt import Prompt
from app.models.project import Project
from app.repositories.experiment import (
    ExperimentRepository,
    ExperimentResultRepository,
)
from app.repositories.task import TaskRepository
from app.schemas.experiment import ExperimentCreate, ExperimentUpdate
from app.services.benchmark_service import build_benchmark_snapshot

logger = logging.getLogger(__name__)


class ExperimentService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.experiments = ExperimentRepository(session)
        self.results = ExperimentResultRepository(session)

    async def _validate_components(self, data: ExperimentCreate) -> None:
        """Ensure all referenced aggregates exist before creating an experiment."""
        if await self.session.get(Project, data.project_id) is None:
            raise ValidationError(f"Referenced project '{data.project_id}' does not exist")

        checks = {
            "dataset": (Dataset, data.dataset_id),
            "benchmark": (Benchmark, data.benchmark_id),
            "prompt": (Prompt, data.prompt_id),
            "model": (Model, data.model_id),
        }
        for label, (model_cls, oid) in checks.items():
            component = await self.session.get(model_cls, oid)
            if component is None:
                raise ValidationError(f"Referenced {label} '{oid}' does not exist")
            component_project_id = getattr(component, "project_id", None)
            if component_project_id is not None and component_project_id != data.project_id:
                raise ValidationError(
                    f"Referenced {label} '{oid}' belongs to another project"
                )

    async def create(self, data: ExperimentCreate) -> Experiment:
        await self._validate_components(data)

        # Snapshot the referenced components' current content so a later edit to a
        # prompt/benchmark/model does not change how this experiment reproduces.
        prompt = await self.session.get(Prompt, data.prompt_id)
        benchmark = await self.session.get(Benchmark, data.benchmark_id)
        model = await self.session.get(Model, data.model_id)
        dataset = await self.session.get(Dataset, data.dataset_id)
        prompt_snapshot = {
            "template": prompt.template,
            "variables": prompt.variables,
            "version": prompt.version,
        }
        benchmark_snapshot = build_benchmark_snapshot(benchmark)
        model_snapshot = {
            "model_id": model.model_id,
            "name": model.name,
            "pricing": model.pricing,
            "provider": model.provider,
            "context_length": model.context_length,
            "is_free": model.model_id.endswith(":free")
            or (model.provider == "qiniu" and model.model_id in settings.qiniu_free_set),
        }
        contract = dataset.contract or {}
        dataset_snapshot = {
            "task_type": dataset.task_type,
            "schema_version": dataset.schema_version,
            "dataset_version": dataset.version,
            "sensitive_fields": (contract.get("sensitive_fields", []) or []),
            "structured_chat": bool(contract.get("structured_chat", False)),
            "answer_policy": contract.get("answer_policy", {}) or {},
        }

        experiment = Experiment(
            project_id=data.project_id,
            name=data.name,
            dataset_id=data.dataset_id,
            dataset_version=dataset.version,
            benchmark_id=data.benchmark_id,
            prompt_id=data.prompt_id,
            model_id=data.model_id,
            params=data.params or {},
            prompt_snapshot=prompt_snapshot,
            benchmark_snapshot=benchmark_snapshot,
            model_snapshot=model_snapshot,
            dataset_snapshot=dataset_snapshot,
            status="pending",
        )
        created = await self.experiments.create(experiment)
        logger.info("experiment %s created (project %s)", created.id, data.project_id)
        return created

    async def get(self, experiment_id: str) -> Experiment:
        exp = await self.experiments.get(experiment_id)
        if exp is None:
            raise NotFoundError(f"Experiment {experiment_id} not found")
        return exp

    async def list(
        self,
        *,
        project_id: str | None = None,
        status: str | None = None,
        q: str | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> Sequence[Experiment]:
        return await self.experiments.list(
            offset=offset,
            limit=limit,
            filters={"project_id": project_id, "status": status},
            search=q,
        )

    async def count(
        self,
        *,
        project_id: str | None = None,
        status: str | None = None,
        q: str | None = None,
    ) -> int:
        return await self.experiments.count(
            filters={"project_id": project_id, "status": status}, search=q
        )

    async def update(self, experiment_id: str, data: ExperimentUpdate) -> Experiment:
        exp = await self.get(experiment_id)
        return await self.experiments.update(exp, data.model_dump(exclude_unset=True))

    async def delete(self, experiment_id: str) -> None:
        exp = await self.get(experiment_id)
        # Keep the audit trail: mark the task as belonging to a deleted
        # experiment instead of hard-deleting the row.
        await TaskRepository(self.session).mark_experiment_deleted([experiment_id])
        await self.results.delete_by_experiment(experiment_id)
        await self.experiments.delete(exp)
        logger.info("experiment %s deleted", experiment_id)

    async def list_results(
        self, experiment_id: str, *, offset: int = 0, limit: int = 1000
    ) -> Sequence[ExperimentResult]:
        await self.get(experiment_id)
        return await self.results.list_by_experiment(
            experiment_id, offset=offset, limit=limit
        )

    async def get_sensitive_fields(self, experiment_id: str) -> set[str]:
        """Sensitive fields declared by the dataset bound to this experiment."""
        experiment = await self.get(experiment_id)
        snapshot_fields = (experiment.dataset_snapshot or {}).get("sensitive_fields")
        if snapshot_fields:
            return set(snapshot_fields)
        from app.repositories.dataset import DatasetVersionRepository

        version = experiment.dataset_version or 1
        meta = await DatasetVersionRepository(self.session).get_by_version(
            experiment.dataset_id, version
        )
        if meta is not None:
            return set((meta.contract or {}).get("sensitive_fields", []) or [])
        dataset = await self.session.get(Dataset, experiment.dataset_id)
        if dataset is not None:
            return set((dataset.contract or {}).get("sensitive_fields", []) or [])
        return set()

    async def recompute_scores(self, experiment_id: str, *, diff_limit: int = 100) -> dict:
        """Re-score stored outputs without calling the evaluated model again."""
        experiment = await self.get(experiment_id)
        results = list(await self.results.list_by_experiment(experiment_id))

        snapshot = experiment.benchmark_snapshot
        if snapshot:
            metric_name = snapshot.get("metric")
            metric_config = snapshot.get("metric_config", {}) or {}
            benchmark_spec = snapshot.get("spec", {}) or {}
            benchmark_type = snapshot.get("type")
        else:
            benchmark = await self.session.get(Benchmark, experiment.benchmark_id)
            if benchmark is None:
                raise ValidationError("Experiment references a missing benchmark")
            metric_name = benchmark.metric
            metric_config = benchmark.metric_config or {}
            benchmark_spec = {}
            benchmark_type = benchmark.type

        dataset_snapshot = experiment.dataset_snapshot or {}
        if dataset_snapshot:
            answer_policy = dataset_snapshot.get("answer_policy", {}) or {}
        else:
            dataset = await self.session.get(Dataset, experiment.dataset_id)
            contract = dataset.contract if dataset is not None else {}
            answer_policy = (contract or {}).get("answer_policy", {}) or {}

        if not metric_name:
            raise ValidationError("Experiment has no scoring metric")

        metric_suite = normalize_metric_suite(metric_name, metric_config, benchmark_spec)
        explicit_metric_suite = has_metric_suite(metric_config, benchmark_spec)
        metric_fns = {item["name"]: get_metric(item["name"]) for item in metric_suite}
        total_weight = sum(item["weight"] for item in metric_suite) or 1.0

        model_snapshot = experiment.model_snapshot or {}
        current_model = None
        if not model_snapshot.get("model_id") or not model_snapshot.get("provider"):
            current_model = await self.session.get(Model, experiment.model_id)
        metric_context = {
            "benchmark_type": benchmark_type,
            "model_id": model_snapshot.get("model_id")
            or (current_model.model_id if current_model is not None else ""),
            "provider": model_snapshot.get("provider")
            or (current_model.provider if current_model is not None else settings.default_provider),
            "answer_policy": answer_policy,
            "raise_on_error": True,
        }
        differences: list[dict] = []
        recomputed_scores: list[float] = []
        metric_errors = 0

        for result in results:
            if result.error:
                continue
            multi_answer = answer_policy.get("multi_answer")
            cleaned_prediction = _extract_answer(
                result.output or "",
                split_commas=multi_answer not in ("all", "set"),
                normalize_whitespace=False,
                strip_units=answer_policy.get("strip_units", True),
            )
            expected_canonical = _first_value(result.expected)
            score = 0.0
            metric_scores: dict[str, float] = {}
            try:
                for item in metric_suite:
                    metric_kwargs = dict(item["config"])
                    for key, value in metric_context.items():
                        metric_kwargs.setdefault(key, value)
                    metric_kwargs["raise_on_error"] = True
                    metric_score = float(await _call_metric(
                        metric_fns[item["name"]],
                        cleaned_prediction,
                        expected_canonical,
                        expected_raw=result.expected,
                        **metric_kwargs,
                    ))
                    metric_scores[item["name"]] = metric_score
                    score += item["weight"] * metric_score
            except MetricEvaluationError:
                metric_errors += 1
                continue
            except Exception:
                metric_errors += 1
                continue
            score /= total_weight
            recomputed_scores.append(score)
            if abs(float(result.score or 0.0) - score) > 1e-9 and len(differences) < diff_limit:
                differences.append(
                    {
                        "row_idx": result.row_idx,
                        "stored_score": float(result.score or 0.0),
                        "recomputed_score": score,
                        "cleaned_prediction": cleaned_prediction,
                        "expected_canonical": expected_canonical,
                        "score_reason": _score_reason(
                            "metric_suite" if explicit_metric_suite else metric_name,
                            score,
                            cleaned_prediction,
                            expected_canonical,
                            metric_scores,
                        ),
                    }
                )

        stored_accuracy = float(
            experiment.accuracy or (experiment.metrics or {}).get("accuracy", 0.0)
        )
        rows_scored = len(recomputed_scores)
        rows_failed = sum(1 for result in results if result.error) + metric_errors
        stored_metrics = experiment.metrics or {}
        dataset_rows_total = int(
            stored_metrics.get("dataset_rows_total")
            or experiment.rows_total
            or len(results)
        )
        rows_unprocessed = max(dataset_rows_total - len(results), 0)
        recomputed_accuracy = (
            sum(recomputed_scores) / len(recomputed_scores) if recomputed_scores else 0.0
        )
        return {
            "metric": "metric_suite" if explicit_metric_suite else metric_name,
            "rows_total": len(results),
            "dataset_rows_total": dataset_rows_total,
            "rows_scored": rows_scored,
            "rows_failed": rows_failed,
            "rows_unprocessed": rows_unprocessed,
            "coverage": rows_scored / dataset_rows_total if dataset_rows_total else 0.0,
            "failure_rate": rows_failed / dataset_rows_total if dataset_rows_total else 0.0,
            "metric_errors": metric_errors,
            "stored_accuracy": stored_accuracy,
            "recomputed_accuracy": recomputed_accuracy,
            "changed_rows": len(differences),
            "differences": differences,
        }

    async def run(self, experiment_id: str) -> Experiment:
        """Queue a background evaluation run. Guard against in-flight/dup submissions."""
        exp = await self.get(experiment_id)
        if exp.status in ("running", "queued"):
            raise ConflictError("Experiment is already running")
        # Mark queued immediately so the UI reflects receipt before work begins.
        await self.experiments.update(exp, {"status": "queued", "error": None})
        await self.session.commit()
        # Persist an audit record before the in-process queue picks the task up,
        # so a restart can mark both the experiment and its task as failed.
        await create_task(experiment_id)
        try:
            task_queue.submit(
                lambda: run_experiment(experiment_id), experiment_id=experiment_id
            )
        except Exception:
            logger.exception("failed to enqueue experiment %s", experiment_id)
            # Never leave the experiment 'queued' with no job behind it.
            await self.experiments.update(
                exp, {"status": "failed", "error": "Task queue submission failed"}
            )
            await self.session.commit()
            await mark_done(experiment_id, status="failed", error="Task queue submission failed")
            raise
        return exp

    async def retry(self, experiment_id: str) -> Experiment:
        """Re-run a completed/failed experiment (results are cleared by the runner)."""
        exp = await self.get(experiment_id)
        if exp.status in ("running", "queued"):
            raise ConflictError("Experiment is already running")
        return await self.run(experiment_id)

    async def duplicate(self, experiment_id: str, name: str | None = None) -> Experiment:
        src = await self.get(experiment_id)
        clone = Experiment(
            project_id=src.project_id,
            name=name or f"{src.name} (copy)",
            dataset_id=src.dataset_id,
            dataset_version=src.dataset_version,
            benchmark_id=src.benchmark_id,
            prompt_id=src.prompt_id,
            model_id=src.model_id,
            params=dict(src.params or {}),
            prompt_snapshot=src.prompt_snapshot,
            benchmark_snapshot=src.benchmark_snapshot,
            model_snapshot=src.model_snapshot,
            dataset_snapshot=src.dataset_snapshot,
            status="pending",
        )
        return await self.experiments.create(clone)


async def get_experiment_service(
    session: AsyncSession = Depends(get_session),
) -> AsyncGenerator[ExperimentService, None]:
    yield ExperimentService(session)
