from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.keyboards.admin_keyboards import (
    developer_back,
    developer_mute_actions,
    developer_panel,
    developer_participant_actions,
    developer_role_choice,
)
from app.models import User
from app.services.developer import (
    FEATURE_LABELS,
    MUTE_FIELD_BY_KEY,
    add_or_update_participant,
    get_participant,
    get_user_mute,
    is_developer,
    list_participants,
    participant_line,
    remove_participant,
    status,
    toggle_bool,
    toggle_participant,
    toggle_user_mute,
    user_mute_line,
)
from app.services.users import search_user
from app.states.admin_states import DeveloperStates
from app.utils.text import full_name, username_text

router = Router(name="developer")


async def _ensure_dev_message(message: Message, current_user: User, settings: Settings) -> bool:
    if not is_developer(current_user, settings):
        await message.answer("Developer panel доступна только DEV_ID.")
        return False
    return True


async def _ensure_dev_callback(callback: CallbackQuery, current_user: User, settings: Settings) -> bool:
    if not is_developer(current_user, settings):
        await callback.answer("Developer panel доступна только DEV_ID", show_alert=True)
        return False
    return True


def _status_text(data: dict[str, bool | int]) -> str:
    mode = "включен" if data["test_mode_enabled"] else "выключен"
    return (
        "<b>Developer panel</b>\n\n"
        f"Тестовый режим: <b>{mode}</b>\n"
        f"Участников теста: <b>{data['participants_enabled']}</b> активных / {data['participants_total']} всего\n\n"
        "Когда тестовый режим включен, заявки, рассылки, бонусные уведомления и чаты отправляются только участникам теста. "
        "Если тестовые менеджеры не заданы, уведомления по Telegram уходят только DEV_ID."
    )


@router.message(Command("dev"))
async def cmd_dev(message: Message, session: AsyncSession, current_user: User, settings: Settings) -> None:
    if not await _ensure_dev_message(message, current_user, settings):
        return
    await message.answer(_status_text(await status(session)), reply_markup=developer_panel(await status(session)))


@router.callback_query(F.data == "dev:panel")
async def cb_dev_panel(callback: CallbackQuery, session: AsyncSession, current_user: User, settings: Settings) -> None:
    if not await _ensure_dev_callback(callback, current_user, settings):
        return
    data = await status(session)
    await callback.message.answer(_status_text(data), reply_markup=developer_panel(data))
    await callback.answer()


@router.callback_query(F.data.startswith("dev:toggle:"))
async def cb_dev_toggle(callback: CallbackQuery, session: AsyncSession, current_user: User, settings: Settings) -> None:
    if not await _ensure_dev_callback(callback, current_user, settings):
        return
    key = callback.data.split(":", 2)[-1]
    if key not in FEATURE_LABELS:
        await callback.answer("Неизвестная функция", show_alert=True)
        return
    value = await toggle_bool(session, key)
    data = await status(session)
    await callback.message.answer(
        f"{FEATURE_LABELS[key]}: {'Вкл' if value else 'Выкл'}",
        reply_markup=developer_panel(data),
    )
    await callback.answer()


@router.callback_query(F.data == "dev:add")
async def cb_dev_add(callback: CallbackQuery, state: FSMContext, current_user: User, settings: Settings) -> None:
    if not await _ensure_dev_callback(callback, current_user, settings):
        return
    await state.set_state(DeveloperStates.waiting_user_query)
    await callback.message.answer(
        "Отправьте Telegram ID, username или внутренний ID пользователя, которого нужно добавить в тестовый режим.",
        reply_markup=developer_back(),
    )
    await callback.answer()


@router.callback_query(F.data == "dev:mutes")
async def cb_dev_mutes(callback: CallbackQuery, state: FSMContext, current_user: User, settings: Settings) -> None:
    if not await _ensure_dev_callback(callback, current_user, settings):
        return
    await state.set_state(DeveloperStates.waiting_mute_user_query)
    await callback.message.answer(
        "Отправьте Telegram ID, username или внутренний ID пользователя, которому нужно отключить рассылки.",
        reply_markup=developer_back(),
    )
    await callback.answer()


