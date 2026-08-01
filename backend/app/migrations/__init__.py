"""Lightweight, zero-dependency async database migration mechanism.

This is a minimal replacement for Alembic, intentionally kept tiny:
- No external dependencies.
- Framework table `schema_migrations` is managed with raw `conn.execute`
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
`schema_migrations` and skips any version already applied, so it is safe to
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


async def _table_exists(conn, table_name: str) -> bool:  # type: ignore[no-untyped-def]
    """Check whether a table exists (works on SQLite and PostgreSQL)."""
    return await conn.run_sync(
        lambda sync_conn: sa.inspect(sync_conn).has_table(table_name)
    )


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


async def _index_exists(conn, index_name: str) -> bool:  # type: ignore[no-untyped-def]
    """Check whether an index exists on the active dialect."""
    if conn.dialect.name == "sqlite":
        result = await conn.execute(
            sa.text(
                "SELECT 1 FROM sqlite_master "
                "WHERE type='index' AND name=:name"
            ),
            {"name": index_name},
        )
    else:
        result = await conn.execute(
            sa.text("SELECT 1 FROM pg_indexes WHERE indexname=:name"),
            {"name": index_name},
        )
    return result.first() is not None


async def _ensure_column(  # type: ignore[no-untyped-def]
    conn, table_name: str, column: str, sqlite_ddl: str, pg_ddl: str
) -> None:
    """Add a column when the table exists and the column is missing."""
    if not await _table_exists(conn, table_name):
        return
    existing = await _table_columns(conn, table_name)
    if column in existing:
        return
    ddl = pg_ddl if conn.dialect.name != "sqlite" else sqlite_ddl
    await conn.execute(
        sa.text(f'ALTER TABLE "{table_name}" ADD COLUMN "{column}" {ddl}')
    )


async def _rebuild_sqlite_table_with_checks(  # type: ignore[no-untyped-def]
    conn, table_name: str, checks: list[str]
) -> None:
    """Rebuild a SQLite table so CHECK constraints can be added.

    SQLite cannot ALTER-ADD a CHECK, so the table is recreated with the same
    columns/defaults, data is copied, and every existing index is recreated.
    There are no foreign keys in this schema, so the swap is safe.
    """
    info = (
        await conn.execute(sa.text(f'PRAGMA table_info("{table_name}")'))
    ).fetchall()
    if not info:
        return

    index_sqls = [
        row[0]
        for row in (
            await conn.execute(
                sa.text(
                    "SELECT sql FROM sqlite_master "
                    "WHERE type='index' AND tbl_name=:t AND sql IS NOT NULL"
                ),
                {"t": table_name},
            )
        ).fetchall()
    ]

    col_defs: list[str] = []
    pk_cols: list[str] = []
    for _cid, name, ctype, notnull, dflt, is_pk in info:
        parts = [f'"{name}" {ctype}']
        if notnull:
            parts.append("NOT NULL")
        if dflt is not None:
            parts.append(f"DEFAULT {dflt}")
        col_defs.append(" ".join(parts))
        if is_pk:
            pk_cols.append(name)
    if pk_cols:
        col_defs.append(
            "PRIMARY KEY (" + ", ".join(f'"{c}"' for c in pk_cols) + ")"
        )
    if checks:
        col_defs.append(
            ", ".join(
                f"CONSTRAINT {name} CHECK ({expr})"
                for name, expr in checks
            )
        )

    new_name = f'"{table_name}__integrity"'
    await conn.execute(
        sa.text(
            f"CREATE TABLE {new_name} (" + ", ".join(col_defs) + ")"
        )
    )
    await conn.execute(
        sa.text(f'INSERT INTO {new_name} SELECT * FROM "{table_name}"')
    )
    await conn.execute(sa.text(f'DROP TABLE "{table_name}"'))
    await conn.execute(sa.text(f'ALTER TABLE {new_name} RENAME TO "{table_name}"'))
    for sql in index_sqls:
        if sql:
            await conn.execute(sa.text(sql))


async def _add_pg_check(  # type: ignore[no-untyped-def]
    conn, table_name: str, constraint: str, expr: str
) -> None:
    """Add a CHECK constraint on PostgreSQL without failing if it exists."""
    if not await _table_exists(conn, table_name):
        return
    result = await conn.execute(
        sa.text(
            "SELECT 1 FROM pg_constraint WHERE conname=:name"
        ),
        {"name": constraint},
    )
    if result.first() is not None:
        return
    await conn.execute(
        sa.text(
            f'ALTER TABLE "{table_name}" '
            f'ADD CONSTRAINT "{constraint}" CHECK ({expr})'
        )
    )


async def _upgrade_integrity_constraints(conn) -> None:  # type: ignore[no-untyped-def]
    """Add integrity guarantees and repair accumulated data drift.

    1. Backfill materialized metric columns from the JSON metrics blob.
    2. Deduplicate models on (provider, model_id), keeping rows referenced by
       experiments (restored rows from snapshots must survive).
    3. Add is_archived to datasets/benchmarks/prompts and
       experiment_deleted_at to evaluation_tasks.
    4. Create unique indexes (also serving as composite indexes) for the key
       business keys that previously had no database-level guarantee.
    5. Add CHECK constraints on enum-like status/format columns.

    Each step is guarded so the migration is safe on fresh DBs (where the ORM
    already created constraints), legacy minimal tables used in tests, and
    PostgreSQL (CHECK via ALTER instead of SQLite table rebuilds).
    """
    dialect = conn.dialect.name

    # 1) Materialized metric columns must mirror the JSON metrics blob.
    if await _table_exists(conn, "experiments"):
        exp_cols = await _table_columns(conn, "experiments")
        if {"metrics", "accuracy", "avg_latency_ms"} <= exp_cols:
            if dialect == "sqlite":
                await conn.execute(
                    sa.text(
                        """
                        UPDATE experiments
                        SET accuracy = COALESCE(
                                json_extract(metrics, '$.accuracy'), accuracy),
                            avg_latency_ms = COALESCE(
                                json_extract(metrics, '$.avg_latency_ms'),
                                avg_latency_ms)
                        """
                    )
                )
            else:
                await conn.execute(
                    sa.text(
                        """
                        UPDATE experiments
                        SET accuracy = COALESCE(
                                (metrics->>'accuracy')::double precision, accuracy),
                            avg_latency_ms = COALESCE(
                                (metrics->>'avg_latency_ms')::double precision,
                                avg_latency_ms)
                        """
                    )
                )

    # 2) Deduplicate models: referenced rows always survive, and unreferenced
    #    duplicates keep the earliest (created_at, id) row.
    if await _table_exists(conn, "models"):
        has_experiments = await _table_exists(conn, "experiments")
        if has_experiments:
            dedupe_sql = """
                DELETE FROM models WHERE id IN (
                    SELECT m.id FROM models m
                    WHERE NOT EXISTS (
                        SELECT 1 FROM experiments e WHERE e.model_id = m.id
                    )
                    AND EXISTS (
                        SELECT 1 FROM models m2
                        WHERE m2.provider = m.provider
                          AND m2.model_id = m.model_id
                          AND m2.id != m.id
                          AND (
                              EXISTS (
                                  SELECT 1 FROM experiments e2
                                  WHERE e2.model_id = m2.id
                              )
                              OR (m2.created_at, m2.id) < (m.created_at, m.id)
                          )
                    )
                )
            """
        else:
            dedupe_sql = """
                DELETE FROM models WHERE id IN (
                    SELECT m.id FROM models m
                    WHERE EXISTS (
                        SELECT 1 FROM models m2
                        WHERE m2.provider = m.provider
                          AND m2.model_id = m.model_id
                          AND m2.id != m.id
                          AND (m2.created_at, m2.id) < (m.created_at, m.id)
                    )
                )
            """
        await conn.execute(sa.text(dedupe_sql))

        if has_experiments:
            # 2b) If a group still has duplicates (multiple referenced rows),
            #      keep the deterministic MIN(id) row and repoint experiments.
            await conn.execute(
                sa.text(
                    """
                    UPDATE experiments
                    SET model_id = (
                        SELECT MIN(m2.id) FROM models m2
                        JOIN models m3 ON m3.id = experiments.model_id
                        WHERE m2.provider = m3.provider
                          AND m2.model_id = m3.model_id
                    )
                    WHERE EXISTS (
                        SELECT 1 FROM models m
                        JOIN models m2
                          ON m2.provider = m.provider
                         AND m2.model_id = m.model_id
                        WHERE m.id = experiments.model_id
                          AND m2.id != m.id
                    )
                    AND experiments.model_id != (
                        SELECT MIN(m3.id) FROM models m3
                        JOIN models m4 ON m4.id = experiments.model_id
                        WHERE m3.provider = m4.provider
                          AND m3.model_id = m4.model_id
                    )
                    """
                )
            )

            # 2c) Delete any remaining duplicate rows (now unreferenced).
            await conn.execute(
                sa.text(
                    """
                    DELETE FROM models WHERE id IN (
                        SELECT m.id FROM models m
                        WHERE EXISTS (
                            SELECT 1 FROM models m2
                            WHERE m2.provider = m.provider
                              AND m2.model_id = m.model_id
                              AND m2.id != m.id
                        )
                        AND m.id != (
                            SELECT MIN(m3.id) FROM models m3
                            WHERE m3.provider = m.provider
                              AND m3.model_id = m.model_id
                        )
                    )
                    """
                )
            )

    # 3) New columns.
    await _ensure_column(
        conn, "datasets", "is_archived",
        "BOOLEAN NOT NULL DEFAULT 0", "BOOLEAN NOT NULL DEFAULT FALSE",
    )
    await _ensure_column(
        conn, "benchmarks", "is_archived",
        "BOOLEAN NOT NULL DEFAULT 0", "BOOLEAN NOT NULL DEFAULT FALSE",
    )
    await _ensure_column(
        conn, "prompts", "is_archived",
        "BOOLEAN NOT NULL DEFAULT 0", "BOOLEAN NOT NULL DEFAULT FALSE",
    )
    await _ensure_column(
        conn, "evaluation_tasks", "experiment_deleted_at",
        "DATETIME", "TIMESTAMPTZ",
    )

    # 4) Unique / composite indexes.
    unique_indexes = [
        ("uq_models_provider_model_id", "models", "provider, model_id"),
        ("uq_datasets_project_name", "datasets", "project_id, name"),
        ("uq_prompts_project_name", "prompts", "project_id, name"),
        ("uq_benchmarks_project_name", "benchmarks", "project_id, name"),
        ("uq_dataset_rows_dataset_idx", "dataset_rows", "dataset_id, idx"),
        (
            "uq_experiment_results_experiment_row",
            "experiment_results",
            "experiment_id, row_idx",
        ),
    ]
    for index_name, table_name, columns in unique_indexes:
        if not await _table_exists(conn, table_name):
            continue
        if await _index_exists(conn, index_name):
            continue
        await conn.execute(
            sa.text(
                f'CREATE UNIQUE INDEX "{index_name}" '
                f'ON "{table_name}" ({columns})'
            )
        )

    # 5) CHECK constraints on enum-like columns.
    check_specs = [
        (
            "projects", "status",
            "ck_projects_status",
            "status IN ('active', 'archived')",
        ),
        (
            "datasets", "format",
            "ck_datasets_format",
            "format IN ('csv', 'json', 'jsonl')",
        ),
        (
            "experiments", "status",
            "ck_experiments_status",
            "status IN ('pending', 'queued', 'running', 'completed', "
            "'partial', 'failed', 'cancelled')",
        ),
        (
            "evaluation_tasks", "status",
            "ck_evaluation_tasks_status",
            "status IN ('queued', 'running', 'succeeded', 'failed', "
            "'cancelled')",
        ),
        (
            "evaluation_tasks", "action",
            "ck_evaluation_tasks_action",
            "action IN ('run', 'retry')",
        ),
    ]
    sqlite_checks: dict[str, list[tuple[str, str]]] = {}
    pg_checks: dict[str, list[tuple[str, str]]] = {}
    for table_name, column, constraint, expr in check_specs:
        if not await _table_exists(conn, table_name):
            continue
        cols = await _table_columns(conn, table_name)
        if column not in cols:
            continue
        if dialect == "sqlite":
            sqlite_checks.setdefault(table_name, []).append((constraint, expr))
        else:
            pg_checks.setdefault(table_name, []).append((constraint, expr))
    for table_name, named_exprs in sqlite_checks.items():
        await _rebuild_sqlite_table_with_checks(conn, table_name, named_exprs)
    for table_name, specs in pg_checks.items():
        for constraint, expr in specs:
            await _add_pg_check(conn, table_name, constraint, expr)


MIGRATIONS[16] = _upgrade_integrity_constraints


async def _ensure_version_table(conn: sa.ext.asyncio.AsyncConnection) -> None:
    """Create `schema_migrations`; migrate and drop the legacy table."""
    has_legacy = await _table_exists(conn, "schema_version")
    has_current = await _table_exists(conn, "schema_migrations")
    if not has_current:
        await conn.execute(
            sa.text(
                """
                CREATE TABLE schema_migrations (
                    version INTEGER PRIMARY KEY,
                    applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )
    if has_legacy:
        if conn.dialect.name == "sqlite":
            await conn.execute(
                sa.text(
                    """
                    INSERT OR IGNORE INTO schema_migrations (version, applied_at)
                    SELECT version, applied_at FROM schema_version
                    """
                )
            )
        else:
            await conn.execute(
                sa.text(
                    """
                    INSERT INTO schema_migrations (version, applied_at)
                    SELECT version, applied_at FROM schema_version
                    ON CONFLICT (version) DO NOTHING
                    """
                )
            )
        await conn.execute(sa.text("DROP TABLE schema_version"))


async def _applied_versions(conn: sa.ext.asyncio.AsyncConnection) -> set[int]:
    """Return the set of version numbers already recorded as applied."""
    result = await conn.execute(sa.text("SELECT version FROM schema_migrations"))
    return {row[0] for row in result.fetchall()}


async def run_migrations(engine: AsyncEngine) -> None:
    """Apply all pending migrations in version order, idempotently.

    Already-applied versions (recorded in `schema_migrations`) are skipped, so
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
                sa.text("INSERT INTO schema_migrations (version) VALUES (:v)"),
                {"v": version},
            )
