"""Append-only audit trail for dataset governance."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.tenant import get_tenant
from app.models.audit import AuditEvent


async def record_event(
    session: AsyncSession,
    *,
    entity_type: str,
    entity_id: str,
    action: str,
    project_id: str | None = None,
    actor: str | None = None,
    detail: dict | None = None,
) -> AuditEvent:
    tenant = get_tenant()
    event = AuditEvent(
        project_id=project_id,
        organization_id=tenant.organization_id if tenant is not None else None,
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        actor=actor,
        detail=detail or {},
    )
    session.add(event)
    return event


async def list_events(
    session: AsyncSession, *, entity_type: str, entity_id: str
) -> list[AuditEvent]:
    stmt = (
        select(AuditEvent)
        .where(
            AuditEvent.entity_type == entity_type,
            AuditEvent.entity_id == entity_id,
        )
        .order_by(AuditEvent.created_at.desc())
    )
    tenant = get_tenant()
    if tenant is not None:
        stmt = stmt.where(AuditEvent.organization_id == tenant.organization_id)
    result = await session.execute(stmt)
    return list(result.scalars().all())
