"""Settings API — environment config management."""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.core.config import settings
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
