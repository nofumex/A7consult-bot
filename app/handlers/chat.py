from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import ChatStatus
from app.keyboards.manager_keyboards import chat_manager_menu
from app.keyboards.user_keyboards import chat_end_menu
from app.models import User
from app.services.chat_sessions import (
    close_session,
    connect_manager,
    get_manager_active_session,
    get_session,
    get_user_active_session,
    open_session,
    save_message,
)
from app.services.developer import CHAT_BRIDGE, can_send_to_user, can_touch_lead, is_participant_user, test_mode_enabled
from app.services.leads import get_lead
from app.services.notifications import notify_staff
from app.services.users import get_by_id
from app.utils.permissions import is_manager
from app.utils.text import full_name, h, username_text

router = Router(name="chat")


def connect_chat_keyboard(session_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="Подключиться в чат", callback_data=f"chat:session:{session_id}", style="success")]]
    )


async def _start_chat(
    message: Message,
    bot: Bot,
    session: AsyncSession,
    current_user: User,
    title: str = "Пользователь хочет связаться с менеджером",
) -> None:
    if await test_mode_enabled(session) and not await is_participant_user(session, current_user):
        await message.answer("Сейчас включен тестовый режим. Чат доступен только участникам теста.")
        return
    existing = await get_user_active_session(session, current_user.id)
    chat = existing or await open_session(session, current_user)
    if existing:
        await message.answer(
            "У вас уже открыт чат с менеджером. Напишите сообщение здесь, и оно попадёт в текущий диалог.",
            reply_markup=chat_end_menu(),
        )
        return
    await message.answer(
        "Напишите сообщение, и свободный менеджер подключится к диалогу.",
        reply_markup=chat_end_menu(),
    )
    text = (
        f"<b>{h(title)}</b>\n\n"
        f"<b>Имя:</b> {full_name(current_user)}\n"
        f"<b>Username:</b> {username_text(current_user)}\n"
        f"<b>Telegram ID:</b> <code>{current_user.telegram_id}</code>"
    )
    await notify_staff(bot, session, text, reply_markup=connect_chat_keyboard(chat.id))


@router.message(Command("tutor"))
async def cmd_tutor(message: Message, bot: Bot, session: AsyncSession, current_user: User) -> None:
    await _start_chat(message, bot, session, current_user)


@router.callback_query(F.data.in_({"chat:start_user", "chat:start_agent"}))
async def cb_start_chat(callback: CallbackQuery, bot: Bot, session: AsyncSession, current_user: User) -> None:
    title = "Агент хочет связаться с менеджером" if callback.data == "chat:start_agent" else "Пользователь хочет связаться с менеджером"
    await _start_chat(callback.message, bot, session, current_user, title=title)
    await callback.answer()


@router.callback_query(F.data.startswith("chat:session:"))
async def cb_connect_session(callback: CallbackQuery, bot: Bot, session: AsyncSession, current_user: User) -> None:
    if not is_manager(current_user):
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    session_id = int(callback.data.split(":")[-1])
    chat = await get_session(session, session_id)
    if not chat or chat.status == ChatStatus.CLOSED.value:
        await callback.answer("Чат уже закрыт", show_alert=True)
        return
    await session.refresh(chat, ["user"])
    if chat.user.platform != current_user.platform:
        await callback.answer("Этот чат относится к другой платформе", show_alert=True)
        return
    if not await can_send_to_user(session, chat.user, CHAT_BRIDGE):
        await callback.answer("Тестовый режим: чат не входит в список участников", show_alert=True)
        return
    chat, connected, manager_busy = await connect_manager(session, chat, current_user)
    if manager_busy:
        await callback.answer("У вас уже есть активный чат", show_alert=True)
        return
    if not connected:
        await callback.answer("Уже подключился другой менеджер", show_alert=True)
        return

    await callback.message.answer(
        f"Вы подключились к чату с пользователем {full_name(chat.user)}. Пишите сообщения сюда.",
        reply_markup=chat_manager_menu(),
    )
    if await can_send_to_user(session, chat.user, CHAT_BRIDGE):
        await bot.send_message(chat.user.telegram_id, "Менеджер подключился к диалогу.", reply_markup=chat_end_menu())
    await callback.answer("Чат подключён")


