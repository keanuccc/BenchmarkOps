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


async def _table_columns(conn, table_name: str) -> set[str]:  # type: ignore[no-untyped-def]
    """Inspect columns through SQLAlchemy so migrations work on SQLite and PostgreSQL."""
    return await conn.run_sync(
        lambda sync_conn: {
            column["name"]
            for column in sa.inspect(sync_conn).get_columns(table_name)
        }
    )


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
    existing = await _table_columns(conn, "experiments")
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
    existing = await _table_columns(conn, "experiments")
    for col, dtype in cols.items():
        if col not in existing:
            await conn.execute(
                sa.text(f"ALTER TABLE experiments ADD COLUMN {col} {dtype}")
            )


MIGRATIONS[11] = _upgrade_experiment_progress_cells


async def _upgrade_experiment_result_diagnostics(conn) -> None:  # type: ignore[no-untyped-def]
    """Add row-level scoring diagnostics to experiment_results."""
    cols = {
        "cleaned_prediction": "TEXT",
        "expected_canonical": "TEXT",
        "score_reason": "TEXT",
    }
    existing = await _table_columns(conn, "experiment_results")
    for col, dtype in cols.items():
        if col not in existing:
            await conn.execute(
                sa.text(f"ALTER TABLE experiment_results ADD COLUMN {col} {dtype}")
            )


MIGRATIONS[12] = _upgrade_experiment_result_diagnostics


async def _upgrade_dataset_contract_columns(conn) -> None:  # type: ignore[no-untyped-def]
    """Add lightweight dataset contract/import metadata columns."""
    cols = {
        "task_type": "VARCHAR(50) NOT NULL DEFAULT 'qa'",
        "field_mapping": "JSON NOT NULL DEFAULT '{}'",
        "contract": "JSON NOT NULL DEFAULT '{}'",
        "source_filename": "TEXT",
        "content_hash": "VARCHAR(64)",
        "import_status": "VARCHAR(20) NOT NULL DEFAULT 'ready'",
        "import_errors": "JSON NOT NULL DEFAULT '[]'",
        "schema_version": "INTEGER NOT NULL DEFAULT 1",
    }
    existing = await _table_columns(conn, "datasets")
    for col, dtype in cols.items():
        if col not in existing:
            await conn.execute(sa.text(f"ALTER TABLE datasets ADD COLUMN {col} {dtype}"))
    await conn.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS ix_datasets_content_hash "
            "ON datasets (content_hash)"
        )
    )


MIGRATIONS[13] = _upgrade_dataset_contract_columns


async def _upgrade_experiment_dataset_snapshot(conn) -> None:  # type: ignore[no-untyped-def]
    """Add the dataset answer-policy snapshot used by reproducible scoring."""
    existing = await _table_columns(conn, "experiments")
    if "dataset_snapshot" not in existing:
        await conn.execute(
            sa.text("ALTER TABLE experiments ADD COLUMN dataset_snapshot JSON")
        )


MIGRATIONS[14] = _upgrade_experiment_dataset_snapshot


async def _upgrade_create_evaluation_tasks(conn) -> None:  # type: ignore[no-untyped-def]
    """Create the evaluation_tasks table (task audit + startup recovery)."""
    await conn.execute(
        sa.text(
            """
            CREATE TABLE IF NOT EXISTS evaluation_tasks (
                id VARCHAR(36) PRIMARY KEY,
                experiment_id VARCHAR(36) NOT NULL,
                action VARCHAR(20) NOT NULL DEFAULT 'run',
                status VARCHAR(20) NOT NULL DEFAULT 'queued',
                attempts INTEGER NOT NULL DEFAULT 1,
                error TEXT,
                started_at DATETIME,
                finished_at DATETIME,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL
            )
            """
        )
    )
    await conn.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS ix_evaluation_tasks_experiment_id "
            "ON evaluation_tasks (experiment_id)"
        )
    )
    await conn.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS ix_evaluation_tasks_status "
            "ON evaluation_tasks (status)"
        )
    )


MIGRATIONS[15] = _upgrade_create_evaluation_tasks


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
