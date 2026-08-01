"""Database health and backup utilities."""
from __future__ import annotations

import logging
import time
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


def get_db_info(database_url: str) -> dict:
    """Return human-readable database backend info."""
    is_sqlite = database_url.startswith("sqlite")
    if is_sqlite:
        # Extract the file path from the URL (e.g. sqlite+aiosqlite:///./data.db)
        parts = database_url.split("///", 1)
        db_path = parts[1] if len(parts) > 1 else "unknown"
        path_obj = Path(db_path)
        size_mb = 0.0
        if path_obj.exists():
            size_mb = round(path_obj.stat().st_size / (1024 * 1024), 2)
        return {
            "backend": "SQLite",
            "path": str(path_obj.resolve()),
            "size_mb": size_mb,
            "is_file_based": True,
        }
    else:
        # Parse postgresql+asyncpg://user:pass@host:port/db
        host = "unknown"
        port = "unknown"
        dbname = "unknown"
        try:
            # Strip credentials
            url_no_auth = database_url.split("://")[1]
            if "@" in url_no_auth:
                url_no_auth = url_no_auth.split("@")[1]
            parts = url_no_auth.split(":")
            host = parts[0]
            if len(parts) > 1:
                port = parts[1].split("/")[0]
                dbname = parts[1].split("/", 1)[1] if "/" in parts[1] else "unknown"
            else:
                dbname = url_no_auth.split("/", 1)[1] if "/" in url_no_auth else "unknown"
        except Exception:  # noqa: BLE001
            pass
        return {
            "backend": "PostgreSQL",
            "host": host,
            "port": port,
            "database": dbname,
            "is_file_based": False,
        }


async def check_db_health(session: AsyncSession) -> dict:
    """Run a quick health check on the database."""
    db_ok = True
    row_count = 0
    try:
        await session.execute(text("SELECT 1"))
    except Exception:
        db_ok = False

    if db_ok:
        try:
            result = await session.execute(
                text("SELECT COUNT(*) FROM experiments")
            )
            row_count = result.scalar() or 0
        except Exception:  # noqa: BLE001
            pass

    return {
        "ok": db_ok,
        "experiment_count": row_count,
    }


def backup_database(database_url: str, dest_dir: str | None = None) -> dict:
    """Create a point-in-time backup of the SQLite database.

    Returns a dict with backup path and size.
    Raises ValueError if the database is not SQLite.
    """
    if not database_url.startswith("sqlite"):
        raise ValueError("Backup is only supported for SQLite databases")

    # Extract DB file path
    parts = database_url.split("///", 1)
    db_path_str = parts[1] if len(parts) > 1 else ""
    db_path = Path(db_path_str)

    if not db_path.exists():
        raise FileNotFoundError(f"Database file not found: {db_path}")

    backup_dir = Path(dest_dir or "./backups")
    backup_dir.mkdir(parents=True, exist_ok=True)

    timestamp = time.strftime("%Y%m%d_%H%M%S")
    backup_filename = f"benchmarkops_{timestamp}.db"
    backup_path = backup_dir / backup_filename

    _backup_sqlite(db_path, backup_path)

    size_mb = round(backup_path.stat().st_size / (1024 * 1024), 2)
    logger.info("database backup created: %s (%s MB)", backup_path, size_mb)

    return {
        "backup_path": str(backup_path),
        "filename": backup_filename,
        "size_mb": size_mb,
        "timestamp": timestamp,
    }


def _backup_sqlite(src_path: Path, dest_path: Path) -> None:
    """Create a consistent point-in-time copy via the SQLite online backup API.

    A plain file copy of a WAL-mode database can capture the main DB file and
    its WAL at different instants, and a shipped snapshot that omits the WAL
    loses the newest committed transactions. The backup API copies pages under
    a read lock, so the result is internally consistent even while another
    writer is active, and WAL contents are folded into the single output file.
    """
    import sqlite3

    src = sqlite3.connect(str(src_path), timeout=30)
    dest = sqlite3.connect(str(dest_path), timeout=30)
    try:
        src.backup(dest)
    finally:
        dest.close()
        src.close()
