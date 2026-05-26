from __future__ import annotations

import asyncio
import logging

from app.adapters.max.client import MaxBotClient
from app.adapters.max import keyboards
from app.adapters.max.handlers import handle_update, notify_staff
from app.adapters.max.mapper import parse_update
from app.config import Settings
from app.database import SessionLocal
from app.services.delayed_notifications import due_agent_client_leads, mark_staff_notified
from app.utils.text import new_lead_notification

logger = logging.getLogger(__name__)


async def send_due_agent_client_notifications(client: MaxBotClient, settings: Settings) -> None:
    while True:
        try:
            async with SessionLocal() as session:
                leads = await due_agent_client_leads(
                    session,
                    "max",
                    settings.agent_client_notification_delay_seconds,
                )
                for lead in leads:
                    await session.refresh(lead, ["agent"])
                    await notify_staff(
                        client,
                        new_lead_notification(lead, "Новый клиент от агента"),
                        keyboards.lead_actions(lead.id, include_bonus=True),
                    )
                    await mark_staff_notified(session, lead)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Failed to send delayed MAX lead notifications")
        await asyncio.sleep(15)


async def run_max_bot(settings: Settings) -> None:
    marker: int | None = None
    async with MaxBotClient(settings.max_bot_token, settings.max_api_base_url) as client:
        delayed_task = asyncio.create_task(send_due_agent_client_notifications(client, settings))
        logger.info("MAX polling started")
        try:
            while True:
                try:
                    payload = await client.get_updates(marker=marker)
                    marker = payload.get("marker", marker)
                    for raw_update in payload.get("updates", []):
                        event = parse_update(raw_update)
                        if not event:
                            continue
                        try:
                            await handle_update(client, event, settings)
                        except Exception:
                            logger.exception("MAX update handling failed")
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception("MAX polling error")
                    await asyncio.sleep(3)
        finally:
            delayed_task.cancel()
