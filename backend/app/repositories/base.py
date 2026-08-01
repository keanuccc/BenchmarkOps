"""Generic async repository.

Encapsulates all direct ORM/session access. Services depend on repositories, not
on Session — so the persistence backend is swappable without touching business
logic. Concrete repositories subclass this and add domain-specific queries.
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Generic, TypeVar

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import Base

ModelT = TypeVar("ModelT", bound=Base)


class BaseRepository(Generic[ModelT]):
    model: type[ModelT]

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(self, id: str) -> ModelT | None:
        return await self.session.get(self.model, id)

    async def list(
        self,
        *,
        offset: int = 0,
        limit: int = 100,
        filters: dict[str, Any] | None = None,
        order_by: Any | None = None,
        search: str | None = None,
    ) -> Sequence[ModelT]:
        stmt = select(self.model)
        if filters:
            for field, value in filters.items():
                # Treat an empty string like None: callers that send
                # ``?project_id=`` (or similar) mean "no filter", and filtering
                # on an empty id would silently return zero rows.
                if value:
                    stmt = stmt.where(getattr(self.model, field) == value)
        if search:
            # Models used by list endpoints expose a ``name`` column; subclasses
            # that don't (e.g. Report) implement their own search in the service.
            stmt = stmt.where(self.model.name.ilike(f"%{search}%"))
        stmt = stmt.order_by(order_by if order_by is not None else self.model.created_at.desc())
        stmt = stmt.offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def count(
        self,
        *,
        filters: dict[str, Any] | None = None,
        search: str | None = None,
    ) -> int:
        stmt = select(func.count()).select_from(self.model)
        if filters:
            for field, value in filters.items():
                if value:
                    stmt = stmt.where(getattr(self.model, field) == value)
        if search:
            stmt = stmt.where(self.model.name.ilike(f"%{search}%"))
        result = await self.session.execute(stmt)
        return int(result.scalar_one())

    async def create(self, obj: ModelT) -> ModelT:
        self.session.add(obj)
        await self.session.flush()
        await self.session.refresh(obj)
        return obj

    async def update(self, obj: ModelT, data: dict[str, Any]) -> ModelT:
        for field, value in data.items():
            setattr(obj, field, value)
        await self.session.flush()
        await self.session.refresh(obj)
        return obj

    async def delete(self, obj: ModelT) -> None:
        await self.session.delete(obj)
        await self.session.flush()
