"""Organization monthly budget enforcement for evaluation runs."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ValidationError
from app.models.experiment import Experiment
from app.models.organization import Organization


async def check_org_budget(org_id: str | None, session: AsyncSession) -> None:
    """Raise when the organization has exhausted its monthly evaluation budget."""
    if not org_id:
        return
    org = await session.get(Organization, org_id)
    if org is None or org.monthly_budget_usd is None:
        return
    month_start = datetime.now(timezone.utc).replace(
        day=1, hour=0, minute=0, second=0, microsecond=0
    )
    result = await session.execute(
        select(func.coalesce(func.sum(Experiment.total_cost), 0.0)).where(
            Experiment.organization_id == org_id,
            Experiment.created_at >= month_start,
            Experiment.status.in_(("completed", "partial", "failed")),
        )
    )
    spent = float(result.scalar_one() or 0.0)
    if spent >= org.monthly_budget_usd:
        raise ValidationError(
            f"Organization monthly budget ${org.monthly_budget_usd:g} exhausted "
            f"(spent ${spent:.4f})"
        )
