"""Settings API — environment config management."""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.database import engine
from app.core.security import require_auth

router = APIRouter(prefix="/settings", tags=["settings"])


class ApiTokenResponse(BaseModel):
    """Current API token status — never returns the actual token value."""

    enabled: bool = Field(
        description="True when an API token is configured."
    )
    masked: str = Field(
        description="First 4 and last 4 chars of the token, middle hidden with ***."
    )


class MigrationInfo(BaseModel):
    """Migration system info."""
    version: int
    name: str


class MigrationStatus(BaseModel):
    """Current migration status."""
    current_version: int | None
    pending: list[MigrationInfo] = []
    applied: list[MigrationInfo] = []


class DbConfigResponse(BaseModel):
    """Database configuration info for the UI."""
    url_prefix: str  # first 30 chars of DB URL (never full path)
    backend: str     # "SQLite" or "PostgreSQL"
    pool_size: int | None
    max_overflow: int
    is_sqlite: bool
    wal_enabled: bool
    migration_versions: list[int]  # registered migration versions
    highest_version: int | None


class ApiTokenUpdate(BaseModel):
    """Set or remove the API token. Pass empty string to disable auth."""

    token: str = Field(
        default="",
        description=(
            "New API token value. Pass empty string to disable authentication."
        ),
    )


def _get_env_path() -> Path:
    """Return the .env file path relative to the project root."""
    # Traverse up from this module to find the backend/ directory (one level above app/)
    backend_dir = Path(__file__).resolve().parent.parent.parent
    return backend_dir / ".env"


def _read_env_lines(env_path: Path) -> list[str]:
    """Read all lines from the .env file."""
    if not env_path.exists():
        return []
    return env_path.read_text(encoding="utf-8").splitlines()


def _write_env_lines(env_path: Path, lines: list[str]) -> None:
    """Write lines back to the .env file."""
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _mask_token(token: str) -> str:
    """Show first 4 and last 4 chars, mask the rest."""
    if len(token) <= 8:
        return "****"
    return f"{token[:4]}***{token[-4:]}"


@router.get("/api-token", response_model=ApiTokenResponse)
async def get_api_token_status() -> ApiTokenResponse:
    """Get the current API token status without exposing the token value."""
    masked = _mask_token(settings.api_token) if settings.api_token else ""
    return ApiTokenResponse(enabled=settings.auth_enabled, masked=masked)


@router.post("/api-token", response_model=ApiTokenResponse)
async def update_api_token(
    payload: ApiTokenUpdate,
    _: None = Depends(require_auth),
) -> ApiTokenResponse:
    """Set or remove the API token by writing to .env file.

    - Non-empty token: enables auth with the new token
    - Empty token: disables auth (same as demo mode)

    Requires auth if auth is currently enabled.
    """
    env_path = _get_env_path()
    lines = _read_env_lines(env_path)

    updated = False
    new_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        # Match API_TOKEN line (with optional leading whitespace/comments)
        if stripped.startswith("API_TOKEN"):
            if payload.token:
                new_lines.append(f"API_TOKEN={payload.token}")
            # If empty token, either skip the line entirely or leave it commented out
            # We remove it to keep .env clean when auth is disabled
            updated = True
        else:
            new_lines.append(line)

    if not updated and payload.token:
        # Add API_TOKEN at the end of the file
        new_lines.append("")
        new_lines.append("# --- Auth ---")
        new_lines.append(f"API_TOKEN={payload.token}")

    _write_env_lines(env_path, new_lines)

    # Reload settings to pick up the change
    settings.__dict__  # noqa: B018 — access to trigger property re-evaluation

    masked = _mask_token(payload.token) if payload.token else ""
    return ApiTokenResponse(
        enabled=bool(payload.token.strip()),
        masked=masked,
    )


# --- Migration & DB Config ---------------------------------------------------

# Map version numbers to human-readable names for display in the UI.
_MIGRATION_NAMES: dict[int, str] = {
    10: "experiment_snapshot_and_metrics",
    11: "experiment_progress_cells",
    12: "experiment_result_diagnostics",
    13: "dataset_contract_columns",
}


@router.get("/migrations/status", response_model=MigrationStatus)
async def get_migration_status() -> MigrationStatus:
    """Return the current migration status — which versions are applied and pending."""
    from app.migrations import MIGRATIONS

    # Read applied versions from the schema_version table
    applied: list[int] = []
    try:
        from app.core.database import AsyncSessionLocal

        async with AsyncSessionLocal() as session:
            result = await session.execute(
                "SELECT version FROM schema_version ORDER BY version"
            )
            applied = [row[0] for row in result.fetchall()]
    except Exception:  # noqa: BLE001
        pass  # Table may not exist on a fresh install

    all_versions = sorted(MIGRATIONS.keys())
    applied_set = set(applied)

    return MigrationStatus(
        current_version=max(applied) if applied else None,
        pending=[
            MigrationInfo(version=v, name=_MIGRATION_NAMES.get(v, f"migration_{v}"))
            for v in all_versions
            if v not in applied_set
        ],
        applied=[
            MigrationInfo(version=v, name=_MIGRATION_NAMES.get(v, f"migration_{v}"))
            for v in all_versions
            if v in applied_set
        ],
    )


@router.get("/db/config", response_model=DbConfigResponse)
async def get_db_config() -> DbConfigResponse:
    """Return database configuration details for the Settings UI."""
    from app.migrations import MIGRATIONS

    is_sqlite = settings.database_url.startswith("sqlite")
    # Show only the driver part of the URL, never the full path/credentials
    url_prefix = settings.database_url[:30] + ("…" if len(settings.database_url) > 30 else "")

    return DbConfigResponse(
        url_prefix=url_prefix,
        backend="SQLite" if is_sqlite else "PostgreSQL",
        pool_size=engine.pool.size() if hasattr(engine.pool, "size") else None,
        max_overflow=getattr(engine.pool, "max_overflow", 10),
        is_sqlite=is_sqlite,
        wal_enabled=is_sqlite,
        migration_versions=list(sorted(MIGRATIONS.keys())),
        highest_version=max(MIGRATIONS.keys()) if MIGRATIONS else None,
    )
