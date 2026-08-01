"""Project CRUD endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.core.security import require_auth
from app.schemas.common import ListResponse
from app.schemas.project import ProjectCreate, ProjectRead, ProjectUpdate
from app.services.project_service import ProjectService, get_project_service

router = APIRouter(prefix="/projects", tags=["projects"])


@router.post("/", response_model=ProjectRead, status_code=201)
async def create_project(
    data: ProjectCreate,
    service: ProjectService = Depends(get_project_service),
    _: None = Depends(require_auth),
) -> ProjectRead:
    return await service.create(data)


@router.get("/", response_model=ListResponse[ProjectRead])
async def list_projects(
    status: str | None = None,
    q: str | None = None,
    offset: int = 0,
    limit: int = 100,
    service: ProjectService = Depends(get_project_service),
) -> ListResponse[ProjectRead]:
    items = await service.list(status=status, q=q, offset=offset, limit=limit)
    total = await service.count(status=status, q=q)
    return ListResponse[ProjectRead](items=items, total=total)


@router.get("/{project_id}", response_model=ProjectRead)
async def get_project(
    project_id: str,
    service: ProjectService = Depends(get_project_service),
) -> ProjectRead:
    return await service.get(project_id)


@router.patch("/{project_id}", response_model=ProjectRead)
async def update_project(
    project_id: str,
    data: ProjectUpdate,
    service: ProjectService = Depends(get_project_service),
    _: None = Depends(require_auth),
) -> ProjectRead:
    return await service.update(project_id, data)


@router.post("/{project_id}/archive", response_model=ProjectRead)
async def archive_project(
    project_id: str,
    service: ProjectService = Depends(get_project_service),
    _: None = Depends(require_auth),
) -> ProjectRead:
    return await service.archive(project_id)


@router.delete("/{project_id}", status_code=204, response_model=None)
async def delete_project(
    project_id: str,
    service: ProjectService = Depends(get_project_service),
    _: None = Depends(require_auth),
) -> None:
    await service.delete(project_id)
