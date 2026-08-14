"""Tests for A/B significance and LLM-judge calibration endpoints."""
from __future__ import annotations

from app.core.database import AsyncSessionLocal
from app.models.experiment import Experiment, ExperimentResult
from app.models.project import Project
from app.services.analytics_service import AnalyticsService


async def _seed_pair(session, exp_a_id: str, exp_b_id: str) -> None:
    rows = []
    for i in range(10):
        rows.append(
            ExperimentResult(
                experiment_id=exp_a_id,
                row_idx=i,
                input={"question": f"q{i}"},
                expected={"answer": "A"},
                output="A",
                score=1.0,
            )
        )
        rows.append(
            ExperimentResult(
                experiment_id=exp_b_id,
                row_idx=i,
                input={"question": f"q{i}"},
                expected={"answer": "A"},
                output="X",
                score=0.0,
            )
        )
    session.add_all(rows)
    await session.flush()


async def test_significance_detects_clear_winner():
    async with AsyncSessionLocal() as session:
        project = Project(name="sig-p")
        session.add(project)
        await session.flush()
        exp_a = Experiment(
            project_id=project.id,
            name="winner",
            dataset_id="d",
            benchmark_id="b",
            prompt_id="p",
            model_id="m1",
            status="completed",
        )
        exp_b = Experiment(
            project_id=project.id,
            name="loser",
            dataset_id="d",
            benchmark_id="b",
            prompt_id="p",
            model_id="m2",
            status="completed",
        )
        session.add_all([exp_a, exp_b])
        await session.flush()
        await _seed_pair(session, exp_a.id, exp_b.id)
        await session.commit()

        service = AnalyticsService(session)
        result = await service.significance(
            exp_a.id, exp_b.id, n_iterations=500, seed=1
        )
        assert result.paired_rows == 10
        assert result.a.mean == 1.0
        assert result.b.mean == 0.0
        assert result.mean_diff > 0.9
        assert result.significant is True
        assert result.p_value < 0.05
        assert result.mcnemar_significant is True


def test_judge_calibrate_endpoint(client):
    r = client.post(
        "/api/v1/benchmarks/judge/calibrate",
        json={
            "gold_labels": [1, 1, 0, 0],
            "judge_labels": [1, 1, 0, 0],
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["calibration"]["accuracy"] == 1.0
    assert body["calibration"]["f1"] == 1.0
    assert body["agreement"] is None


def test_judge_calibrate_endpoint_with_two_judges(client):
    r = client.post(
        "/api/v1/benchmarks/judge/calibrate",
        json={
            "gold_labels": [1, 1, 0, 0],
            "judge_labels": [1, 1, 0, 0],
            "judge_b_labels": [1, 1, 0, 0],
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["agreement"]["cohen_kappa"] == 1.0
