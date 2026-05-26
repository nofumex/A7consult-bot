from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models import User
from app.services.developer import is_developer
from app.services.reset import reset_database_and_sheet

router = Router(name="commands")


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(
        "<b>Помощь по боту «А7 Консалт»</b>\n\n"
        "<b>Для клиента</b>\n"
        "<code>/start</code> - главное меню\n"
        "<code>/consultation</code> - записаться на бесплатную консультацию\n"
        "<code>/tutor</code> - связаться с менеджером\n"
        "<code>/profile</code> - открыть профиль\n\n"
        "<b>Для агента</b>\n"
        "<code>/ref_url</code> - реферальная ссылка\n"
        "<code>/new_client</code> - передать нового клиента\n\n"
        "<b>Для команды</b>\n"
        "<code>/manager</code> - панель менеджера\n"
        "<code>/admin</code> - админ-панель\n"
        "<code>/dev</code> - developer panel\n"
        "<code>/endchat</code> - завершить активный чат\n"
        "<code>/cancel</code> - отменить текущий сценарий"
    )


@router.message(Command("reset_db"))
async def cmd_reset_db(message: Message, session: AsyncSession, current_user: User, settings: Settings) -> None:
    if not is_developer(current_user, settings):
        await message.answer("Команда доступна только DEV_ID.")
        return
    await reset_database_and_sheet(session)
    await message.answer("База и Google-таблица сброшены. В таблице оставлены только заголовки колонок.")


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Текущее действие отменено. Можно выбрать нужный раздел заново через /start.")
