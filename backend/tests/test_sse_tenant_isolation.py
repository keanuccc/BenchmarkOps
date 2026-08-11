"""SSE streams must honor organization isolation."""
from __future__ import annotations

from app.core.database import AsyncSessionLocal
from app.models.experiment import Experiment
from app.models.project import Project


def _create_org(client, name: str) -> str:
    r = client.post("/api/v1/organizations", json={"name": name})
    assert r.status_code == 201
    return r.json()["api_key"]["key"]


async def _seed_pending_experiment(project_id: str) -> str:
    async with AsyncSessionLocal() as session:
        exp = Experiment(
            project_id=project_id,
            name="sse-exp",
            dataset_id="d",
            benchmark_id="b",
            prompt_id="p",
            model_id="m",
            status="pending",
            progress=0,
        )
        session.add(exp)
        await session.commit()
        return exp.id


def test_sse_rejects_other_org_key(client):
    key_a = _create_org(client, "SSE A")
    key_b = _create_org(client, "SSE B")
    project = client.post(
        "/api/v1/projects",
        json={"name": "sse-p"},
        headers={"Authorization": f"Bearer {key_a}"},
    )
    pid = project.json()["id"]

    import asyncio

    exp_id = asyncio.run(_seed_pending_experiment(pid))

    # Org B must not receive progress for Org A's experiment.
    with client.stream(
        "GET",
        f"/api/v1/experiments/{exp_id}/stream?token={key_b}",
    ) as resp:
        assert resp.status_code == 200
        body = "".join(resp.iter_lines())
        assert "experiment not found" in body

    # Org A can subscribe to its own experiment.
    with client.stream(
        "GET",
        f"/api/v1/experiments/{exp_id}/stream?token={key_a}",
    ) as resp:
        assert resp.status_code == 200
        lines = resp.iter_lines()
        head = [next(lines, "") for _ in range(4)]
        assert any("id:" in line or "progress" in line for line in head)


def test_sse_completed_experiment_emits_json_progress(client):
    """A finished experiment must stream a valid progress event (not an error)."""
    from datetime import datetime, timezone

    from app.core.database import AsyncSessionLocal
    from app.models.experiment import Experiment
    from app.models.project import Project

    import asyncio

    async def _seed():
        async with AsyncSessionLocal() as session:
            project = Project(name="sse-completed")
            session.add(project)
            await session.flush()
            exp = Experiment(
                project_id=project.id,
                name="done",
                dataset_id="d",
                benchmark_id="b",
                prompt_id="p",
                model_id="m",
                status="completed",
                progress=3,
                rows_total=3,
                cells_done=3,
                accuracy=1.0,
                metrics={"accuracy": 1.0},
                total_cost=0.0,
                total_tokens=10,
                runtime_ms=50,
                updated_at=datetime.now(timezone.utc),
            )
            session.add(exp)
            await session.commit()
            return exp.id

    exp_id = asyncio.run(_seed())
    with client.stream(
        "GET",
        f"/api/v1/experiments/{exp_id}/stream",
    ) as resp:
        assert resp.status_code == 200
        body = "".join(resp.iter_lines())
        assert "event: progress" in body
        assert "stream error" not in body
        assert '"updated_at":' in body
