"""Tests for organization budget enforcement and model routing suggestions."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.core.database import AsyncSessionLocal
from app.models.experiment import Experiment
from app.models.organization import Organization
from app.models.project import Project
from app.services.analytics_service import AnalyticsService
from app.services.budget_service import check_org_budget


async def _seed(
    session,
    *,
    org_id: str | None,
    project_id: str,
    rows: list[tuple[str, float, float]],
) -> None:
    now = datetime.now(timezone.utc)
    for i, (model_id, accuracy, cost) in enumerate(rows):
        session.add(
            Experiment(
                project_id=project_id,
                organization_id=org_id,
                name=f"exp-{i}",
                dataset_id="d",
                benchmark_id="b",
                prompt_id="p",
                model_id=model_id,
                status="completed",
                accuracy=accuracy,
                total_cost=cost,
                total_tokens=100,
                runtime_ms=200,
                metrics={"accuracy": accuracy, "avg_latency_ms": 100.0},
                created_at=now - timedelta(hours=i),
            )
        )
    await session.flush()


async def test_budget_blocked_when_exhausted():
    async with AsyncSessionLocal() as session:
        org = Organization(
            name="budget-org", monthly_budget_usd=1.0
        )
        session.add(org)
        await session.flush()
        project = Project(name="budget-p", organization_id=org.id)
        session.add(project)
        await session.flush()
        await _seed(
            session,
            org_id=org.id,
            project_id=project.id,
            rows=[("m1", 0.9, 0.6), ("m2", 0.8, 0.6)],
        )
        await session.commit()

        from app.core.exceptions import ValidationError

        try:
            await check_org_budget(org.id, session)
            raised = False
        except ValidationError:
            raised = True
        assert raised is True


async def test_budget_allowed_under_cap():
    async with AsyncSessionLocal() as session:
        org = Organization(
            name="budget-ok", monthly_budget_usd=100.0
        )
        session.add(org)
        await session.flush()
        project = Project(name="budget-ok-p", organization_id=org.id)
        session.add(project)
        await session.flush()
        await _seed(
            session,
            org_id=org.id,
            project_id=project.id,
            rows=[("m1", 0.9, 0.6)],
        )
        await session.commit()
        await check_org_budget(org.id, session)  # must not raise


async def test_model_routing_ranks_cost_effective_models():
    async with AsyncSessionLocal() as session:
        project = Project(name="route-p")
        session.add(project)
        await session.flush()
        await _seed(
            session,
            org_id=None,
            project_id=project.id,
            rows=[
                ("cheap-model", 0.82, 0.01),
                ("accurate-model", 0.95, 5.0),
                ("weak-model", 0.6, 0.001),
            ],
        )
        await session.commit()

        service = AnalyticsService(session)
        routing = await service.model_routing(
            project.id, min_accuracy=0.8
        )
        names = [r.model_name for r in routing]
        assert names[0] == "cheap-model"  # qualifies and costs the least
        assert routing[0].recommended is True
        assert routing[2].model_name == "weak-model"  # below floor, last
