from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import BonusStatus
from app.models import Bonus


async def bonus_totals(session: AsyncSession, agent_id: int) -> dict[str, int]:
    rows = await session.execute(
        select(Bonus.status, func.coalesce(func.sum(Bonus.amount), 0))
        .where(Bonus.agent_id == agent_id)
        .group_by(Bonus.status)
    )
    totals = {"total": 0, "paid": 0, "pending": 0, "canceled": 0}
    for status, amount in rows.all():
        totals[status] = int(amount or 0)
        if status != BonusStatus.CANCELED.value:
            totals["total"] += int(amount or 0)
    return totals


async def recent_bonuses(session: AsyncSession, agent_id: int, limit: int = 10) -> list[Bonus]:
    result = await session.execute(
        select(Bonus).where(Bonus.agent_id == agent_id).order_by(Bonus.created_at.desc()).limit(limit)
    )
    return list(result.scalars().all())


async def create_bonus(
    session: AsyncSession,
    agent_id: int,
    amount: int,
    comment: str | None,
    admin_id: int | None,
    lead_id: int | None = None,
) -> Bonus:
    bonus = Bonus(
        agent_id=agent_id,
        lead_id=lead_id,
        amount=amount,
        comment=comment,
        created_by_admin_id=admin_id,
        status=BonusStatus.PENDING.value,
    )
    session.add(bonus)
    await session.commit()
    await session.refresh(bonus)
    return bonus


async def set_bonus_status(session: AsyncSession, bonus: Bonus, status: BonusStatus) -> Bonus:
    bonus.status = status.value
    if status == BonusStatus.PAID:
        bonus.paid_at = datetime.utcnow()
    await session.commit()
    await session.refresh(bonus)
    return bonus
