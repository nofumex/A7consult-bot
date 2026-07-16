from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from sqlalchemy import select

from app.config import get_settings
from app.database import SessionLocal
from app.models import Bonus, DeveloperSetting, Lead, User
from app.services.amocrm import sync_agent_event_to_amocrm

logger = logging.getLogger(__name__)

BACKFILL_KEY = "agent_amocrm_backfill_v1"


async def run_agent_crm_backfill_once() -> None:
    settings = get_settings()
    if not (settings.amocrm_base_url and settings.amocrm_access_token and settings.amocrm_agent_pipeline_id):
        return

    async with SessionLocal() as session:
        if await session.get(DeveloperSetting, BACKFILL_KEY):
            return

        users = list((await session.execute(select(User).order_by(User.id))).scalars().all())
        client_rows = list(
            (
                await session.execute(
                    select(Lead)
                    .where(
                        Lead.type == "agent_client",
                        Lead.agent_id.is_not(None),
                        Lead.client_name.is_not(None),
                        Lead.client_name != "",
                        Lead.phone.is_not(None),
                        Lead.phone != "",
                    )
                    .order_by(Lead.id)
                )
            )
            .scalars()
            .all()
        )
        bonus_rows = list((await session.execute(select(Bonus).order_by(Bonus.id))).scalars().all())

        latest_client_by_agent = {int(lead.agent_id): lead for lead in client_rows if lead.agent_id}
        latest_bonus_by_agent = {int(bonus.agent_id): bonus for bonus in bonus_rows}
        errors = 0

        logger.info("Starting one-time agent amoCRM backfill for %s users", len(users))
        for user in users:
            payload: dict[str, object] = {"_backfill": True}
            if user.id in latest_bonus_by_agent:
                bonus = latest_bonus_by_agent[user.id]
                event_type = "first_bonus_awarded"
                payload.update(
                    bonus_id=bonus.id,
                    amount=bonus.amount,
                    comment=bonus.comment or "",
                    lead_id=bonus.lead_id,
                )
            elif user.id in latest_client_by_agent:
                lead = latest_client_by_agent[user.id]
                event_type = "client_data_submitted"
                payload.update(lead_id=lead.id, client_name=lead.client_name or "", phone=lead.phone or "")
            elif user.is_agent:
                event_type = "became_agent"
            else:
                event_type = "subscribed"

            await sync_agent_event_to_amocrm(session, user, event_type, payload)
            if user.amo_agent_sync_status == "error":
                errors += 1
            await asyncio.sleep(0.25)

        if errors:
            logger.error("Agent amoCRM backfill finished with %s errors; it will retry after the next restart", errors)
            return

        session.add(
            DeveloperSetting(
                key=BACKFILL_KEY,
                value=f"completed:{datetime.utcnow().isoformat(timespec='seconds')}:users={len(users)}",
            )
        )
        await session.commit()
        logger.info("Agent amoCRM backfill completed for %s users", len(users))
