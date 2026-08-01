"""One-shot repair for dangling references in the BenchmarkOps database.

Usage: ``uv run python -m app.repair_integrity`` (from backend/)

The script first creates a point-in-time backup under ``backend/backups``, then:
  1. restores missing Model rows from experiment model snapshots (so history
     whose model was deleted keeps its references valid); when a snapshot's
     provider/model_id already exists, experiments are repointed to that row
     instead, so the script works before or after the integrity migration;
  2. deletes datasets / benchmarks / prompts / reports whose project is gone;
  3. deletes experiments whose project or any component is gone, along with
     their results, and marks their evaluation_tasks with experiment_deleted_at
     instead of hard-deleting the audit trail.

It must run while the backend is stopped (it acquires the SQLite writer lock).
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import AsyncSessionLocal, acquire_writer_lock
from app.core.integrity import check_integrity
from app.services.db_service import backup_database

logger = logging.getLogger("benchmarkops.repair")

_PROVIDER_BY_PREFIX = {
    "openai": "openai",
    "anthropic": "anthropic",
    "google": "google",
    "deepseek": "deepseek",
    "qwen": "qwen",
    "zhipuai": "zhipu",
    "tencent": "tencent",
    "moonshot": "moonshot",
    "qiniu": "qiniu",
}


def _provider_for_model_id(model_id: str) -> str:
    prefix = (model_id or "").split("/", 1)[0]
    return _PROVIDER_BY_PREFIX.get(prefix, prefix or "unknown")


async def repair_database(session: AsyncSession) -> dict:
    """Repair dangling references in a single transaction (caller commits)."""
    dialect = getattr(getattr(session.bind, "dialect", None), "name", "sqlite")
    is_sqlite = dialect == "sqlite"
    now = datetime.now(timezone.utc).replace(tzinfo=None).isoformat(
        sep=" ", timespec="seconds"
    )
    report: dict = {
        "models_restored": 0,
        "models_repointed": 0,
        "models_unresolvable": 0,
        "datasets_deleted": 0,
        "dataset_rows_deleted": 0,
        "benchmarks_deleted": 0,
        "prompts_deleted": 0,
        "reports_deleted": 0,
        "experiments_deleted": 0,
        "experiment_results_deleted": 0,
        "tasks_marked": 0,
    }

    # Ensure the audit-marker column exists (it is added by migration 16, but
    # the repair script is also safe to run against the pre-migration schema).
    if await _table_exists(session, "evaluation_tasks"):
        cols = await _table_columns(session, "evaluation_tasks")
        if "experiment_deleted_at" not in cols:
            ddl = (
                "DATETIME"
                if getattr(getattr(session.bind, "dialect", None), "name", "sqlite")
                == "sqlite"
                else "TIMESTAMPTZ"
            )
            await session.execute(
                sa.text(
                    f'ALTER TABLE "evaluation_tasks" '
                    f'ADD COLUMN "experiment_deleted_at" {ddl}'
                )
            )

    # 1) Restore models referenced by experiments but missing from models.
    snap_model_id = (
        "json_extract(e.model_snapshot, '$.model_id')"
        if is_sqlite
        else "e.model_snapshot->>'model_id'"
    )
    snap_name = (
        "json_extract(e.model_snapshot, '$.name')"
        if is_sqlite
        else "e.model_snapshot->>'name'"
    )
    snap_pricing = (
        "json_extract(e.model_snapshot, '$.pricing')"
        if is_sqlite
        else "e.model_snapshot->>'pricing'"
    )
    rows = (
        await session.execute(
            sa.text(
                f"""
                SELECT DISTINCT e.model_id AS ref_id,
                       {snap_model_id} AS mid,
                       {snap_name} AS name,
                       {snap_pricing} AS pricing
                FROM experiments e
                LEFT JOIN models m ON e.model_id = m.id
                WHERE m.id IS NULL
                  AND e.model_snapshot IS NOT NULL
                  AND {snap_model_id} IS NOT NULL
                """
            )
        )
    ).fetchall()
    for ref_id, mid, name, pricing in rows:
        if not ref_id or not mid:
            continue
        params = {
            "id": ref_id,
            "name": name or mid,
            "provider": _provider_for_model_id(mid),
            "mid": mid,
            "pricing": pricing or "{}",
            "now": now,
        }
        if is_sqlite:
            insert_sql = """
                INSERT OR IGNORE INTO models (
                    id, name, provider, model_id, context_length,
                    pricing, capabilities, is_active, created_at, updated_at
                ) VALUES (
                    :id, :name, :provider, :mid, NULL,
                    :pricing, '[]', 1, :now, :now
                )
            """
        else:
            insert_sql = """
                INSERT INTO models (
                    id, name, provider, model_id, context_length,
                    pricing, capabilities, is_active, created_at, updated_at
                ) VALUES (
                    :id, :name, :provider, :mid, NULL,
                    CAST(:pricing AS JSON), '[]', TRUE, :now, :now
                )
                ON CONFLICT (id) DO NOTHING
            """
        result = await session.execute(sa.text(insert_sql), params)
        if (result.rowcount or 0) > 0:
            report["models_restored"] += 1
            continue
        # INSERT was ignored (duplicate id or provider/model_id already taken):
        # if the referenced id still does not exist, repoint experiments to the
        # equivalent existing model row.
        exists = (
            await session.execute(
                sa.text("SELECT 1 FROM models WHERE id=:id"),
                {"id": ref_id},
            )
        ).first()
        if exists:
            continue
        existing = (
            await session.execute(
                sa.text(
                    "SELECT id FROM models "
                    "WHERE model_id=:mid ORDER BY provider LIMIT 1"
                ),
                {"mid": mid},
            )
        ).first()
        if existing:
            repointed = await session.execute(
                sa.text(
                    "UPDATE experiments SET model_id=:to WHERE model_id=:from"
                ),
                {"to": existing[0], "from": ref_id},
            )
            report["models_repointed"] += repointed.rowcount or 0
        else:
            report["models_unresolvable"] += 1

    # 2) Delete datasets (and their rows) whose project is gone.
    orphan_datasets = sa.text(
        """
        SELECT d.id FROM datasets d
        LEFT JOIN projects p ON d.project_id = p.id
        WHERE p.id IS NULL
        """
    )
    dataset_ids = [r[0] for r in (await session.execute(orphan_datasets)).fetchall()]
    if dataset_ids:
        res_rows = await session.execute(
            sa.text(
                "DELETE FROM dataset_rows "
                "WHERE dataset_id IN (SELECT d.id FROM datasets d "
                "LEFT JOIN projects p ON d.project_id = p.id WHERE p.id IS NULL)"
            )
        )
        report["dataset_rows_deleted"] += res_rows.rowcount or 0
        res_ds = await session.execute(
            sa.text(
                "DELETE FROM datasets WHERE id IN "
                "(SELECT d.id FROM datasets d LEFT JOIN projects p "
                "ON d.project_id = p.id WHERE p.id IS NULL)"
            ),
            {"ids": dataset_ids},
        )
        report["datasets_deleted"] += res_ds.rowcount or 0

    # 3) Delete experiments whose project or any component is gone (after the
    #    model restore above), keeping the task audit rows marked, not deleted.
    dangling_experiments = sa.text(
        """
        SELECT e.id FROM experiments e
        LEFT JOIN projects p ON e.project_id = p.id
        LEFT JOIN datasets d ON e.dataset_id = d.id
        LEFT JOIN benchmarks b ON e.benchmark_id = b.id
        LEFT JOIN prompts pr ON e.prompt_id = pr.id
        LEFT JOIN models m ON e.model_id = m.id
        WHERE p.id IS NULL OR d.id IS NULL OR b.id IS NULL
           OR pr.id IS NULL OR m.id IS NULL
        """
    )
    experiment_ids = [
        r[0] for r in (await session.execute(dangling_experiments)).fetchall()
    ]
    if experiment_ids:
        ids_bind = sa.bindparam("ids", expanding=True)
        res_mark = await session.execute(
            sa.text(
                "UPDATE evaluation_tasks SET experiment_deleted_at = :now "
                "WHERE experiment_id IN :ids AND experiment_deleted_at IS NULL"
            ).bindparams(ids_bind),
            {"ids": experiment_ids, "now": now},
        )
        report["tasks_marked"] += res_mark.rowcount or 0
        res_results = await session.execute(
            sa.text(
                "DELETE FROM experiment_results WHERE experiment_id IN :ids"
            ).bindparams(ids_bind),
            {"ids": experiment_ids},
        )
        report["experiment_results_deleted"] += res_results.rowcount or 0
        res_exp = await session.execute(
            sa.text("DELETE FROM experiments WHERE id IN :ids").bindparams(ids_bind),
            {"ids": experiment_ids},
        )
        report["experiments_deleted"] += res_exp.rowcount or 0

    # 4) Generic cleanup for remaining unowned rows.
    res_b = await session.execute(
        sa.text(
            "DELETE FROM benchmarks WHERE id IN "
            "(SELECT b.id FROM benchmarks b LEFT JOIN projects p "
            "ON b.project_id = p.id WHERE p.id IS NULL)"
        )
    )
    report["benchmarks_deleted"] += res_b.rowcount or 0

    res_p = await session.execute(
        sa.text(
            "DELETE FROM prompts WHERE id IN "
            "(SELECT p.id FROM prompts p LEFT JOIN projects pr "
            "ON p.project_id = pr.id WHERE pr.id IS NULL)"
        )
    )
    report["prompts_deleted"] += res_p.rowcount or 0

    res_r = await session.execute(
        sa.text(
            "DELETE FROM reports WHERE id IN "
            "(SELECT r.id FROM reports r LEFT JOIN projects p "
            "ON r.project_id = p.id WHERE p.id IS NULL)"
        )
    )
    report["reports_deleted"] += res_r.rowcount or 0

    res_rows = await session.execute(
        sa.text(
            "DELETE FROM dataset_rows WHERE id IN "
            "(SELECT r.id FROM dataset_rows r LEFT JOIN datasets d "
            "ON r.dataset_id = d.id WHERE d.id IS NULL)"
        )
    )
    report["dataset_rows_deleted"] += res_rows.rowcount or 0

    res_results = await session.execute(
        sa.text(
            "DELETE FROM experiment_results WHERE id IN "
            "(SELECT r.id FROM experiment_results r LEFT JOIN experiments e "
            "ON r.experiment_id = e.id WHERE e.id IS NULL)"
        )
    )
    report["experiment_results_deleted"] += res_results.rowcount or 0

    res_mark = await session.execute(
        sa.text(
            "UPDATE evaluation_tasks SET experiment_deleted_at = :now "
            "WHERE experiment_deleted_at IS NULL AND NOT EXISTS "
            "(SELECT 1 FROM experiments e WHERE e.id = evaluation_tasks.experiment_id)"
        ),
        {"now": now},
    )
    report["tasks_marked"] += res_mark.rowcount or 0

    return report


async def _table_exists(session: AsyncSession, table: str) -> bool:
    return await session.run_sync(
        lambda sync_session: sa.inspect(sync_session.bind).has_table(table)
    )


async def _table_columns(session: AsyncSession, table: str) -> set[str]:
    return await session.run_sync(
        lambda sync_session: {
            col["name"]
            for col in sa.inspect(sync_session.bind).get_columns(table)
        }
    )


async def _main() -> None:
    acquire_writer_lock()
    backup = backup_database(settings.database_url)
    logger.info("backup created: %s", backup["backup_path"])
    async with AsyncSessionLocal() as session:
        report = await repair_database(session)
        await session.commit()
        integrity = await check_integrity(session)
    print(
        json.dumps(
            {"backup": backup, "repair": report, "integrity_after": integrity},
            ensure_ascii=False,
            indent=2,
        )
    )
    dangling = {
        k: v for k, v in integrity.items() if isinstance(v, int) and v > 0
    }
    if dangling:
        logger.warning("integrity still has issues: %s", dangling)
    else:
        logger.info("integrity check clean after repair")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(_main())
