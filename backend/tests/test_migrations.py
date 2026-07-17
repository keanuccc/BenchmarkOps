"""Tests for the zero-dependency migration mechanism.

These verify that `run_migrations` is idempotent and that the framework
`schema_version` table is created and tracks applied versions.

The tests use a private throwaway DB (not the session-shared test DB) so they
stay isolated from other tests that run the real migrations (e.g. the v10
experiment column migration applied by the app's `init_db`).
"""
from __future__ import annotations

import os
import tempfile
import uuid

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.migrations import MIGRATIONS, run_migrations


def _snapshot_migrations() -> dict[int, object]:
    """Return a copy of the global registry so we can mutate it safely."""
    return dict(MIGRATIONS)


def _make_engine():
    path = os.path.join(
        tempfile.gettempdir(), f"benchmarkops_migtest_{uuid.uuid4().hex}.db"
    )
    return create_async_engine(f"sqlite+aiosqlite:///{path}", future=True)


async def test_schema_version_table_created_and_idempotent() -> None:
    """run_migrations creates schema_version and is safe to call twice."""
    original = _snapshot_migrations()
    engine = _make_engine()
    MIGRATIONS.clear()
    try:
        await run_migrations(engine)
        await run_migrations(engine)  # must be idempotent

        async with engine.begin() as conn:
            result = await conn.execute(
                sa.text("SELECT name FROM sqlite_master WHERE name = 'schema_version'")
            )
            assert result.fetchone() is not None

            rows = await conn.execute(sa.text("SELECT version FROM schema_version"))
            assert rows.fetchall() == []
    finally:
        await engine.dispose()
        MIGRATIONS.clear()
        MIGRATIONS.update(original)


async def test_registered_migration_applied_once() -> None:
    """A registered migration runs exactly once even across multiple runs."""
    original = _snapshot_migrations()
    engine = _make_engine()
    MIGRATIONS.clear()
    try:
        marker: dict[str, int] = {"n": 0}

        async def upgrade_marker(conn) -> None:  # type: ignore[no-untyped-def]
            marker["n"] += 1
            await conn.execute(
                sa.text("CREATE TABLE IF NOT EXISTS _mtest (id INTEGER PRIMARY KEY)")
            )

        MIGRATIONS[1] = upgrade_marker

        await run_migrations(engine)
        await run_migrations(engine)  # idempotent re-run
        await run_migrations(engine)  # yet another re-run

        assert marker["n"] == 1

        async with engine.begin() as conn:
            rows = await conn.execute(sa.text("SELECT version FROM schema_version"))
            versions = sorted(r[0] for r in rows.fetchall())
            assert versions == [1]
    finally:
        await engine.dispose()
        MIGRATIONS.clear()
        MIGRATIONS.update(original)
