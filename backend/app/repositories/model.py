"""Model Center repository."""
from __future__ import annotations

from sqlalchemy import delete

from app.models.model import Model
from app.repositories.base import BaseRepository


class ModelRepository(BaseRepository[Model]):
    model = Model

    async def delete_many(self, ids: list[str] | None = None) -> int:
        """Delete models by id. When `ids` is None/empty, deletes all models.

        Returns the number of rows deleted.
        """
        stmt = delete(Model)
        if ids:
            stmt = stmt.where(Model.id.in_(ids))
        result = await self.session.execute(stmt)
        await self.session.flush()
        return result.rowcount
