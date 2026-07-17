"""Repository for the Prompt Library module."""
from __future__ import annotations

from app.models.prompt import Prompt
from app.repositories.base import BaseRepository


class PromptRepository(BaseRepository[Prompt]):
    model = Prompt