@router.message(DeveloperStates.waiting_user_query, ~F.text.startswith("/"))
async def process_dev_user_query(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    current_user: User,
    settings: Settings,
) -> None:
    if not await _ensure_dev_message(message, current_user, settings):
        await state.clear()
        return
    user = await search_user(session, message.text or "")
    await state.clear()
    if not user:
        await message.answer("Пользователь не найден. Он должен хотя бы один раз открыть бота.", reply_markup=developer_back())
        return
    await message.answer(
        f"Добавить в тестовый режим:\n"
        f"{full_name(user)} ({username_text(user)})\n"
        f"Telegram ID: <code>{user.telegram_id}</code>",
        reply_markup=developer_role_choice(user.id),
    )


@router.message(DeveloperStates.waiting_mute_user_query, ~F.text.startswith("/"))
async def process_dev_mute_user_query(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    current_user: User,
    settings: Settings,
) -> None:
    if not await _ensure_dev_message(message, current_user, settings):
        await state.clear()
        return
    user = await search_user(session, message.text or "")
    await state.clear()
    if not user:
        await message.answer("Пользователь не найден. Он должен хотя бы один раз открыть бота.", reply_markup=developer_back())
        return
    mute = await get_user_mute(session, user.id)
    await message.answer(user_mute_line(user, mute), reply_markup=developer_mute_actions(user.id))


@router.callback_query(F.data.startswith("dev:mute_toggle:"))
async def cb_dev_mute_toggle(callback: CallbackQuery, session: AsyncSession, current_user: User, settings: Settings) -> None:
    if not await _ensure_dev_callback(callback, current_user, settings):
        return
    _, _, user_id, key = callback.data.split(":", 3)
    if key not in MUTE_FIELD_BY_KEY:
        await callback.answer("Неизвестный тип рассылки", show_alert=True)
        return
    user = await session.get(User, int(user_id))
    if not user:
        await callback.answer("Пользователь не найден", show_alert=True)
        return
    mute = await toggle_user_mute(session, user, key)
    await callback.message.answer(user_mute_line(user, mute), reply_markup=developer_mute_actions(user.id))
    await callback.answer()


@router.callback_query(F.data.startswith("dev:add_role:"))
async def cb_dev_add_role(callback: CallbackQuery, session: AsyncSession, current_user: User, settings: Settings) -> None:
    if not await _ensure_dev_callback(callback, current_user, settings):
        return
    _, _, user_id, role = callback.data.split(":", 3)
    user = await session.get(User, int(user_id))
    if not user:
        await callback.answer("Пользователь не найден", show_alert=True)
        return
    participant = await add_or_update_participant(session, user, role)
    await session.refresh(participant, ["user"])
    await callback.message.answer(
        f"Участник теста добавлен:\n{participant_line(participant)}",
        reply_markup=developer_participant_actions(participant.id, participant.enabled),
    )
    await callback.answer()


@router.callback_query(F.data == "dev:participants")
async def cb_dev_participants(callback: CallbackQuery, session: AsyncSession, current_user: User, settings: Settings) -> None:
    if not await _ensure_dev_callback(callback, current_user, settings):
        return
    participants = await list_participants(session, platform="telegram")
    if not participants:
        await callback.message.answer("Участников теста пока нет.", reply_markup=developer_back())
        await callback.answer()
        return
    for participant in participants[:20]:
        await session.refresh(participant, ["user"])
        await callback.message.answer(
            participant_line(participant),
            reply_markup=developer_participant_actions(participant.id, participant.enabled),
        )
    await callback.answer()


@router.callback_query(F.data.startswith("dev:participant_toggle:"))
async def cb_dev_participant_toggle(callback: CallbackQuery, session: AsyncSession, current_user: User, settings: Settings) -> None:
    if not await _ensure_dev_callback(callback, current_user, settings):
        return
    participant = await get_participant(session, int(callback.data.split(":")[-1]))
    if not participant:
        await callback.answer("Участник не найден", show_alert=True)
        return
    participant = await toggle_participant(session, participant)
    await session.refresh(participant, ["user"])
    await callback.message.answer(
        participant_line(participant),
        reply_markup=developer_participant_actions(participant.id, participant.enabled),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("dev:participant_remove:"))
async def cb_dev_participant_remove(callback: CallbackQuery, session: AsyncSession, current_user: User, settings: Settings) -> None:
    if not await _ensure_dev_callback(callback, current_user, settings):
        return
    participant = await get_participant(session, int(callback.data.split(":")[-1]))
    if not participant:
        await callback.answer("Участник не найден", show_alert=True)
        return
    await remove_participant(session, participant)
    await callback.message.answer("Участник удален из тестового режима.", reply_markup=developer_back())
    await callback.answer()
