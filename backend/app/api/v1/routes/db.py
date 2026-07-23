"""Database management endpoints — health, info, backup."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_session
from app.core.security import require_auth
from app.services.db_service import (
    backup_database,
    check_db_health,
    get_db_info,
)

router = APIRouter(prefix="/db", tags=["database"])


@router.get("/info")
async def db_info() -> dict:
    """Return database backend information (no auth needed)."""
    return get_db_info(settings.database_url)


@router.get("/health")
async def db_health(session: AsyncSession = Depends(get_session)) -> dict:
    """Quick database health check with row counts."""
    return await check_db_health(session)


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


@router.get("/backup/{filename}")
async def download_backup(
    filename: str,
    _: None = Depends(require_auth),
) -> FileResponse:
    """Download a previously created backup file."""
    from pathlib import Path

    backup_dir = Path("./backups")
    backup_path = backup_dir / filename

    if not backup_path.exists():
        return FileResponse(
            status_code=404,
            content="Backup file not found",
            media_type="text/plain",
        )

    return FileResponse(
        path=str(backup_path),
        filename=filename,
        media_type="application/octet-stream",
    )


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
