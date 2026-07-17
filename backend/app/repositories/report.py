"""Repository for the AI Report module."""
from __future__ import annotations

from app.models.report import Report
from app.repositories.base import BaseRepository


class ReportRepository(BaseRepository[Report]):
    model = Report
