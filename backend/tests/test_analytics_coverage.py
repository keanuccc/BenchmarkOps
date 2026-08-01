from __future__ import annotations

import asyncio

from app.core.database import AsyncSessionLocal
from app.models.experiment import Experiment


def test_analytics_exposes_coverage_and_failure_rate(client) -> None:
    project_id = "project-coverage"

    async def seed() -> None:
        async with AsyncSessionLocal() as session:
            session.add(
                Experiment(
                    project_id=project_id,
                    name="Partial run",
                    dataset_id="dataset-coverage",
                    benchmark_id="benchmark-coverage",
                    prompt_id="prompt-coverage",
                    model_id="model-coverage",
                    status="completed",
                    metrics={
                        "accuracy": 0.5,
                        "rows_total": 4,
                        "dataset_rows_total": 5,
                        "coverage": 0.6,
                        "failure_rate": 0.2,
                    },
                    accuracy=0.5,
                )
            )
            await session.commit()

    asyncio.run(seed())

    leaderboard = client.get(
        "/api/v1/analytics/leaderboard", params={"project_id": project_id}
    ).json()
    summary = client.get(f"/api/v1/analytics/projects/{project_id}/summary").json()

    assert leaderboard[0]["dataset_rows_total"] == 5
    assert leaderboard[0]["coverage"] == 0.6
    assert leaderboard[0]["failure_rate"] == 0.2
    assert summary["coverage"] == 0.6
    assert summary["failure_rate"] == 0.2


def test_analytics_includes_partial_runs_and_normalizes_legacy_metrics(client) -> None:
    project_id = "project-legacy-coverage"

    async def seed() -> None:
        async with AsyncSessionLocal() as session:
            session.add_all(
                [
                    Experiment(
                        project_id=project_id,
                        name="Legacy run",
                        dataset_id="dataset-legacy",
                        benchmark_id="benchmark-legacy",
                        prompt_id="prompt-legacy",
                        model_id="model-legacy",
                        status="completed",
                        metrics={"accuracy": 1.0, "rows_total": 4},
                        accuracy=1.0,
                    ),
                    Experiment(
                        project_id=project_id,
                        name="Partial run",
                        dataset_id="dataset-partial",
                        benchmark_id="benchmark-partial",
                        prompt_id="prompt-partial",
                        model_id="model-partial",
                        status="partial",
                        metrics={
                            "accuracy": 1.0,
                            "rows_total": 2,
                            "dataset_rows_total": 4,
                            "rows_scored": 1,
                            "rows_failed": 1,
                        },
                        accuracy=1.0,
                    ),
                ]
            )
            await session.commit()

    asyncio.run(seed())

    leaderboard = client.get(
        "/api/v1/analytics/leaderboard", params={"project_id": project_id}
    ).json()
    summary = client.get(f"/api/v1/analytics/projects/{project_id}/summary").json()

    assert {entry["experiment_name"] for entry in leaderboard} == {
        "Legacy run",
        "Partial run",
    }
    legacy = next(entry for entry in leaderboard if entry["experiment_name"] == "Legacy run")
    assert legacy["coverage"] == 1.0
    assert legacy["failure_rate"] == 0.0
    assert summary["coverage"] == 0.625
    assert summary["failure_rate"] == 0.125
