"""Business logic for organizations and scoped API keys."""
from __future__ import annotations

import secrets

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.core.exceptions import ForbiddenError, NotFoundError, ValidationError
from app.core.security import _hash_key
from app.core.tenant import TenantContext
from app.models.organization import ApiKey, Organization
from app.repositories.organization import ApiKeyRepository, OrganizationRepository
from app.schemas.organization import (
    ApiKeyCreate,
    ApiKeyCreated,
    ApiKeyRead,
    OrganizationCreate,
    OrganizationRead,
    OrganizationUpdate,
    OrganizationWithKey,
)

_KEY_PREFIX = "bmops_"


def _generate_key() -> str:
    return _KEY_PREFIX + secrets.token_urlsafe(32)


class OrganizationService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.organizations = OrganizationRepository(session)
        self.api_keys = ApiKeyRepository(session)

    async def create_organization(
        self, data: OrganizationCreate
    ) -> OrganizationWithKey:
        org = Organization(name=data.name, description=data.description)
        org = await self.organizations.create(org)
        raw_key = _generate_key()
        key = ApiKey(
            organization_id=org.id,
            name="owner",
            key_hash=_hash_key(raw_key),
            key_prefix=raw_key[:8],
            role="owner",
            is_active=True,
        )
        key = await self.api_keys.create(key)
        await self.session.commit()
        base = ApiKeyRead.model_validate(key)
        return OrganizationWithKey(
            organization=OrganizationRead.model_validate(org),
            api_key=ApiKeyCreated(**base.model_dump(), key=raw_key),
        )

    async def get_organization(self, org_id: str) -> Organization:
        org = await self.organizations.get(org_id)
        if org is None:
            raise NotFoundError(f"Organization {org_id} not found")
        return org

    async def update_organization(
        self, org_id: str, data: OrganizationUpdate
    ) -> Organization:
        org = await self.get_organization(org_id)
        payload = data.model_dump(exclude_unset=True)
        return await self.organizations.update(org, payload)

    async def create_api_key(
        self, org_id: str, data: ApiKeyCreate, actor: TenantContext
    ) -> ApiKeyCreated:
        if actor.organization_id != org_id:
            raise ForbiddenError("Cannot manage another organization's keys")
        raw_key = _generate_key()
        key = ApiKey(
            organization_id=org_id,
            name=data.name,
            key_hash=_hash_key(raw_key),
            key_prefix=raw_key[:8],
            role=data.role,
            is_active=True,
        )
        key = await self.api_keys.create(key)
        await self.session.commit()
        base = ApiKeyRead.model_validate(key)
        return ApiKeyCreated(**base.model_dump(), key=raw_key)

    async def list_api_keys(self, org_id: str, actor: TenantContext) -> list[ApiKey]:
        if actor.organization_id != org_id:
            raise ForbiddenError("Cannot list another organization's keys")
        result = await self.session.execute(
            select(ApiKey)
            .where(ApiKey.organization_id == org_id)
            .order_by(ApiKey.created_at.desc())
        )
        return list(result.scalars().all())

    async def revoke_api_key(
        self, org_id: str, key_id: str, actor: TenantContext
    ) -> None:
        if actor.organization_id != org_id:
            raise ForbiddenError("Cannot revoke another organization's keys")
        key = await self.api_keys.get(key_id)
        if key is None or key.organization_id != org_id:
            raise NotFoundError(f"API key {key_id} not found")
        if key.id == actor.key_id:
            raise ValidationError("Cannot revoke the key used for this request")
        if key.role == "owner":
            owners = await self.session.execute(
                select(ApiKey).where(
                    ApiKey.organization_id == org_id,
                    ApiKey.role == "owner",
                    ApiKey.is_active.is_(True),
                )
            )
            if len(list(owners.scalars().all())) <= 1:
                raise ValidationError("Cannot revoke the last active owner key")
        key.is_active = False
        await self.session.commit()


def get_organization_service(
    session: AsyncSession = Depends(get_session),
) -> OrganizationService:
    return OrganizationService(session)
