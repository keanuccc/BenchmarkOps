"""Read-only database integrity checks for BenchmarkOps.

The v1 schema deliberately keeps modules decoupled with plain string IDs
instead of foreign keys, so referential health must be verified explicitly.
`check_integrity` returns one counter per known dangling-reference pattern and
is used by the startup log and the `/api/v1/db/integrity` endpoint.
"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_MISSING_PARENT_SQL: dict[str, str] = {
    "experiments_missing_project": """
        SELECT COUNT(*) FROM experiments e
        LEFT JOIN projects p ON e.project_id = p.id
        WHERE p.id IS NULL
    """,
    "experiments_missing_dataset": """
        SELECT COUNT(*) FROM experiments e
        LEFT JOIN datasets d ON e.dataset_id = d.id
        WHERE d.id IS NULL
    """,
    "experiments_missing_benchmark": """
        SELECT COUNT(*) FROM experiments e
        LEFT JOIN benchmarks b ON e.benchmark_id = b.id
        WHERE b.id IS NULL
    """,
    "experiments_missing_prompt": """
        SELECT COUNT(*) FROM experiments e
        LEFT JOIN prompts p ON e.prompt_id = p.id
        WHERE p.id IS NULL
    """,
    "experiments_missing_model": """
        SELECT COUNT(*) FROM experiments e
        LEFT JOIN models m ON e.model_id = m.id
        WHERE m.id IS NULL
    """,
    "datasets_missing_project": """
        SELECT COUNT(*) FROM datasets d
        LEFT JOIN projects p ON d.project_id = p.id
        WHERE p.id IS NULL
    """,
    "benchmarks_missing_project": """
        SELECT COUNT(*) FROM benchmarks b
        LEFT JOIN projects p ON b.project_id = p.id
        WHERE p.id IS NULL
    """,
    "prompts_missing_project": """
        SELECT COUNT(*) FROM prompts p
        LEFT JOIN projects pr ON p.project_id = pr.id
        WHERE pr.id IS NULL
    """,
    "reports_missing_project": """
        SELECT COUNT(*) FROM reports r
        LEFT JOIN projects p ON r.project_id = p.id
        WHERE p.id IS NULL
    """,
    "dataset_rows_missing_dataset": """
        SELECT COUNT(*) FROM dataset_rows r
        LEFT JOIN datasets d ON r.dataset_id = d.id
        WHERE d.id IS NULL
    """,
    "experiment_results_missing_experiment": """
        SELECT COUNT(*) FROM experiment_results r
        LEFT JOIN experiments e ON r.experiment_id = e.id
        WHERE e.id IS NULL
    """,
    "evaluation_tasks_missing_experiment": """
        SELECT COUNT(*) FROM evaluation_tasks t
        LEFT JOIN experiments e ON t.experiment_id = e.id
        WHERE e.id IS NULL AND t.experiment_deleted_at IS NULL
    """,
}


def _metric_drift_sql(dialect: str) -> str:
    """Return SQL counting experiments whose materialized columns drift."""
    if dialect == "sqlite":
        return """
            SELECT COUNT(*) FROM experiments
            WHERE metrics IS NOT NULL
              AND (
                json_type(metrics, '$.accuracy') IN ('real', 'integer')
                AND ABS(accuracy - json_extract(metrics, '$.accuracy')) > 1e-9
                OR
                json_type(metrics, '$.avg_latency_ms') IN ('real', 'integer')
                AND ABS(avg_latency_ms - json_extract(metrics, '$.avg_latency_ms')) > 1e-9
              )
        """
    return """
        SELECT COUNT(*) FROM experiments
        WHERE metrics IS NOT NULL
          AND (
            metrics->>'accuracy' IS NOT NULL
            AND ABS(accuracy - (metrics->>'accuracy')::double precision) > 1e-9
            OR
            metrics->>'avg_latency_ms' IS NOT NULL
            AND ABS(avg_latency_ms - (metrics->>'avg_latency_ms')::double precision) > 1e-9
          )
    """


async def check_integrity(session: AsyncSession) -> dict[str, int]:
    """Return a count per integrity pattern (table missing -> -1)."""
    dialect = getattr(session.bind, "dialect", None)
    dialect_name = getattr(dialect, "name", "sqlite")
    results: dict[str, int] = {}
    for name, sql in _MISSING_PARENT_SQL.items():
        try:
            row = await session.execute(text(sql))
            results[name] = int(row.scalar() or 0)
        except Exception:  # noqa: BLE001 - table may not exist yet
            results[name] = -1
    try:
        row = await session.execute(text(_metric_drift_sql(dialect_name)))
        results["experiments_metric_column_drift"] = int(row.scalar() or 0)
    except Exception:  # noqa: BLE001
        results["experiments_metric_column_drift"] = -1
    return results
