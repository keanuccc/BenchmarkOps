"""Tests for subgroup analysis and experiment failure diffing."""
from __future__ import annotations

from app.services.analytics_service import AnalyticsService
from app.core.database import AsyncSessionLocal
from app.models.experiment import Experiment, ExperimentResult
from app.models.project import Project


async def _seed_experiment_rows(
    session, *, exp_a_id: str, exp_b_id: str
) -> None:
    rows = [
        ExperimentResult(
            experiment_id=exp_a_id,
            row_idx=0,
            input={"question": "q1", "_metadata": {"category": "退款"}},
            expected={"answer": "A"},
            output="A",
            score=1.0,
        ),
        ExperimentResult(
            experiment_id=exp_a_id,
            row_idx=1,
            input={"question": "q2", "_metadata": {"category": "物流"}},
            expected={"answer": "B"},
            output="X",
            score=0.0,
        ),
        ExperimentResult(
            experiment_id=exp_a_id,
            row_idx=2,
            input={"question": "q3", "_metadata": {"category": "退款"}},
            expected={"answer": "C"},
            output="C",
            score=1.0,
            error=None,
        ),
        # Experiment B: row 0 same answer (both right), row 1 differs (B right,
        # A wrong), row 2 differs (B wrong, A right).
        ExperimentResult(
            experiment_id=exp_b_id,
            row_idx=0,
            input={"question": "q1"},
            expected={"answer": "A"},
            output="A",
            score=1.0,
        ),
        ExperimentResult(
            experiment_id=exp_b_id,
            row_idx=1,
            input={"question": "q2"},
            expected={"answer": "B"},
            output="B",
            score=1.0,
        ),
        ExperimentResult(
            experiment_id=exp_b_id,
            row_idx=2,
            input={"question": "q3"},
            expected={"answer": "C"},
            output="Z",
            score=0.0,
        ),
    ]
    session.add_all(rows)
    await session.flush()


async def test_subgroups_groups_by_metadata_field():
    async with AsyncSessionLocal() as session:
        project = Project(name="subgroup-p")
        session.add(project)
        await session.flush()
        exp = Experiment(
            project_id=project.id,
            name="subgroup-exp",
            dataset_id="d",
            benchmark_id="b",
            prompt_id="p",
            model_id="m",
            status="completed",
        )
        session.add(exp)
        await session.flush()
        await _seed_experiment_rows(session, exp_a_id=exp.id, exp_b_id="other")
        await session.commit()

        service = AnalyticsService(session)
        result = await service.subgroups(exp.id, group_field="category")
        by_group = {g.group: g for g in result.groups}
        assert by_group["退款"].row_count == 2
        assert by_group["退款"].pass_count == 2
        assert by_group["退款"].fail_count == 0
        assert by_group["物流"].row_count == 1
        assert by_group["物流"].pass_count == 0
        assert by_group["物流"].fail_count == 1


async def test_compare_failures_buckets():
    async with AsyncSessionLocal() as session:
        project = Project(name="diff-p")
        session.add(project)
        await session.flush()
        exp_a = Experiment(
            project_id=project.id,
            name="a",
            dataset_id="d",
            benchmark_id="b",
            prompt_id="p",
            model_id="m",
            status="completed",
        )
        exp_b = Experiment(
            project_id=project.id,
            name="b",
            dataset_id="d",
            benchmark_id="b",
            prompt_id="p",
            model_id="m",
            status="completed",
        )
        session.add_all([exp_a, exp_b])
        await session.flush()
        await _seed_experiment_rows(
            session, exp_a_id=exp_a.id, exp_b_id=exp_b.id
        )
        await session.commit()

        service = AnalyticsService(session)
        result = await service.compare_failures(exp_a.id, exp_b.id)
        assert [c.row_idx for c in result.a_only_wrong] == [1]
        assert [c.row_idx for c in result.b_only_wrong] == [2]
        assert result.both_wrong == []
