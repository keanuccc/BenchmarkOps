"""Webhook subscription endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.core.security import require_auth
from app.schemas.webhook import WebhookCreate, WebhookRead, WebhookUpdate
from app.services.webhook_service import WebhookService, get_webhook_service

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post("/", response_model=WebhookRead, status_code=201)
async def create_webhook(
    data: WebhookCreate,
    service: WebhookService = Depends(get_webhook_service),
    _: None = Depends(require_auth),
):
    return await service.create(data)


@router.get("/", response_model=list[WebhookRead])
async def list_webhooks(
    project_id: str,
    service: WebhookService = Depends(get_webhook_service),
):
    return await service.list(project_id)


@router.get("/{webhook_id}", response_model=WebhookRead)
async def get_webhook(
    webhook_id: str,
    service: WebhookService = Depends(get_webhook_service),
):
    return await service.get(webhook_id)


@router.patch("/{webhook_id}", response_model=WebhookRead)
async def update_webhook(
    webhook_id: str,
    data: WebhookUpdate,
    service: WebhookService = Depends(get_webhook_service),
    _: None = Depends(require_auth),
):
    return await service.update(webhook_id, data)


@router.delete("/{webhook_id}", status_code=204, response_model=None)
async def delete_webhook(
    webhook_id: str,
    service: WebhookService = Depends(get_webhook_service),
    _: None = Depends(require_auth),
):
    await service.delete(webhook_id)


@router.post("/{webhook_id}/test", response_model=dict)
async def test_webhook(
    webhook_id: str,
    service: WebhookService = Depends(get_webhook_service),
    _: None = Depends(require_auth),
):
    return await service.test(webhook_id)
