"""Model Center service — business logic for the Model Center module."""
from __future__ import annotations

from fastapi import Depends
import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.core.exceptions import ConflictError, NotFoundError
from app.core.config import settings
from app.models.model import Model
from app.repositories.experiment import ExperimentRepository
from app.repositories.model import ModelRepository
from app.schemas.model import ModelCreate, ModelUpdate


_DEFAULT_MODELS: list[dict] = [
    {
        "name": "GPT-4o mini",
        "provider": "openai",
        "model_id": "openai/gpt-4o-mini",
        "context_length": 128000,
        "pricing": {"input_per_1k": 0.15, "output_per_1k": 0.6},
        "capabilities": ["chat", "coding"],
    },
    {
        "name": "GPT-4o",
        "provider": "openai",
        "model_id": "openai/gpt-4o",
        "context_length": 128000,
        "pricing": {"input_per_1k": 2.5, "output_per_1k": 10},
        "capabilities": ["chat", "coding", "reasoning"],
    },
    {
        "name": "Claude 3.5 Sonnet",
        "provider": "anthropic",
        "model_id": "anthropic/claude-3.5-sonnet",
        "context_length": 200000,
        "pricing": {"input_per_1k": 3, "output_per_1k": 15},
        "capabilities": ["chat", "coding", "reasoning"],
    },
    {
        "name": "Claude 3.5 Haiku",
        "provider": "anthropic",
        "model_id": "anthropic/claude-3.5-haiku",
        "context_length": 200000,
        "pricing": {"input_per_1k": 0.8, "output_per_1k": 4},
        "capabilities": ["chat", "coding"],
    },
    {
        "name": "Gemini 1.5 Pro",
        "provider": "google",
        "model_id": "google/gemini-pro-1.5",
        "context_length": 2000000,
        "pricing": {"input_per_1k": 1.25, "output_per_1k": 5},
        "capabilities": ["chat", "reasoning"],
    },
    {
        "name": "DeepSeek V3",
        "provider": "deepseek",
        "model_id": "deepseek/deepseek-chat",
        "context_length": 64000,
        "pricing": {"input_per_1k": 0.14, "output_per_1k": 0.28},
        "capabilities": ["chat", "coding"],
    },
    {
        "name": "Qwen 2.5 72B",
        "provider": "qwen",
        "model_id": "qwen/qwen-2.5-72b-instruct",
        "context_length": 32000,
        "pricing": {"input_per_1k": 0.35, "output_per_1k": 0.4},
        "capabilities": ["chat", "coding"],
    },
    {
        "name": "GLM-4",
        "provider": "zhipu",
        "model_id": "zhipuai/glm-4",
        "context_length": 128000,
        "pricing": {"input_per_1k": 0.5, "output_per_1k": 0.5},
        "capabilities": ["chat"],
    },
]


