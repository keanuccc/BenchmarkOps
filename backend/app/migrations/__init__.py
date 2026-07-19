"""Lightweight, zero-dependency async database migration mechanism.

This is a minimal replacement for Alembic, intentionally kept tiny:
- No external dependencies.
- Frame work table `schema_version` is managed with raw `conn.execute`
  (never registered on the ORM `Base`, so `create_all` cannot touch it).
- Migrations are plain `async def upgrade(conn)` coroutines registered in
  `MIGRATIONS` below, keyed by an increasing integer version.

Usage for future schema changes
---------------------------------
1. Add an `async def upgrade(conn)` that performs the ALTER (create table,
   add column, change type, create index, etc.) using the raw connection:

       async def upgrade_add_foo(conn) -> None:
           await conn.execute(
               sa.text("ALTER TABLE bar ADD COLUMN foo TEXT")
           )

2. Register it in `MIGRATIONS` with the next version number, e.g.:

       MIGRATIONS[3] = upgrade_add_foo

`run_migrations` is idempotent: it records each applied version in
`schema_version` and skips any version already applied, so it is safe to
call on every startup (and harmless to call twice).
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

# A migration is an async function that receives a raw async connection.
MigrationFn = Callable[[sa.ext.asyncio.AsyncConnection], Awaitable[None]]

# Ordered registry of migrations, keyed by an increasing integer version.
# The baseline (create_all) is implicit version 0 and is NOT registered here.
# To add a migration: MIGRATIONS[N] = your_upgrade_function
MIGRATIONS: dict[int, MigrationFn] = {}


async def _upgrade_experiment_snapshot_and_metrics(conn) -> None:  # type: ignore[no-untyped-def]
    """Add experiment snapshot / progress / materialized-metric columns.

    Safe to re-run: each ALTER is guarded so it only executes against a column
    that does not already exist in the experiments table.
    """
    cols = {
        "prompt_snapshot": "TEXT",
        "benchmark_snapshot": "TEXT",
        "model_snapshot": "TEXT",
        "progress": "INTEGER NOT NULL DEFAULT 0",
        "rows_total": "INTEGER",
        "accuracy": "FLOAT NOT NULL DEFAULT 0.0",
        "avg_latency_ms": "FLOAT NOT NULL DEFAULT 0.0",
    }
    existing = {
        r[1]
        for r in await conn.execute(sa.text("PRAGMA table_info(experiments)"))
        if r and len(r) > 1
    }
    for col, dtype in cols.items():
        if col not in existing:
            await conn.execute(
                sa.text(f"ALTER TABLE experiments ADD COLUMN {col} {dtype}")
            )


MIGRATIONS[10] = _upgrade_experiment_snapshot_and_metrics


async def _upgrade_experiment_progress_cells(conn) -> None:  # type: ignore[no-untyped-def]
    """Add per-cell progress counters (cells_done / cells_error) to experiments.

    Drives the three-segment progress bar shown while a run is in flight
    (scored vs failed vs total). Idempotent: the ALTER only runs for columns
    that are not already present.
    """
    cols = {
        "cells_done": "INTEGER NOT NULL DEFAULT 0",
        "cells_error": "INTEGER NOT NULL DEFAULT 0",
    }
    existing = {
        r[1]
        for r in await conn.execute(sa.text("PRAGMA table_info(experiments)"))
        if r and len(r) > 1
    }
    for col, dtype in cols.items():
        if col not in existing:
            await conn.execute(
                sa.text(f"ALTER TABLE experiments ADD COLUMN {col} {dtype}")
            )


MIGRATIONS[11] = _upgrade_experiment_progress_cells


async def _ensure_version_table(conn: sa.ext.asyncio.AsyncConnection) -> None:
    """Create the framework `schema_version` table if it does not exist."""
    await conn.execute(
        sa.text(
            """
            CREATE TABLE IF NOT EXISTS schema_version (
                version INTEGER PRIMARY KEY,
                applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
    )


async def _applied_versions(conn: sa.ext.asyncio.AsyncConnection) -> set[int]:
    """Return the set of version numbers already recorded as applied."""
    result = await conn.execute(sa.text("SELECT version FROM schema_version"))
    return {row[0] for row in result.fetchall()}


async def run_migrations(engine: AsyncEngine) -> None:
    """Apply all pending migrations in version order, idempotently.

    Already-applied versions (recorded in `schema_version`) are skipped, so
    this is safe to call on every startup and harmless to call twice.
    """
    async with engine.begin() as conn:
        await _ensure_version_table(conn)
        applied = await _applied_versions(conn)

        for version in sorted(MIGRATIONS):
            if version in applied:
                continue
            upgrade = MIGRATIONS[version]
            await upgrade(conn)
            await conn.execute(
                sa.text("INSERT INTO schema_version (version) VALUES (:v)"),
                {"v": version},
            )
