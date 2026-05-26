from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import BonusStatus, ChatStatus, LeadStatus, LeadType
from app.models import Bonus, ChatSession, Lead, User


async def admin_stats(session: AsyncSession) -> dict[str, int | dict[str, int]]:
    now = datetime.utcnow()
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week = now - timedelta(days=7)
    month = now - timedelta(days=30)

    async def count(stmt) -> int:
        return int((await session.scalar(stmt)) or 0)

    status_rows = await session.execute(select(Lead.status, func.count(Lead.id)).group_by(Lead.status))
    lead_statuses = {status: int(total) for status, total in status_rows.all()}
    agent_form_stats = await agent_client_form_stats(session)

    return {
        "users_total": await count(select(func.count(User.id))),
        "users_today": await count(select(func.count(User.id)).where(User.created_at >= today)),
        "users_week": await count(select(func.count(User.id)).where(User.created_at >= week)),
        "clients_total": await count(select(func.count(User.id)).where(User.is_client.is_(True))),
        "agents_total": await count(select(func.count(User.id)).where(User.is_agent.is_(True))),
        "managers_total": await count(select(func.count(User.id)).where(User.is_manager.is_(True))),
        "leads_total": await count(select(func.count(Lead.id))),
        "leads_today": await count(select(func.count(Lead.id)).where(Lead.created_at >= today)),
        "leads_week": await count(select(func.count(Lead.id)).where(Lead.created_at >= week)),
        "leads_month": await count(select(func.count(Lead.id)).where(Lead.created_at >= month)),
        "lead_statuses": lead_statuses,
        "agent_form_stats": agent_form_stats,
        "bonus_total": await count(select(func.coalesce(func.sum(Bonus.amount), 0)).where(Bonus.status != BonusStatus.CANCELED.value)),
        "bonus_paid_total": await count(select(func.coalesce(func.sum(Bonus.amount), 0)).where(Bonus.status == BonusStatus.PAID.value)),
        "bonus_paid_month": await count(
            select(func.coalesce(func.sum(Bonus.amount), 0)).where(Bonus.status == BonusStatus.PAID.value, Bonus.paid_at >= month)
        ),
        "bonus_paid_week": await count(
            select(func.coalesce(func.sum(Bonus.amount), 0)).where(Bonus.status == BonusStatus.PAID.value, Bonus.paid_at >= week)
        ),
        "chats_active": await count(select(func.count(ChatSession.id)).where(ChatSession.status == ChatStatus.ACTIVE.value)),
        "chats_closed": await count(select(func.count(ChatSession.id)).where(ChatSession.status == ChatStatus.CLOSED.value)),
        "leads_new": await count(select(func.count(Lead.id)).where(Lead.status == LeadStatus.NEW.value)),
    }


async def agent_client_form_stats(session: AsyncSession) -> dict[str, dict[str, int | float] | int]:
    result = await session.execute(select(Lead).where(Lead.type == LeadType.AGENT_CLIENT.value))
    leads = list(result.scalars().all())
    total = len(leads)
    counts = {
        "only_name": 0,
        "name_phone": 0,
        "name_phone_relation": 0,
        "completed": 0,
        "other": 0,
    }
    for lead in leads:
        has_phone = bool(lead.phone)
        has_relation = bool(lead.relation_to_agent)
        has_payout_phone = bool(lead.agent_payout_phone)
        if has_phone and has_relation and has_payout_phone:
            counts["completed"] += 1
        elif has_phone and has_relation:
            counts["name_phone_relation"] += 1
        elif has_phone:
            counts["name_phone"] += 1
        elif lead.client_name:
            counts["only_name"] += 1
        else:
            counts["other"] += 1

    def item(value: int) -> dict[str, int | float]:
        percent = round((value / total * 100), 1) if total else 0
        return {"count": value, "percent": percent}

    return {
        "total": total,
        "only_name": item(counts["only_name"]),
        "name_phone": item(counts["name_phone"]),
        "name_phone_relation": item(counts["name_phone_relation"]),
        "completed": item(counts["completed"]),
        "other": item(counts["other"]),
    }


async def manager_stats(session: AsyncSession, manager_id: int) -> dict[str, int]:
    return {
        "my_in_progress": int(
            (await session.scalar(
                select(func.count(Lead.id)).where(
                    Lead.assigned_manager_id == manager_id,
                    Lead.status == LeadStatus.IN_PROGRESS.value,
                )
            ))
            or 0
        ),
        "my_closed": int(
            (await session.scalar(
                select(func.count(Lead.id)).where(
                    Lead.assigned_manager_id == manager_id,
                    Lead.status == LeadStatus.CLOSED.value,
                )
            ))
            or 0
        ),
    }
