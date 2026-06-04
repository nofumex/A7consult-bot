from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.keyboards.user_keyboards import agent_menu, agent_rules_menu, main_menu
from app.models import User
from app.services.bonuses import bonus_totals, recent_bonuses
from app.services.developer import is_participant_user, test_mode_enabled
from app.services.leads import create_agent_client_lead_draft, get_lead, update_agent_client_lead
from app.services.referrals import recent_referrals
from app.services.users import set_agent
from app.states.manager_states import AgentClientStates
from app.utils.assets import AGENT_IMAGE, PARTNER_IMAGE, local_photo
from app.utils.text import agent_welcome_text, bonus_line, h, money, referral_rules_text
from app.utils.validators import clean_text, normalize_phone

router = Router(name="agent")


@router.callback_query(F.data == "agent:join")
async def cb_agent_join(callback: CallbackQuery, session: AsyncSession, current_user: User, settings: Settings) -> None:
    if not current_user.is_agent:
        await set_agent(session, current_user)
    photo = local_photo(AGENT_IMAGE)
    if photo:
        await callback.message.answer_photo(photo)
    await callback.message.answer(agent_welcome_text(settings), reply_markup=agent_menu())
    await callback.answer()


@router.callback_query(F.data == "agent:rules")
async def cb_agent_rules(callback: CallbackQuery, settings: Settings) -> None:
    await callback.message.answer(referral_rules_text(settings), reply_markup=agent_rules_menu())
    await callback.answer()


@router.message(Command("new_client"))
@router.callback_query(F.data == "agent:new_client")
async def start_new_client(event: Message | CallbackQuery, state: FSMContext, session: AsyncSession, current_user: User) -> None:
    if await test_mode_enabled(session) and not await is_participant_user(session, current_user):
        target = event.message if isinstance(event, CallbackQuery) else event
        await target.answer("Сейчас включен тестовый режим. Передача клиентов доступна только участникам теста.")
        if isinstance(event, CallbackQuery):
            await event.answer()
        return
    if not current_user.is_agent:
        await set_agent(session, current_user)
    photo = local_photo(PARTNER_IMAGE)
    await state.clear()
    await state.set_state(AgentClientStates.waiting_name)
    target = event.message if isinstance(event, CallbackQuery) else event
    if photo:
        await target.answer_photo(photo)
    await target.answer("<b>Новый клиент</b>\n\nВведите имя клиента.")
    if isinstance(event, CallbackQuery):
        await event.answer()


@router.message(AgentClientStates.waiting_name, ~F.text.startswith("/"))
async def new_client_name(message: Message, state: FSMContext, session: AsyncSession, current_user: User) -> None:
    name = clean_text(message.text, 255)
    if not name:
        await message.answer("Имя не должно быть пустым. Введите имя клиента.")
        return
    lead = await create_agent_client_lead_draft(session, current_user, name)
    await state.update_data(lead_id=lead.id, client_name=name)
    await state.set_state(AgentClientStates.waiting_phone)
    await message.answer("Введите телефон клиента.")


@router.message(AgentClientStates.waiting_phone, ~F.text.startswith("/"))
async def new_client_phone(message: Message, state: FSMContext, session: AsyncSession) -> None:
    phone = normalize_phone(message.text)
    if not phone:
        await message.answer("Телефон выглядит некорректно. Введите номер ещё раз.")
        return
    data = await state.get_data()
    lead = await get_lead(session, data["lead_id"])
    if lead:
        await update_agent_client_lead(session, lead, phone=phone)
    await state.update_data(phone=phone)
    await state.set_state(AgentClientStates.waiting_relation)
    await message.answer("Кем клиент вам приходится? Может ли он на вас сослаться?")


@router.message(AgentClientStates.waiting_relation, ~F.text.startswith("/"))
async def new_client_relation(message: Message, state: FSMContext, session: AsyncSession) -> None:
    relation = clean_text(message.text, 255) or "не указано"
    data = await state.get_data()
    lead = await get_lead(session, data["lead_id"])
    if lead:
        await update_agent_client_lead(session, lead, relation_to_agent=relation)
    await state.update_data(relation_to_agent=relation)
    await state.set_state(AgentClientStates.waiting_source_permission)
    await message.answer("Можно ли сообщить, что номер получили от вас?")


@router.message(AgentClientStates.waiting_source_permission, ~F.text.startswith("/"))
async def new_client_source_permission(message: Message, state: FSMContext, session: AsyncSession) -> None:
    permission = clean_text(message.text, 255) or "не указано"
    comment = f"Можно ли сообщить, что номер получили от вас? {permission}"
    data = await state.get_data()
    lead = await get_lead(session, data["lead_id"])
    if lead:
        await update_agent_client_lead(session, lead, comment=comment)
    await state.update_data(source_permission=permission)
    await state.set_state(AgentClientStates.waiting_payout_phone)
    await message.answer("По какому номеру с вами связываться для выплаты бонуса?")


@router.message(AgentClientStates.waiting_payout_phone, ~F.text.startswith("/"))
async def new_client_payout_phone(message: Message, state: FSMContext, session: AsyncSession) -> None:
    phone = normalize_phone(message.text)
    if not phone:
        await message.answer("Телефон выглядит некорректно. Введите номер ещё раз.")
        return
    data = await state.get_data()
    lead = await get_lead(session, data["lead_id"])
    if lead:
        await update_agent_client_lead(session, lead, agent_payout_phone=phone)
    await state.clear()
    await message.answer("<b>Спасибо.</b> Данные клиента переданы менеджерам «А7 Консалт».", reply_markup=agent_menu())


@router.callback_query(F.data == "agent:bonuses")
async def cb_agent_bonuses(callback: CallbackQuery, session: AsyncSession, current_user: User) -> None:
    totals = await bonus_totals(session, current_user.id)
    bonuses = await recent_bonuses(session, current_user.id)
    lines = [
        "<b>Заработанные бонусы</b>",
        "",
        f"<b>Всего начислено:</b> {money(totals['total'])} ₽",
        f"<b>Выплачено:</b> {money(totals['paid'])} ₽",
        f"<b>Ожидает выплаты:</b> {money(totals['pending'])} ₽",
        "",
        "Последние начисления:",
    ]
    lines.extend([bonus_line(item) for item in bonuses] or ["Начислений пока нет."])
    await callback.message.answer("\n".join(lines), reply_markup=agent_menu())
    await callback.answer()


@router.callback_query(F.data == "agent:referrals")
async def cb_agent_referrals(callback: CallbackQuery, session: AsyncSession, current_user: User) -> None:
    if not current_user.is_agent:
        await callback.message.answer(
            "Список рефералов доступен агентам. Нажмите «Хочу стать агентом» в Главном меню, чтобы подключиться.",
            reply_markup=main_menu(),
        )
        await callback.answer()
        return
    referrals = await recent_referrals(session, current_user.id, limit=10)
    if not referrals:
        await callback.message.answer("Рефералов пока нет. Получите ссылку и отправьте её тем, кому может быть полезна консультация.")
        await callback.answer()
        return
    lines = ["Последние рефералы", ""]
    for item in referrals:
        await session.refresh(item, ["referred"])
        username = f"@{item.referred.username}" if item.referred.username else "username не указан"
        lines.append(f"Уровень {item.level}: {h(item.referred.first_name or 'Без имени')} ({h(username)})")
    await callback.message.answer("\n".join(lines), reply_markup=agent_menu())
    await callback.answer()
