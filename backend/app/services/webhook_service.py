"""Webhook subscriptions: CRUD plus experiment-event delivery."""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import urllib.error
import urllib.request
from collections.abc import Sequence

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal, get_session
from app.core.exceptions import NotFoundError, ValidationError
from app.models.experiment import Experiment
from app.models.webhook import WebhookSubscription
from app.repositories.project import ProjectRepository
from app.repositories.webhook import WebhookRepository
from app.schemas.webhook import WebhookCreate, WebhookUpdate

logger = logging.getLogger(__name__)


def _sign(secret: str, body: bytes) -> str:
    return hmac.new(
        secret.encode("utf-8"), body, hashlib.sha256
    ).hexdigest()


async def _deliver(
    webhook: WebhookSubscription, event: str, payload: dict
) -> bool:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "BenchmarkOps-Webhook/1.0",
        "X-BenchmarkOps-Event": event,
    }
    if webhook.secret:
        headers["X-BenchmarkOps-Signature"] = _sign(webhook.secret, body)

    def _post() -> bool:
        req = urllib.request.Request(
            webhook.url, data=body, headers=headers, method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return 200 <= resp.status < 300
        except (urllib.error.URLError, OSError) as exc:
            logger.warning(
                "webhook %s delivery to %s failed: %s",
                webhook.id,
                webhook.url,
                exc,
            )
            return False

    return await asyncio.to_thread(_post)


async def notify_experiment(experiment_id: str, status: str) -> None:
    """Deliver an experiment lifecycle event to matching webhooks (best-effort).

    Called by the evaluation runner after a run finishes; failures are logged
    and never affect the run outcome.
    """
    event = (
        "experiment.completed"
        if status in ("completed", "partial")
        else "experiment.failed"
    )
    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(Experiment).where(Experiment.id == experiment_id)
            )
            exp = result.scalar_one_or_none()
            if exp is None:
                return
            payload = {
                "event": event,
                "experiment_id": experiment_id,
                "status": exp.status or status,
                "accuracy": float(exp.accuracy or 0.0),
                "total_cost": float(exp.total_cost or 0.0),
                "total_tokens": int(exp.total_tokens or 0),
                "project_id": exp.project_id,
                "runtime_ms": int(exp.runtime_ms or 0),
            }
            result = await session.execute(
                select(WebhookSubscription).where(
                    WebhookSubscription.project_id == exp.project_id,
                    WebhookSubscription.is_active.is_(True),
                )
            )
            hooks: Sequence[WebhookSubscription] = result.scalars().all()
        for hook in hooks:
            if event in (hook.events or []):
                asyncio.create_task(
                    _deliver(hook, event, payload), name=f"webhook-{hook.id}"
                )
    except Exception:  # noqa: BLE001
        logger.exception("webhook notification failed for experiment %s", experiment_id)


class WebhookService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = WebhookRepository(session)

    async def create(self, data: WebhookCreate) -> WebhookSubscription:
        if await ProjectRepository(self.session).get(data.project_id) is None:
            raise ValidationError(f"Project '{data.project_id}' does not exist")
        obj = WebhookSubscription(
            project_id=data.project_id,
            name=data.name,
            url=data.url,
            secret=data.secret,
            events=data.events,
        )
        return await self.repo.create(obj)

    async def list(self, project_id: str) -> Sequence[WebhookSubscription]:
        return await self.repo.list(filters={"project_id": project_id})

    async def get(self, webhook_id: str) -> WebhookSubscription:
        obj = await self.repo.get(webhook_id)
        if obj is None:
            raise NotFoundError(f"Webhook {webhook_id} not found")
        return obj

    async def update(
        self, webhook_id: str, data: WebhookUpdate
    ) -> WebhookSubscription:
        obj = await self.get(webhook_id)
        payload = data.model_dump(exclude_unset=True)
        return await self.repo.update(obj, payload)

    async def delete(self, webhook_id: str) -> None:
        obj = await self.get(webhook_id)
        await self.repo.delete(obj)

    async def test(self, webhook_id: str) -> dict:
        """Send a synthetic ping and report delivery success."""
        obj = await self.get(webhook_id)
        ok = await _deliver(
            obj,
            "experiment.completed",
            {
                "event": "ping",
                "experiment_id": None,
                "status": "ping",
                "accuracy": 0.0,
                "total_cost": 0.0,
                "total_tokens": 0,
                "project_id": obj.project_id,
                "runtime_ms": 0,
            },
        )
        return {"delivered": ok}


def get_webhook_service(
    session: AsyncSession = Depends(get_session),
) -> WebhookService:
    return WebhookService(session)
