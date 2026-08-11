"""Database management endpoints — health, info, backup."""
from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_session
from app.core.integrity import check_integrity
from app.core.security import require_auth
from app.services.db_service import (
    backup_database,
    check_db_health,
    get_db_info,
)

router = APIRouter(prefix="/db", tags=["database"])

# Filenames produced by backup_database(): benchmarkops_<YYYYmmdd>_<HHMMSS>.db
_BACKUP_FILENAME_RE = re.compile(r"^benchmarkops_\d{8}_\d{6}\.db$")


@router.get("/info")
async def db_info() -> dict:
    """Return database backend information (no auth needed)."""
    return get_db_info(settings.database_url)


@router.get("/health")
async def db_health(session: AsyncSession = Depends(get_session)) -> dict:
    """Quick database health check with row counts."""
    return await check_db_health(session)


@router.get("/integrity")
async def db_integrity(session: AsyncSession = Depends(get_session)) -> dict:
    """Return one counter per dangling-reference integrity pattern."""
    return await check_integrity(session)


@router.post("/backup")
async def create_backup(
    service: None = Depends(require_auth),
) -> dict:
    """Create a point-in-time backup of the SQLite database.

    Returns the backup file path, size, and timestamp.
    Requires authentication if API token is configured.
    """
    result = backup_database(settings.database_url)
    return result


@router.get("/backup/list")
async def list_backups(
    _: None = Depends(require_auth),
) -> list[dict]:
    """List all available backup files with metadata."""
    from pathlib import Path

    backup_dir = Path("./backups")
    if not backup_dir.exists():
        return []

    backups = []
    for f in sorted(backup_dir.glob("benchmarkops_*.db*"), reverse=True):
        # Only include main .db files (not -wal/-shm sidecar files)
        if not f.name.endswith(".db"):
            continue
        stat = f.stat()
        backups.append({
            "filename": f.name,
            "size_mb": round(stat.st_size / (1024 * 1024), 2),
            "created_at": f.strftime("%Y-%m-%d %H:%M:%S") if hasattr(f, 'strftime') else "",
            "modified": f.stat().st_mtime,
        })
    return backups


@router.get("/backup/{filename}")
async def download_backup(
    filename: str,
    _: None = Depends(require_auth),
) -> FileResponse:
    """Download a previously created backup file.

    The filename must match the pattern produced by ``backup_database`` and
    resolve inside the backups directory. This blocks path traversal (e.g.
    ``..%2F..%2F.env``) that would otherwise let any caller read arbitrary
    files on the server.
    """
    from pathlib import Path

    if not _BACKUP_FILENAME_RE.fullmatch(filename):
        raise HTTPException(status_code=400, detail="Invalid backup filename")

    backup_dir = Path("./backups").resolve()
    backup_path = (backup_dir / filename).resolve()
    if not backup_path.is_relative_to(backup_dir):
        raise HTTPException(status_code=400, detail="Invalid backup filename")

    if not backup_path.is_file():
        raise HTTPException(status_code=404, detail="Backup file not found")

    return FileResponse(
        path=str(backup_path),
        filename=filename,
        media_type="application/octet-stream",
    )


@router.delete("/backup/{filename}", status_code=204, response_model=None)
async def delete_backup(
    filename: str,
    _: None = Depends(require_auth),
) -> None:
    """Delete a previously created backup file (and its WAL/SHM sidecars).

    Uses the same validation as download: only ``benchmarkops_<timestamp>.db``
    files resolving inside the backups directory can be removed.
    """
    from pathlib import Path

    if not _BACKUP_FILENAME_RE.fullmatch(filename):
        raise HTTPException(status_code=400, detail="Invalid backup filename")

    backup_dir = Path("./backups").resolve()
    backup_path = (backup_dir / filename).resolve()
    if not backup_path.is_relative_to(backup_dir):
        raise HTTPException(status_code=400, detail="Invalid backup filename")
    if not backup_path.is_file():
        raise HTTPException(status_code=404, detail="Backup file not found")

    backup_path.unlink()
    for suffix in ("-wal", "-shm"):
        sidecar = Path(str(backup_path) + suffix)
        if sidecar.exists():
            sidecar.unlink()
