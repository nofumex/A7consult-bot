from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.filters import ExceptionTypeFilter
from aiogram.types import BotCommand, ErrorEvent

from app.config import Settings
from app.database import SessionLocal
from app.handlers import admin, agent, chat, commands, developer, manager, profile, user
from app.middlewares.role_middleware import DbUserMiddleware
from app.keyboards.manager_keyboards import lead_actions
from app.services.delayed_notifications import due_agent_client_leads, mark_staff_notified
from app.services.notifications import notify_staff
from app.utils.text import new_lead_notification


async def set_commands(bot: Bot) -> None:
    await bot.set_my_commands(
        [
            BotCommand(command="start", description="Старт"),
            BotCommand(command="profile", description="Профиль"),
            BotCommand(command="consultation", description="Бесплатная консультация"),
            BotCommand(command="ref_url", description="Реферальная ссылка"),
            BotCommand(command="tutor", description="Связь с менеджером"),
            BotCommand(command="new_client", description="Новый клиент"),
            BotCommand(command="manager", description="Панель менеджера"),
            BotCommand(command="admin", description="Админ-панель"),
            BotCommand(command="dev", description="Developer panel"),
            BotCommand(command="endchat", description="Завершить чат"),
            BotCommand(command="cancel", description="Отменить действие"),
            BotCommand(command="help", description="Помощь"),
        ]
    )


async def on_error(event: ErrorEvent) -> None:
    if isinstance(event.exception, TelegramBadRequest) and "query is too old" in str(event.exception):
        logging.info("Ignored expired callback query answer")
        return

    logging.exception("Unhandled Telegram update error", exc_info=event.exception)
    update = event.update
    try:
        if update.message:
            await update.message.answer("Произошла техническая ошибка. Мы уже записали её в лог.")
        elif update.callback_query and update.callback_query.message:
            await update.callback_query.message.answer("Произошла техническая ошибка. Мы уже записали её в лог.")
    except TelegramAPIError:
        logging.exception("Failed to send Telegram error message")


async def send_due_agent_client_notifications(bot: Bot, settings: Settings) -> None:
    while True:
        try:
            async with SessionLocal() as session:
                leads = await due_agent_client_leads(
                    session,
                    "telegram",
                    settings.agent_client_notification_delay_seconds,
                )
                for lead in leads:
                    await session.refresh(lead, ["agent"])
                    await notify_staff(
                        bot,
                        session,
                        new_lead_notification(lead, "Новый клиент от агента"),
                        reply_markup=lead_actions(lead.id, include_bonus=True),
                    )
                    await mark_staff_notified(session, lead)
        except asyncio.CancelledError:
            raise
        except Exception:
            logging.exception("Failed to send delayed Telegram lead notifications")
        await asyncio.sleep(15)


async def run_telegram_bot(settings: Settings) -> None:
    bot = Bot(settings.telegram_bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(settings=settings)
    middleware = DbUserMiddleware(settings)
    dp.message.outer_middleware(middleware)
    dp.callback_query.outer_middleware(middleware)

    dp.errors.register(on_error, ExceptionTypeFilter(Exception))

    dp.include_router(commands.router)
    dp.include_router(user.router)
    dp.include_router(profile.router)
    dp.include_router(agent.router)
    dp.include_router(developer.router)
    dp.include_router(admin.router)
    dp.include_router(manager.router)
    dp.include_router(chat.router)

    try:
        delayed_task = asyncio.create_task(send_due_agent_client_notifications(bot, settings))
        if settings.drop_pending_updates:
            await bot.delete_webhook(drop_pending_updates=True)
        await set_commands(bot)
        logging.info("Telegram polling started")
        await dp.start_polling(bot)
    finally:
        delayed_task.cancel()
        await bot.session.close()
