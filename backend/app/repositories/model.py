"""Model Center repository."""
from __future__ import annotations

from app.models.model import Model
from app.repositories.base import BaseRepository


class ModelRepository(BaseRepository[Model]):
    model = Model
