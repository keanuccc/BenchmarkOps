"""Repositories for organizations and API keys."""
from __future__ import annotations

from app.models.organization import ApiKey, Organization
from app.repositories.base import BaseRepository


class OrganizationRepository(BaseRepository[Organization]):
    model = Organization


class ApiKeyRepository(BaseRepository[ApiKey]):
    model = ApiKey
