from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import LeadStatus, LeadType
from app.models import Lead, User
from app.services.amocrm import enqueue_amocrm_sync
from app.services.sheets import enqueue_lead_sync


async def create_consultation_lead(session: AsyncSession, user: User, phone: str) -> Lead:
    user.phone = phone
    lead = Lead(
        type=LeadType.CONSULTATION.value,
        status=LeadStatus.NEW.value,
        platform=user.platform or "telegram",
        user_id=user.id,
        agent_id=user.referrer_id,
        client_name=" ".join(part for part in [user.first_name, user.last_name] if part) or user.username,
        phone=phone,
    )
    session.add(lead)
    await session.commit()
    await session.refresh(lead, ["user", "agent"])
    enqueue_lead_sync(lead.id)
    enqueue_amocrm_sync(lead.id)
    return lead


async def create_question_lead(session: AsyncSession, user: User, question: str) -> Lead:
    lead = Lead(type=LeadType.QUESTION.value, status=LeadStatus.NEW.value, user_id=user.id, question_text=question)
    lead.platform = user.platform or "telegram"
    session.add(lead)
    await session.commit()
    await session.refresh(lead, ["user"])
    enqueue_lead_sync(lead.id)
    enqueue_amocrm_sync(lead.id)
    return lead


async def create_agent_client_lead(
    session: AsyncSession,
    agent: User,
    client_name: str,
    phone: str,
    city: str | None = None,
    debt_amount: str | None = None,
    comment: str = "",
    relation_to_agent: str | None = None,
    agent_payout_phone: str | None = None,
) -> Lead:
    if agent_payout_phone:
        agent.phone = agent_payout_phone
    lead = Lead(
        type=LeadType.AGENT_CLIENT.value,
        status=LeadStatus.NEW.value,
        platform=agent.platform or "telegram",
        agent_id=agent.id,
        client_name=client_name,
        phone=phone,
        city=city,
        debt_amount=debt_amount,
        relation_to_agent=relation_to_agent,
        agent_payout_phone=agent_payout_phone,
        comment=comment,
    )
    session.add(lead)
    await session.commit()
    await session.refresh(lead, ["agent"])
    enqueue_lead_sync(lead.id)
    return lead


async def create_agent_client_lead_draft(session: AsyncSession, agent: User, client_name: str) -> Lead:
    lead = Lead(
        type=LeadType.AGENT_CLIENT.value,
        status=LeadStatus.NEW.value,
        platform=agent.platform or "telegram",
        agent_id=agent.id,
        client_name=client_name,
    )
    session.add(lead)
    await session.commit()
    await session.refresh(lead, ["agent"])
    enqueue_lead_sync(lead.id)
    return lead


async def update_agent_client_lead(
    session: AsyncSession,
    lead: Lead,
    *,
    phone: str | None = None,
    relation_to_agent: str | None = None,
    agent_payout_phone: str | None = None,
    comment: str | None = None,
) -> Lead:
    if phone is not None:
        lead.phone = phone
    if relation_to_agent is not None:
        lead.relation_to_agent = relation_to_agent
    if agent_payout_phone is not None:
        lead.agent_payout_phone = agent_payout_phone
        await session.refresh(lead, ["agent"])
        if lead.agent:
            lead.agent.phone = agent_payout_phone
    if comment is not None:
        lead.comment = comment
    await session.commit()
    await session.refresh(lead, ["agent"])
    enqueue_lead_sync(lead.id)
    enqueue_amocrm_sync(lead.id)
    return lead


async def append_agent_followup_answer(session: AsyncSession, lead: Lead, label: str, answer: str) -> Lead:
    line = f"{label}: {answer}"
    comment = f"{lead.comment}\n{line}" if lead.comment else line
    return await update_agent_client_lead(session, lead, comment=comment)


async def get_lead(session: AsyncSession, lead_id: int) -> Lead | None:
    return await session.get(Lead, lead_id)


async def list_leads(
    session: AsyncSession,
    status: str | None = None,
    manager_id: int | None = None,
    limit: int = 10,
    platform: str | None = None,
) -> list[Lead]:
    stmt = select(Lead).order_by(Lead.created_at.desc()).limit(limit)
    if status:
        stmt = stmt.where(Lead.status == status)
    if manager_id:
        stmt = stmt.where(Lead.assigned_manager_id == manager_id)
        stmt = stmt.where(~Lead.status.in_([LeadStatus.CLOSED.value, LeadStatus.CANCELED.value]))
    if platform:
        stmt = stmt.where(Lead.platform == platform)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def list_open_leads(session: AsyncSession, limit: int = 10, platform: str | None = None) -> list[Lead]:
    stmt = (
        select(Lead)
        .where(Lead.status == LeadStatus.NEW.value, Lead.assigned_manager_id.is_(None))
        .order_by(Lead.created_at.desc())
        .limit(limit)
    )
    if platform:
        stmt = stmt.where(Lead.platform == platform)
    result = await session.execute(
        stmt
    )
    return list(result.scalars().all())


async def list_leads_by_platform(
    session: AsyncSession,
    platform: str,
    status: str | None = None,
    manager_id: int | None = None,
    only_unassigned: bool = False,
    limit: int = 10,
) -> list[Lead]:
    stmt = select(Lead).where(Lead.platform == platform).order_by(Lead.created_at.desc()).limit(limit)
    if status:
        stmt = stmt.where(Lead.status == status)
    if manager_id:
        stmt = stmt.where(Lead.assigned_manager_id == manager_id)
        stmt = stmt.where(~Lead.status.in_([LeadStatus.CLOSED.value, LeadStatus.CANCELED.value]))
    if only_unassigned:
        stmt = stmt.where(Lead.assigned_manager_id.is_(None))
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def take_lead(session: AsyncSession, lead: Lead, manager: User) -> tuple[Lead, bool]:
    if lead.platform != manager.platform or lead.status in {LeadStatus.CLOSED.value, LeadStatus.CANCELED.value}:
        return lead, False
    if lead.assigned_manager_id and lead.assigned_manager_id != manager.id:
        return lead, False
    lead.assigned_manager_id = manager.id
    lead.status = LeadStatus.IN_PROGRESS.value
    await session.commit()
    await session.refresh(lead)
    enqueue_lead_sync(lead.id)
    enqueue_amocrm_sync(lead.id)
    return lead, True


async def close_lead(session: AsyncSession, lead: Lead) -> Lead:
    lead.status = LeadStatus.CLOSED.value
    lead.closed_at = datetime.utcnow()
    await session.commit()
    await session.refresh(lead)
    enqueue_lead_sync(lead.id)
    enqueue_amocrm_sync(lead.id)
    return lead
