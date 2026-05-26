from __future__ import annotations

import logging

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import InlineKeyboardMarkup
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import User
from app.services.developer import (
    STAFF_NOTIFICATIONS,
    can_send_to_user,
    fallback_developer_recipient,
    get_bool,
    participant_recipients,
    test_mode_enabled,
)

logger = logging.getLogger(__name__)


async def notification_recipients(session: AsyncSession, platform: str = "telegram") -> list[User]:
    if await test_mode_enabled(session):
        if not await get_bool(session, STAFF_NOTIFICATIONS):
            return []
        recipients = await participant_recipients(session, platform, roles={"manager", "admin"})
        if recipients:
            return [user for user in recipients if await can_send_to_user(session, user, STAFF_NOTIFICATIONS)]
        if platform == "telegram":
            fallback = await fallback_developer_recipient(session, get_settings())
            return [user for user in fallback if await can_send_to_user(session, user, STAFF_NOTIFICATIONS)]
        return []

    result = await session.execute(
        select(User).where(
            User.platform == platform,
            ((User.is_manager.is_(True)) | (User.is_admin.is_(True))),
            ((User.is_admin.is_(False)) | (User.admin_notifications_enabled.is_(True))),
        )
    )
    users = list(result.scalars().all())
    return [user for user in users if await can_send_to_user(session, user, STAFF_NOTIFICATIONS)]


async def notify_staff(
    bot: Bot,
    session: AsyncSession,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> None:
    for user in await notification_recipients(session, platform="telegram"):
        try:
            if user.telegram_id is not None:
                await bot.send_message(user.telegram_id, text, reply_markup=reply_markup)
        except TelegramAPIError:
            logger.exception("Failed to notify staff user %s", user.telegram_id)