@router.callback_query(F.data.startswith("chat:lead:"))
async def cb_connect_lead_chat(callback: CallbackQuery, bot: Bot, session: AsyncSession, current_user: User) -> None:
    if not is_manager(current_user):
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    lead_id = int(callback.data.split(":")[-1])
    lead = await get_lead(session, lead_id)
    if not lead or lead.platform != current_user.platform:
        await callback.answer("Заявка не найдена", show_alert=True)
        return
    if not await can_touch_lead(session, lead):
        await callback.answer("Тестовый режим: заявка не входит в список участников", show_alert=True)
        return
    await session.refresh(lead, ["user", "agent"])
    target = lead.user or lead.agent
    if not target or target.platform != current_user.platform:
        await callback.answer("У заявки нет пользователя для чата", show_alert=True)
        return
    chat = await open_session(session, target)
    chat, connected, manager_busy = await connect_manager(session, chat, current_user)
    if manager_busy:
        await callback.answer("У вас уже есть активный чат", show_alert=True)
        return
    if not connected:
        await callback.answer("Уже подключился другой менеджер", show_alert=True)
        return
    await callback.message.answer(f"Чат по заявке #{lead.id} подключён. Пишите сообщения сюда.", reply_markup=chat_manager_menu())
    if await can_send_to_user(session, target, CHAT_BRIDGE):
        await bot.send_message(target.telegram_id, "Менеджер подключился к диалогу по вашей заявке.", reply_markup=chat_end_menu())
    await callback.answer()


@router.callback_query(F.data.startswith("chat:user:"))
async def cb_open_user_chat(callback: CallbackQuery, bot: Bot, session: AsyncSession, current_user: User) -> None:
    if not is_manager(current_user):
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    user_id = int(callback.data.split(":")[-1])
    target = await get_by_id(session, user_id)
    if not target or target.platform != current_user.platform:
        await callback.answer("Пользователь не найден", show_alert=True)
        return
    if not await can_send_to_user(session, target, CHAT_BRIDGE):
        await callback.answer("Тестовый режим: пользователь не входит в список участников", show_alert=True)
        return
    chat = await open_session(session, target)
    chat, connected, manager_busy = await connect_manager(session, chat, current_user)
    if manager_busy:
        await callback.answer("У вас уже есть активный чат", show_alert=True)
        return
    if not connected:
        await callback.answer("Уже подключился другой менеджер", show_alert=True)
        return
    await callback.message.answer(f"Чат с {full_name(target)} открыт.", reply_markup=chat_manager_menu())
    await bot.send_message(target.telegram_id, "Менеджер открыл чат с вами.", reply_markup=chat_end_menu())
    await callback.answer()


@router.message(Command("endchat"))
@router.callback_query(F.data == "chat:end")
async def end_chat(event: Message | CallbackQuery, bot: Bot, session: AsyncSession, current_user: User) -> None:
    target = event.message if isinstance(event, CallbackQuery) else event
    chat = await get_manager_active_session(session, current_user.id) if is_manager(current_user) else None
    chat = chat or await get_user_active_session(session, current_user.id)
    if not chat:
        await target.answer("Активного чата сейчас нет.")
        if isinstance(event, CallbackQuery):
            await event.answer()
        return
    await session.refresh(chat, ["user", "manager"])
    await close_session(session, chat)
    await target.answer("Чат завершён.")
    if chat.user_id != current_user.id and await can_send_to_user(session, chat.user, CHAT_BRIDGE):
        await bot.send_message(chat.user.telegram_id, "Чат завершён.")
    if chat.manager and chat.manager_id != current_user.id and await can_send_to_user(session, chat.manager, CHAT_BRIDGE):
        await bot.send_message(chat.manager.telegram_id, "Чат завершён.")
    if isinstance(event, CallbackQuery):
        await event.answer()


@router.message(F.text)
async def relay_chat_message(message: Message, bot: Bot, session: AsyncSession, current_user: User) -> None:
    if message.text.startswith("/"):
        return

    if is_manager(current_user):
        chat = await get_manager_active_session(session, current_user.id)
        if chat:
            await session.refresh(chat, ["user"])
            await save_message(session, chat, current_user, message.text, "manager")
            if await can_send_to_user(session, chat.user, CHAT_BRIDGE):
                await bot.send_message(chat.user.telegram_id, f"<b>Менеджер:</b>\n{h(message.text)}", reply_markup=chat_end_menu())
            else:
                await message.answer("Тестовый режим: сообщение не отправлено пользователю вне списка участников.")
            return

    chat = await get_user_active_session(session, current_user.id)
    if not chat:
        return
    await session.refresh(chat, ["manager"])
    await save_message(session, chat, current_user, message.text, "user")
    if chat.status == ChatStatus.ACTIVE.value and chat.manager:
        if await can_send_to_user(session, chat.manager, CHAT_BRIDGE):
            await bot.send_message(
                chat.manager.telegram_id,
                f"{full_name(current_user)} ({username_text(current_user)}):\n{h(message.text)}",
                reply_markup=chat_manager_menu(),
            )
        else:
            await message.answer("Тестовый режим: сообщение не отправлено менеджеру вне списка участников.")
    else:
        await message.answer("Сообщение сохранено. Менеджер подключится, как только освободится.", reply_markup=chat_end_menu())
