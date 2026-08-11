"""Repository for webhook subscriptions."""
from __future__ import annotations

from app.models.webhook import WebhookSubscription
from app.repositories.base import BaseRepository


class WebhookRepository(BaseRepository[WebhookSubscription]):
    model = WebhookSubscription
