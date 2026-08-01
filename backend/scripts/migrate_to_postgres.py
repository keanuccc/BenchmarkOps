"""Migrate BenchmarkOps data from SQLite to PostgreSQL (or reverse).

Reads the current DATABASE_URL to determine the source engine, then copies
every table into the target database specified by TARGET_DATABASE_URL.

Usage:
    # Default: SQLite → PostgreSQL (reads current .env DATABASE_URL as source)
    python scripts/migrate_to_postgres.py

    # Reverse: PostgreSQL → SQLite
    python scripts/migrate_to_postgres.py --reverse

    # Custom target URL via env var
    TARGET_DATABASE_URL=sqlite+aiosqlite:///./backup.db python scripts/migrate_to_postgres.py
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

# Ensure the backend root is on sys.path so we can import app modules.
_BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from sqlalchemy import (  # noqa: E401
    MetaData,
    create_engine,
    text,
)
from sqlalchemy.orm import Session, sessionmaker  # noqa: E401

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


def get_source_url() -> str:
    """Return the source DATABASE_URL from environment or .env file."""
    url = os.environ.get("SOURCE_DATABASE_URL")
    if url:
        return url
    # Fall back to reading .env
    env_path = _BACKEND_ROOT / ".env"
    if env_path.exists():
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line.startswith("DATABASE_URL=") and not line.startswith("#"):
                    return line.split("=", 1)[1]
    raise RuntimeError(
        "No source database URL found. Set SOURCE_DATABASE_URL or ensure .env has DATABASE_URL."
    )


def copy_tables(src_url: str, dst_url: str) -> dict[str, tuple[int, int]]:
    """Copy all tables from src to dst. Returns {table: (src_count, dst_count)}.

    Uses synchronous SQLAlchemy engines for simplicity — the migration script
    is a one-shot tool, not part of the hot path.
    """
    src_engine = create_engine(src_url)
    dst_engine = create_engine(dst_url)

    # Reflect source metadata
    src_meta = MetaData()
    src_meta.reflect(bind=src_engine)

    if not src_meta.tables:
        logger.warning("Source database has no tables — nothing to migrate.")
        return {}

    results: dict[str, tuple[int, int]] = {}

    with Session(src_engine) as src_session, Session(dst_engine) as dst_session:
        for table_name, table in src_meta.tables.items():
            # Skip SQLAlchemy internal tables
            if table_name.startswith("alembic"):
                continue

            logger.info("Copying table: %s", table_name)

            # Get source rows
            src_rows = src_session.execute(text(f"SELECT * FROM [{table_name}]")).fetchall()
            src_count = len(src_rows)

            if src_count == 0:
                logger.info("  Table %s is empty — skipping.", table_name)
                results[table_name] = (0, 0)
                continue

            # Create destination table (copy structure only)
            table.create(dst_engine, checkfirst=True)

            # Insert rows
            col_names = [c.name for c in table.columns]
            placeholders = ", ".join([":" + n for n in col_names])
            insert_sql = f"INSERT INTO {table_name} ({', '.join(col_names)}) VALUES ({placeholders})"

            dst_count = 0
            failed = 0
            for row in src_rows:
                try:
                    values = dict(zip(col_names, row))
                    dst_session.execute(text(insert_sql), values)
                    dst_count += 1
                except Exception as exc:
                    failed += 1
                    logger.warning("  Row insert failed for %s: %s", table_name, exc)

            dst_session.commit()
            results[table_name] = (src_count, dst_count)
            logger.info("  %s/%s rows copied (%d failed)", dst_count, src_count, failed)

    src_engine.dispose()
    dst_engine.dispose()
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate BenchmarkOps data between SQLite and PostgreSQL")
    parser.add_argument(
        "--reverse",
        action="store_true",
        help="Reverse direction: read TARGET_DATABASE_URL as source and SOURCE_DATABASE_URL as target",
    )
    args = parser.parse_args()

    src_url = os.environ.get("TARGET_DATABASE_URL") if args.reverse else get_source_url()
    dst_url = os.environ.get("SOURCE_DATABASE_URL") if args.reverse else os.environ.get("TARGET_DATABASE_URL")

    if not dst_url:
        # Default target: swap the driver prefix
        if "sqlite" in src_url:
            default_pg = "postgresql+asyncpg://benchmarkops:secure_password@localhost:5432/benchmarkops"
        else:
            default_pg = "sqlite+aiosqlite:///./benchmarkops_migration_target.db"
        dst_url = default_pg
        logger.info("Using default target: %s", dst_url)

    logger.info("Source: %s", src_url)
    logger.info("Target: %s", dst_url)

    try:
        results = copy_tables(src_url, dst_url)
    except Exception:
        logger.exception("Migration failed!")
        sys.exit(1)

    # Summary
    total_src = sum(r[0] for r in results.values())
    total_dst = sum(r[1] for r in results.values())
    logger.info("=" * 60)
    logger.info("Migration complete:")
    logger.info("  Tables migrated : %d", len(results))
    logger.info("  Total rows read : %d", total_src)
    logger.info("  Total rows written: %d", total_dst)
    logger.info("=" * 60)

    if total_src != total_dst:
        logger.warning("Row count mismatch! Review the log above.")
        sys.exit(1)
    else:
        logger.info("All rows verified — migration successful.")


if __name__ == "__main__":
    main()
