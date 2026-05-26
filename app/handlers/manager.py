from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import LeadStatus
from app.keyboards.manager_keyboards import lead_actions, lead_list_keyboard, manager_panel, my_lead_actions
from app.models import User
from app.services.bonuses import bonus_totals
from app.services.chat_sessions import get_manager_active_session
from app.services.developer import can_touch_lead, filter_leads
from app.services.leads import close_lead, get_lead, list_leads, list_open_leads, take_lead
from app.services.referrals import referral_counts, referral_leads_count
from app.services.stats import manager_stats
from app.services.users import set_client
from app.utils.permissions import is_manager
from app.utils.text import full_name, lead_summary, profile_text

router = Router(name="manager")
LEADS_PAGE_SIZE = 5


async def _ensure_manager_message(message: Message, current_user: User) -> bool:
    if not is_manager(current_user):
        await message.answer("Эта команда доступна только менеджерам и администраторам.")
        return False
    return True


async def _ensure_manager_callback(callback: CallbackQuery, current_user: User) -> bool:
    if not is_manager(current_user):
        await callback.answer("Недостаточно прав", show_alert=True)
        return False
    return True


@router.message(Command("manager"))
async def cmd_manager(message: Message, current_user: User) -> None:
    if not await _ensure_manager_message(message, current_user):
        return
    await message.answer(
        "<b>Панель менеджера</b>\n\n"
        "Здесь можно забрать новые заявки, открыть свои обращения в работе и продолжить активный чат.",
        reply_markup=manager_panel(),
    )


@router.callback_query(F.data == "manager:panel")
async def cb_manager_panel(callback: CallbackQuery, current_user: User) -> None:
    if not await _ensure_manager_callback(callback, current_user):
        return
    await callback.message.answer(
        "<b>Панель менеджера</b>\n\n"
        "Выберите раздел: новые заявки, ваши заявки в работе или активный чат.",
        reply_markup=manager_panel(),
    )
    await callback.answer()


def _page_from_callback(callback: CallbackQuery) -> int:
    parts = (callback.data or "").split(":")
    try:
        return max(0, int(parts[-1])) if len(parts) > 2 else 0
    except ValueError:
        return 0


