"""Organization and API-key management endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.core.security import require_auth, require_org_admin, require_org_auth
from app.core.tenant import TenantContext
from app.schemas.organization import (
    ApiKeyCreate,
    ApiKeyCreated,
    ApiKeyRead,
    OrganizationCreate,
    OrganizationRead,
    OrganizationUpdate,
    OrganizationWithKey,
)
from app.services.organization_service import (
    OrganizationService,
    get_organization_service,
)

router = APIRouter(prefix="/organizations", tags=["organizations"])


@router.post("/", response_model=OrganizationWithKey, status_code=201)
async def create_organization(
    data: OrganizationCreate,
    service: OrganizationService = Depends(get_organization_service),
    _: None = Depends(require_auth),
) -> OrganizationWithKey:
    """Create an organization and return its first (owner) API key."""
    return await service.create_organization(data)


@router.get("/me", response_model=OrganizationRead)
async def get_my_organization(
    auth: TenantContext = Depends(require_org_auth),
    service: OrganizationService = Depends(get_organization_service),
) -> OrganizationRead:
    org = await service.get_organization(auth.organization_id)
    return OrganizationRead.model_validate(org)


@router.patch("/{org_id}", response_model=OrganizationRead)
async def update_organization(
    org_id: str,
    data: OrganizationUpdate,
    auth: TenantContext = Depends(require_org_admin),
    service: OrganizationService = Depends(get_organization_service),
) -> OrganizationRead:
    org = await service.update_organization(org_id, data)
    return OrganizationRead.model_validate(org)


@router.post("/{org_id}/api-keys", response_model=ApiKeyCreated, status_code=201)
async def create_api_key(
    org_id: str,
    data: ApiKeyCreate,
    auth: TenantContext = Depends(require_org_admin),
    service: OrganizationService = Depends(get_organization_service),
) -> ApiKeyCreated:
    return await service.create_api_key(org_id, data, auth)


@router.get("/{org_id}/api-keys", response_model=list[ApiKeyRead])
async def list_api_keys(
    org_id: str,
    auth: TenantContext = Depends(require_org_admin),
    service: OrganizationService = Depends(get_organization_service),
) -> list[ApiKeyRead]:
    keys = await service.list_api_keys(org_id, auth)
    return [ApiKeyRead.model_validate(k) for k in keys]


@router.delete("/{org_id}/api-keys/{key_id}", status_code=204, response_model=None)
async def revoke_api_key(
    org_id: str,
    key_id: str,
    auth: TenantContext = Depends(require_org_admin),
    service: OrganizationService = Depends(get_organization_service),
) -> None:
    await service.revoke_api_key(org_id, key_id, auth)
