"""Pytest fixtures.

We set DATABASE_URL to a throwaway temp file *before* the app (and its database
module) are imported, so the app builds its engine against the test DB. This avoids
fragile module reloading. Requires that no test imports app.* at collection time.
"""
from __future__ import annotations

import os
import tempfile
import uuid

import pytest

# Point at a unique temp DB for the whole test session, before app import.
_TMP_DB = os.path.join(tempfile.gettempdir(), f"benchmarkops_test_{uuid.uuid4().hex}.db")
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TMP_DB}"
# Distributed-queue tests use a dedicated Redis logical DB so they never touch
# whatever is stored in the default DB 0. Set before app import so Settings
# picks it up; tests skip when Redis is unreachable.
os.environ.setdefault("REDIS_DSN", "redis://localhost:6379/15")


@pytest.fixture(scope="session", autouse=True)
def _init_test_db():
    """Create tables + run migrations once before any test (async tests rely on it)."""
    import asyncio

    from app.core.database import init_db

    asyncio.run(init_db())
    yield


@pytest.fixture()
def client():
    from starlette.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c


def pytest_sessionfinish(session, exitstatus):  # noqa: ARG001
    try:
        if os.path.exists(_TMP_DB):
            os.remove(_TMP_DB)
    except OSError:
        pass