async def _send_leads(callback: CallbackQuery, leads: list, empty_text: str, section: str, title: str) -> None:
    if not leads:
        await callback.message.answer(empty_text, reply_markup=manager_panel())
        return
    page = _page_from_callback(callback)
    total_pages = max(1, (len(leads) + LEADS_PAGE_SIZE - 1) // LEADS_PAGE_SIZE)
    page = min(page, total_pages - 1)
    start = page * LEADS_PAGE_SIZE
    chunk = leads[start : start + LEADS_PAGE_SIZE]
    await callback.message.answer(
        f"<b>{title}</b>\n\nВыберите заявку. Страница {page + 1} из {total_pages}.",
        reply_markup=lead_list_keyboard(
            chunk,
            section=section,
            page=page,
            has_prev=page > 0,
            has_next=start + LEADS_PAGE_SIZE < len(leads),
        ),
    )


@router.callback_query(F.data.startswith("manager:leads_new"))
async def cb_new_leads(callback: CallbackQuery, session: AsyncSession, current_user: User) -> None:
    if not await _ensure_manager_callback(callback, current_user):
        return
    leads = await filter_leads(session, await list_leads(session, status=LeadStatus.NEW.value, limit=50, platform="telegram"))
    await _send_leads(callback, leads, "Новых заявок нет.", section="leads_new", title="Новые заявки")
    await callback.answer()


@router.callback_query(F.data.startswith("manager:leads_my"))
async def cb_my_leads(callback: CallbackQuery, session: AsyncSession, current_user: User) -> None:
    if not await _ensure_manager_callback(callback, current_user):
        return
    leads = await filter_leads(session, await list_leads(session, manager_id=current_user.id, limit=50, platform="telegram"))
    await _send_leads(callback, leads, "У вас пока нет заявок.", section="leads_my", title="Мои заявки в работе")
    await callback.answer()


@router.callback_query(F.data.startswith("manager:leads_open"))
async def cb_open_leads(callback: CallbackQuery, session: AsyncSession, current_user: User) -> None:
    if not await _ensure_manager_callback(callback, current_user):
        return
    leads = await filter_leads(session, await list_open_leads(session, limit=50, platform="telegram"))
    await _send_leads(callback, leads, "Открытых заявок нет.", section="leads_open", title="Очередь без менеджера")
    await callback.answer()


@router.callback_query(F.data.startswith("manager:lead_view:"))
async def cb_view_lead_from_list(callback: CallbackQuery, session: AsyncSession, current_user: User) -> None:
    if not await _ensure_manager_callback(callback, current_user):
        return
    _, _, section, lead_id = callback.data.split(":", 3)
    lead = await get_lead(session, int(lead_id))
    if not lead or lead.platform != current_user.platform:
        await callback.answer("Заявка не найдена", show_alert=True)
        return
    if not await can_touch_lead(session, lead):
        await callback.answer("Тестовый режим: заявка не входит в список участников", show_alert=True)
        return
    await session.refresh(lead, ["user", "agent", "assigned_manager"])
    is_closed = lead.status in {LeadStatus.CLOSED.value, LeadStatus.CANCELED.value}
    can_take = section != "leads_my" and lead.assigned_manager_id is None
    markup_factory = lead_actions if can_take else my_lead_actions
    await callback.message.answer(
        lead_summary(lead),
        reply_markup=markup_factory(lead.id, include_bonus=bool(lead.agent_id), is_closed=is_closed),
    )
    await callback.answer()


@router.callback_query(F.data == "manager:active_chat")
async def cb_active_chat(callback: CallbackQuery, session: AsyncSession, current_user: User) -> None:
    if not await _ensure_manager_callback(callback, current_user):
        return
    chat = await get_manager_active_session(session, current_user.id)
    if not chat:
        await callback.message.answer("Активного чата сейчас нет.")
    else:
        await session.refresh(chat, ["user"])
        await callback.message.answer(f"Активный чат: {full_name(chat.user)}. Напишите сообщение сюда или завершите чат.")
    await callback.answer()


@router.callback_query(F.data == "manager:stats")
async def cb_manager_stats(callback: CallbackQuery, session: AsyncSession, current_user: User) -> None:
    if not await _ensure_manager_callback(callback, current_user):
        return
    stats = await manager_stats(session, current_user.id)
    await callback.message.answer(
        "<b>Статистика менеджера</b>\n\n"
        f"В работе: <b>{stats['my_in_progress']}</b>\n"
        f"Закрыто: <b>{stats['my_closed']}</b>",
        reply_markup=manager_panel(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("lead:take:"))
async def cb_take_lead(callback: CallbackQuery, session: AsyncSession, current_user: User) -> None:
    if not await _ensure_manager_callback(callback, current_user):
        return
    lead = await get_lead(session, int(callback.data.split(":")[-1]))
    if not lead or lead.platform != current_user.platform:
        await callback.answer("Заявка не найдена", show_alert=True)
        return
    if not await can_touch_lead(session, lead):
        await callback.answer("Тестовый режим: заявка не входит в список участников", show_alert=True)
        return
    lead, ok = await take_lead(session, lead, current_user)
    if not ok:
        await callback.answer("Уже в работе у другого менеджера", show_alert=True)
        return
    await callback.message.answer(
        f"<b>Заявка #{lead.id} закреплена за вами.</b>\n\n"
        "Следующий шаг - подключиться в чат или связаться с клиентом по телефону.",
        reply_markup=my_lead_actions(lead.id, include_bonus=bool(lead.agent_id)),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("lead:close:"))
async def cb_close_lead(callback: CallbackQuery, session: AsyncSession, current_user: User) -> None:
    if not await _ensure_manager_callback(callback, current_user):
        return
    lead = await get_lead(session, int(callback.data.split(":")[-1]))
    if not lead or lead.platform != current_user.platform:
        await callback.answer("Заявка не найдена", show_alert=True)
        return
    if not await can_touch_lead(session, lead):
        await callback.answer("Тестовый режим: заявка не входит в список участников", show_alert=True)
        return
    if lead.status in {LeadStatus.CLOSED.value, LeadStatus.CANCELED.value}:
        await callback.answer("Заявка уже закрыта", show_alert=True)
        return
    await close_lead(session, lead)
    await callback.message.answer(f"Заявка #{lead.id} закрыта.")
    await callback.answer()


@router.callback_query(F.data.startswith("lead:client:"))
async def cb_mark_client(callback: CallbackQuery, session: AsyncSession, current_user: User) -> None:
    if not await _ensure_manager_callback(callback, current_user):
        return
    lead = await get_lead(session, int(callback.data.split(":")[-1]))
    if not lead or lead.platform != current_user.platform:
        await callback.answer("Заявка не найдена", show_alert=True)
        return
    if not await can_touch_lead(session, lead):
        await callback.answer("Тестовый режим: заявка не входит в список участников", show_alert=True)
        return
    if lead.status in {LeadStatus.CLOSED.value, LeadStatus.CANCELED.value}:
        await callback.answer("Заявка уже закрыта", show_alert=True)
        return
    await session.refresh(lead, ["user", "agent"])
    target = lead.user
    if target:
        await set_client(session, target)
    await close_lead(session, lead)
    if not target:
        await callback.message.answer(
            f"Договор по заявке #{lead.id} отмечен как заключён.\n"
            "Заявка закрыта и больше не отображается в активных списках."
        )
        await callback.answer()
        return
    if target.platform != current_user.platform:
        await callback.answer("Пользователь не найден", show_alert=True)
        return
    await callback.message.answer(
        f"Договор по заявке #{lead.id} отмечен как заключён.\n"
        f"{full_name(target)} теперь отображается как клиент."
    )
    await callback.answer()


@router.callback_query(F.data.startswith("profile:view:"))
async def cb_view_profile(callback: CallbackQuery, session: AsyncSession, current_user: User) -> None:
    if not await _ensure_manager_callback(callback, current_user):
        return
    lead = await get_lead(session, int(callback.data.split(":")[-1]))
    if not lead or lead.platform != current_user.platform:
        await callback.answer("Заявка не найдена", show_alert=True)
        return
    if not await can_touch_lead(session, lead):
        await callback.answer("Тестовый режим: заявка не входит в список участников", show_alert=True)
        return
    await session.refresh(lead, ["user", "agent"])
    target = lead.user or lead.agent
    if not target:
        await callback.answer("Пользователь не найден", show_alert=True)
        return
    direct_refs, second_refs = await referral_counts(session, target.id)
    referral_leads = await referral_leads_count(session, target.id)
    bonuses = await bonus_totals(session, target.id)
    await callback.message.answer(profile_text(target, direct_refs, second_refs, referral_leads, bonuses))
    await callback.answer()
