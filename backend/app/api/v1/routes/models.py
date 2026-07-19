"""Model Center CRUD endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.core.security import require_auth
from app.schemas.model import ModelCreate, ModelRead, ModelUpdate
from app.services.model_service import ModelService, get_model_service

router = APIRouter(prefix="/models", tags=["models"])


class ModelBulkDelete(BaseModel):
    ids: list[str] = []


@router.post("/", response_model=ModelRead, status_code=201)
async def create_model(
    data: ModelCreate,
    service: ModelService = Depends(get_model_service),
    _: None = Depends(require_auth),
) -> ModelRead:
    return await service.create(data)


@router.get("/presets")
async def list_presets(
    service: ModelService = Depends(get_model_service),
) -> list[dict]:
    """Built-in model catalog for one-click add (no auth needed)."""
    return await service.list_presets()


@router.get("/", response_model=list[ModelRead])
async def list_models(
    provider: str | None = None,
    is_active: bool | None = None,
    offset: int = 0,
    limit: int = 100,
    service: ModelService = Depends(get_model_service),
) -> list[ModelRead]:
    return await service.list(provider=provider, is_active=is_active, offset=offset, limit=limit)


@router.get("/openrouter")
async def list_openrouter_models(
    service: ModelService = Depends(get_model_service),
) -> list[dict]:
    """Live catalog of models available on OpenRouter (no API key required)."""
    return await service.list_openrouter_models()


@router.delete("/bulk", status_code=200)
async def bulk_delete_models(
    payload: ModelBulkDelete,
    service: ModelService = Depends(get_model_service),
    _: None = Depends(require_auth),
) -> dict:
    """Delete the given models. With an empty `ids` list, deletes ALL models."""
    deleted = await service.delete_many(payload.ids or None)
    return {"deleted": deleted}


@router.get("/{model_pk}", response_model=ModelRead)
async def get_model(
    model_pk: str,
    service: ModelService = Depends(get_model_service),
) -> ModelRead:
    return await service.get(model_pk)


@router.patch("/{model_pk}", response_model=ModelRead)
async def update_model(
    model_pk: str,
    data: ModelUpdate,
    service: ModelService = Depends(get_model_service),
    _: None = Depends(require_auth),
) -> ModelRead:
    return await service.update(model_pk, data)


@router.delete("/{model_pk}", status_code=204)
async def delete_model(
    model_pk: str,
    service: ModelService = Depends(get_model_service),
    _: None = Depends(require_auth),
) -> None:
    await service.delete(model_pk)


@router.post("/seed")
async def seed_models(
    service: ModelService = Depends(get_model_service),
    _: None = Depends(require_auth),
) -> dict:
    seeded = await service.seed_defaults()
    return {"seeded": seeded}
