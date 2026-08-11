"""Consistency tests for the SQLite backup helper."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from app.services.db_service import backup_database


def _make_db(path: Path) -> sqlite3.Connection:
    """Create a WAL-mode SQLite database with one committed row."""
    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
    conn.execute("INSERT INTO t (v) VALUES ('before')")
    conn.commit()
    return conn


def test_backup_is_consistent_and_complete(tmp_path):
    """The snapshot must contain every committed transaction, including data
    that lives only in the WAL (the writer stays open), and must be a single
    self-contained file with no WAL/SHM sidecars."""
    db_path = tmp_path / "data.db"
    conn = _make_db(db_path)
    # Keep the writer open so the WAL holds committed data that a naive copy of
    # the main .db file would miss.
    conn.execute("INSERT INTO t (v) VALUES ('after')")
    conn.commit()

    result = backup_database(
        f"sqlite+aiosqlite:///{db_path}", dest_dir=str(tmp_path / "backups")
    )

    conn.close()

    backup_conn = sqlite3.connect(result["backup_path"])
    try:
        assert backup_conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        values = [
            row[0]
            for row in backup_conn.execute("SELECT v FROM t ORDER BY id")
        ]
        assert values == ["before", "after"]
    finally:
        backup_conn.close()

    sidecars = list(Path(result["backup_path"]).parent.glob("benchmarkops_*.db-*"))
    assert sidecars == []


def test_backup_rejects_non_sqlite(tmp_path):
    with pytest.raises(ValueError):
        backup_database(
            "postgresql+asyncpg://localhost/benchmarkops",
            dest_dir=str(tmp_path),
        )


def test_backup_missing_db_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        backup_database(
            "sqlite+aiosqlite:///./does_not_exist.db",
            dest_dir=str(tmp_path),
        )


def test_backup_list_route_is_not_shadowed_by_filename(client):
    """GET /db/backup/list must not be captured by /db/backup/{filename}."""
    r = client.get("/api/v1/db/backup/list")
    assert r.status_code == 200
    assert isinstance(r.json(), list)
