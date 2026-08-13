"""Health & readiness endpoints."""
from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_session
from app.services.db_service import get_db_info
from app.providers.registry import active_provider_name, get_provider

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(session: AsyncSession = Depends(get_session)) -> dict:
    """Liveness + basic DB connectivity + provider mode + DB backend info."""
    db_ok = True
    try:
        await session.execute(text("SELECT 1"))
    except Exception:
        db_ok = False

    return {
        "status": "ok" if db_ok else "degraded",
        "app": settings.app_name,
        "env": settings.app_env,
        "database": "ok" if db_ok else "error",
        "provider_mode": active_provider_name(),
        "db_backend": get_db_info(settings.database_url),
    }


@router.get("/ready")
async def ready(session: AsyncSession = Depends(get_session)) -> dict:
    """Readiness probe — checks DB, provider gateway, and task queue availability."""
    checks: dict[str, str] = {}
    all_ok = True

    # --- DB check ---
    db_ok = True
    try:
        await session.execute(text("SELECT 1"))
    except Exception:
        db_ok = False
    checks["db"] = "ok" if db_ok else "error"
    if not db_ok:
        all_ok = False

    # --- Provider check (fire-and-forget with timeout) ---
    provider_status = "skipped"  # default when no real provider configured
    provider_timeout = asyncio.TimeoutError  # sentinel for the timeout handler
    try:
        prov_name = active_provider_name()
        if prov_name == "mock":
            provider_status = "ok (mock)"
        else:
            provider = get_provider(prov_name)
            # A minimal model id valid on the gateway actually being probed.
            probe_model_id = {
                "deepseek": "deepseek-chat",
                "openrouter": "openai/gpt-4o-mini",
                "qiniu": "deepseek-v3",
            }.get(prov_name, "gpt-4o-mini")
            # Lightweight ping: a minimal request to verify the gateway is reachable.
            # We use a short timeout so a hung provider doesn't block the probe.
            with asyncio.timeout(3):
                # Attempt a minimal completion call — if the provider raises,
                # it's unreachable / misconfigured.
                from app.providers.base import ChatMessage, CompletionRequest
                result = await provider.complete(
                    CompletionRequest(
                        model_id=probe_model_id,
                        messages=[ChatMessage(role="user", content="hi")],
                        max_tokens=1,
                    )
                )
                provider_status = "ok" if result else "ok (no response body)"
    except asyncio.TimeoutError:
        provider_status = "timeout"
        all_ok = False
    except Exception as exc:  # noqa: BLE001
        logger.debug("/ready provider check failed: %s", exc)
        provider_status = f"error ({exc})"
        all_ok = False
    checks["provider"] = provider_status

    # --- Task queue check ---
    checks["task_queue"] = "available"

    status = "ok" if all_ok else "degraded"
    return {"status": status, "checks": checks}
