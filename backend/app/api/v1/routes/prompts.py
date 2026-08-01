"""Prompt Library API routes."""
from __future__ import annotations

from typing import Sequence

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.core.security import require_auth
from app.schemas.common import ListResponse
from app.schemas.prompt import PromptCreate, PromptRead, PromptUpdate
from app.services.prompt_service import PromptService, get_prompt_service

router = APIRouter(prefix="/prompts", tags=["prompts"])


@router.post("/", response_model=PromptRead)
async def create_prompt(
    data: PromptCreate,
    service: PromptService = Depends(get_prompt_service),
    _: None = Depends(require_auth),
) -> Prompt:
    return await service.create(
        project_id=data.project_id,
        name=data.name,
        template=data.template,
        description=data.description,
    )


@router.get("/", response_model=ListResponse[PromptRead])
async def list_prompts(
    project_id: str | None = Query(None),
    q: str | None = Query(None),
    offset: int = Query(0),
    limit: int = Query(100),
    service: PromptService = Depends(get_prompt_service),
) -> ListResponse[PromptRead]:
    items = await service.list(project_id=project_id, q=q, offset=offset, limit=limit)
    total = await service.count(project_id=project_id, q=q)
    return ListResponse[PromptRead](items=items, total=total)


@router.get("/{prompt_id}", response_model=PromptRead)
async def get_prompt(
    prompt_id: str,
    service: PromptService = Depends(get_prompt_service),
) -> Prompt:
    return await service.get(prompt_id)


@router.patch("/{prompt_id}", response_model=PromptRead)
async def update_prompt(
    prompt_id: str,
    data: PromptUpdate,
    service: PromptService = Depends(get_prompt_service),
    _: None = Depends(require_auth),
) -> Prompt:
    return await service.update(prompt_id, data)


@router.delete("/{prompt_id}", status_code=204, response_model=None)
async def delete_prompt(
    prompt_id: str,
    service: PromptService = Depends(get_prompt_service),
    _: None = Depends(require_auth),
) -> None:
    await service.delete(prompt_id)


@router.post("/{prompt_id}/render", response_model=dict)
async def render_prompt(
    prompt_id: str,
    body: dict,
    service: PromptService = Depends(get_prompt_service),
    _: None = Depends(require_auth),
) -> dict:
    variables = body.get("variables", {})
    rendered = await service.render(prompt_id, variables)
    return {"rendered": rendered}
