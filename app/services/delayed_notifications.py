from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import LeadStatus, LeadType
from app.models import Lead


async def due_agent_client_leads(session: AsyncSession, platform: str, delay_seconds: int) -> list[Lead]:
    cutoff = datetime.utcnow() - timedelta(seconds=delay_seconds)
    result = await session.execute(
        select(Lead)
        .where(
            Lead.platform == platform,
            Lead.type == LeadType.AGENT_CLIENT.value,
            Lead.status == LeadStatus.NEW.value,
            Lead.staff_notified_at.is_(None),
            Lead.created_at <= cutoff,
        )
        .order_by(Lead.created_at.asc())
        .limit(20)
    )
    return list(result.scalars().all())


async def mark_staff_notified(session: AsyncSession, lead: Lead) -> Lead:
    lead.staff_notified_at = datetime.utcnow()
    await session.commit()
    await session.refresh(lead)
    return lead