class ModelService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = ModelRepository(session)

    async def create(self, data: ModelCreate) -> Model:
        obj = Model(
            name=data.name,
            provider=data.provider,
            model_id=data.model_id,
            context_length=data.context_length,
            pricing=data.pricing,
            capabilities=data.capabilities,
            is_active=data.is_active,
        )
        return await self.repo.create(obj)

    async def get(self, model_pk: str) -> Model:
        obj = await self.repo.get(model_pk)
        if obj is None:
            raise NotFoundError(f"Model {model_pk} not found")
        return obj

    async def list(
        self,
        *,
        provider: str | None = None,
        is_active: bool | None = None,
        q: str | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> list[Model]:
        stmt = select(Model)
        if provider is not None:
            stmt = stmt.where(Model.provider == provider)
        if is_active is not None:
            stmt = stmt.where(Model.is_active == is_active)
        if q:
            stmt = stmt.where(Model.name.ilike(f"%{q}%"))
        stmt = stmt.order_by(Model.created_at.desc())
        stmt = stmt.offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def count(
        self,
        *,
        provider: str | None = None,
        is_active: bool | None = None,
        q: str | None = None,
    ) -> int:
        if q:
            from sqlalchemy import func

            stmt = select(func.count()).select_from(Model)
            if provider is not None:
                stmt = stmt.where(Model.provider == provider)
            if is_active is not None:
                stmt = stmt.where(Model.is_active == is_active)
            stmt = stmt.where(Model.name.ilike(f"%{q}%"))
            result = await self.session.execute(stmt)
            return int(result.scalar_one())
        return await self.repo.count(
            filters={"provider": provider, "is_active": is_active}
        )

    async def update(self, model_pk: str, data: ModelUpdate) -> Model:
        obj = await self.get(model_pk)
        payload = data.model_dump(exclude_unset=True)
        return await self.repo.update(obj, payload)

    async def delete(self, model_pk: str) -> None:
        obj = await self.get(model_pk)
        references = await ExperimentRepository(self.session).count_by_component(
            model_id=model_pk
        )
        if references:
            raise ConflictError(
                f"Model is referenced by {references} experiment(s); "
                "delete those experiments first"
            )
        await self.repo.delete(obj)

    async def delete_many(self, ids: list[str] | None = None) -> int:
        """Delete the given models (or all models when `ids` is empty/None).

        Refuses the whole operation if any target model is still referenced by
        an experiment, so a bulk "delete all" cannot silently break history.
        """
        targets = ids if ids else [m.id for m in await self.list(limit=100_000)]
        for model_pk in targets:
            references = await ExperimentRepository(self.session).count_by_component(
                model_id=model_pk
            )
            if references:
                raise ConflictError(
                    f"Model {model_pk} is referenced by {references} experiment(s); "
                    "delete those experiments first"
                )
        return await self.repo.delete_many(ids)

    async def list_presets(self) -> list[dict]:
        """Catalog of built-in models available to add individually."""
        return [dict(spec) for spec in _DEFAULT_MODELS]

    async def list_qiniu_models(self) -> list[dict]:
        """Live Qiniu Cloud AI model catalog (requires API key).

        Qiniu exposes an OpenAI-compatible GET /v1/models that returns the real
        model ids available on the account. Unlike OpenRouter it does not include
        pricing/context_length, so those fields are left at defaults and can be
        edited after the model is added. Returns an empty list when no key is set.
        """
        if not settings.qiniu_api_key.strip():
            return []
        url = f"{settings.qiniu_base_url.rstrip('/')}/models"
        headers = {"Authorization": f"Bearer {settings.qiniu_api_key}"}
        async with httpx.AsyncClient(timeout=settings.eval_request_timeout) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            payload = resp.json()

        out: list[dict] = []
        for m in payload.get("data", []):
            mid = m.get("id")
            if not mid:
                continue
            out.append(
                {
                    "id": mid,
                    "name": m.get("id") or mid,
                    "owned_by": m.get("owned_by") or "qiniu",
                }
            )
        # Stable dropdown order by id.
        return sorted(out, key=lambda x: (x["id"] or "").lower())

    async def list_openrouter_models(self) -> list[dict]:
        """Live OpenRouter model catalog.

        OpenRouter exposes a public /models endpoint (no API key needed). We map
        its per-token pricing to our per-1K-token schema so added models slot
        straight into the existing ModelCreate shape.
        """
        url = f"{settings.openrouter_base_url.rstrip('/')}/models"
        headers = {
            "HTTP-Referer": settings.openrouter_http_referer,
            "X-Title": settings.openrouter_app_title,
        }
        async with httpx.AsyncClient(timeout=settings.eval_request_timeout) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            payload = resp.json()

        out: list[dict] = []
        for m in payload.get("data", []):
            pricing = m.get("pricing") or {}
            try:
                in_1k = float(pricing.get("prompt", 0)) * 1000
                out_1k = float(pricing.get("completion", 0)) * 1000
            except (TypeError, ValueError):
                in_1k = out_1k = 0.0
            out.append(
                {
                    "id": m.get("id"),
                    "name": m.get("name") or m.get("id"),
                    "context_length": m.get("context_length"),
                    "pricing": {
                        "input_per_1k": round(in_1k, 8),
                        "output_per_1k": round(out_1k, 8),
                    },
                    "architecture": (m.get("architecture") or {}).get("modality", ""),
                }
            )
        # Sort by name for a stable dropdown.
        return sorted(out, key=lambda x: (x["name"] or "").lower())

    async def seed_defaults(self) -> int:
        seeded = 0
        for spec in _DEFAULT_MODELS:
            obj = Model(
                name=spec["name"],
                provider=spec["provider"],
                model_id=spec["model_id"],
                context_length=spec["context_length"],
                pricing=spec["pricing"],
                capabilities=spec["capabilities"],
            )
            await self.repo.create(obj)
            seeded += 1
        return seeded


def get_model_service(session: AsyncSession = Depends(get_session)) -> ModelService:
    return ModelService(session)
