"""Benchmark repository."""
from __future__ import annotations

from app.models.benchmark import Benchmark
from app.repositories.base import BaseRepository


class BenchmarkRepository(BaseRepository[Benchmark]):
    model = Benchmark
