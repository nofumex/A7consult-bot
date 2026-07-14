from __future__ import annotations

import logging

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.enums import BonusStatus, LeadStatus
from app.keyboards.admin_keyboards import admin_back, admin_panel, sales_manager_actions, user_admin_actions
from app.keyboards.manager_keyboards import lead_actions
from app.models import Bonus, SalesManager, User
from app.services.bonuses import create_bonus, set_bonus_status
from app.services.developer import (
    BONUS_NOTIFICATIONS,
    BROADCASTS,
    can_send_to_user,
    can_touch_lead,
    feature_enabled,
    filter_leads,
    is_developer,
    is_participant_user,
    participant_recipients,
    test_mode_enabled,
)
from app.services.leads import get_lead, list_leads
from app.services.referrals import referral_counts, referral_leads_count
from app.services.sales_managers import list_sales_managers, sales_manager_line, set_sales_manager_enabled, update_sales_manager_details
from app.services.stats import admin_stats
from app.services.users import list_agents, search_user, set_agent, set_client, set_regular
from app.states.admin_states import AdminSearchStates, BonusStates, BroadcastStates, SalesManagerStates
from app.utils.permissions import is_admin
from app.utils.text import bonus_status_label, full_name, h, lead_status_label, lead_summary, money, profile_text, username_text
from app.utils.validators import clean_text, parse_positive_int

router = Router(name="admin")
logger = logging.getLogger(__name__)


def _form_stat_line(label: str, item: dict[str, int | float]) -> str:
    return f"{label}: {item['count']} ({item['percent']}%)"


async def _ensure_admin_message(message: Message, current_user: User) -> bool:
    if not is_admin(current_user):
        await message.answer("Эта команда доступна только администраторам.")
        return False
    return True


async def _ensure_admin_callback(callback: CallbackQuery, current_user: User) -> bool:
    if not is_admin(current_user):
        await callback.answer("Недостаточно прав", show_alert=True)
        return False
    return True


@router.message(Command("admin"))
async def cmd_admin(message: Message, current_user: User, settings: Settings) -> None:
    if not await _ensure_admin_message(message, current_user):
        return
    await message.answer(
        "Админ-панель",
        reply_markup=admin_panel(current_user.admin_notifications_enabled, show_dev=is_developer(current_user, settings)),
    )


@router.callback_query(F.data == "admin:panel")
async def cb_admin_panel(callback: CallbackQuery, current_user: User, settings: Settings) -> None:
    if not await _ensure_admin_callback(callback, current_user):
        return
    await callback.message.answer(
        "Админ-панель",
        reply_markup=admin_panel(current_user.admin_notifications_enabled, show_dev=is_developer(current_user, settings)),
    )
    await callback.answer()


@router.callback_query(F.data == "admin:stats")
async def cb_admin_stats(callback: CallbackQuery, session: AsyncSession, current_user: User) -> None:
    if not await _ensure_admin_callback(callback, current_user):
        return
    data = await admin_stats(session)
    statuses = data["lead_statuses"]
    form_stats = data["agent_form_stats"]
    status_text = ", ".join(f"{lead_status_label(key)}: {value}" for key, value in statuses.items()) or "нет"
    await callback.message.answer(
        "Статистика\n\n"
        f"Пользователей всего: {data['users_total']}\n"
        f"Новых сегодня: {data['users_today']}\n"
        f"Новых за неделю: {data['users_week']}\n"
        f"Клиентов: {data['clients_total']}\n"
        f"Агентов: {data['agents_total']}\n"
        f"Менеджеров: {data['managers_total']}\n\n"
        f"Заявок всего: {data['leads_total']}\n"
        f"Заявок сегодня: {data['leads_today']}\n"
        f"Заявок за неделю: {data['leads_week']}\n"
        f"Заявок за месяц: {data['leads_month']}\n"
        f"По статусам: {status_text}\n\n"
        "<b>Анкета нового клиента</b>\n"
        f"Всего анкет: {form_stats['total']}\n"
        f"{_form_stat_line('Только имя', form_stats['only_name'])}\n"
        f"{_form_stat_line('Имя + телефон', form_stats['name_phone'])}\n"
        f"{_form_stat_line('Имя + телефон + связь', form_stats['name_phone_relation'])}\n"
        f"{_form_stat_line('Заполнено полностью', form_stats['completed'])}\n\n"
        f"Бонусов начислено: {data['bonus_total']} ₽\n"
        f"Бонусов выплачено всего: {data['bonus_paid_total']} ₽\n"
        f"Выплачено за месяц: {data['bonus_paid_month']} ₽\n"
        f"Выплачено за неделю: {data['bonus_paid_week']} ₽\n\n"
        f"Активных чатов: {data['chats_active']}\n"
        f"Закрытых чатов: {data['chats_closed']}",
        reply_markup=admin_back(),
    )
    await callback.answer()


@router.callback_query(F.data == "admin:leads")
async def cb_admin_leads(callback: CallbackQuery, session: AsyncSession, current_user: User) -> None:
    if not await _ensure_admin_callback(callback, current_user):
        return
    leads = await filter_leads(session, await list_leads(session, limit=10, platform="telegram"))
    if not leads:
        await callback.message.answer("Заявок пока нет.", reply_markup=admin_back())
    for lead in leads:
        is_closed = lead.status in {LeadStatus.CLOSED.value, LeadStatus.CANCELED.value}
        can_take = lead.status == LeadStatus.NEW.value and lead.assigned_manager_id is None
        await callback.message.answer(
            lead_summary(lead),
            reply_markup=lead_actions(
                lead.id,
                include_bonus=bool(lead.agent_id),
                can_take=can_take,
                is_closed=is_closed,
            ),
        )
    await callback.answer()


@router.callback_query(F.data == "admin:users")
async def cb_admin_users(callback: CallbackQuery, state: FSMContext, current_user: User) -> None:
    if not await _ensure_admin_callback(callback, current_user):
        return
    await state.set_state(AdminSearchStates.waiting_user_query)
    await callback.message.answer("Введите Telegram ID, username или внутренний ID пользователя.")
    await callback.answer()


@router.message(AdminSearchStates.waiting_user_query, ~F.text.startswith("/"))
async def process_user_search(message: Message, state: FSMContext, session: AsyncSession, current_user: User) -> None:
    if not await _ensure_admin_message(message, current_user):
        await state.clear()
        return
    user = await search_user(session, message.text or "")
    await state.clear()
    if not user:
        await message.answer("Пользователь не найден.", reply_markup=admin_back())
        return
    direct_refs, second_refs = await referral_counts(session, user.id)
    referral_leads = await referral_leads_count(session, user.id)
    from app.services.bonuses import bonus_totals

    bonuses = await bonus_totals(session, user.id)
    await message.answer(
        profile_text(user, direct_refs, second_refs, referral_leads, bonuses),
        reply_markup=user_admin_actions(user.id),
    )


@router.callback_query(F.data.startswith("admin:user_client:"))
async def cb_make_client(callback: CallbackQuery, session: AsyncSession, current_user: User) -> None:
    if not await _ensure_admin_callback(callback, current_user):
        return
    user = await session.get(User, int(callback.data.split(":")[-1]))
    if user:
        if await test_mode_enabled(session) and not await is_participant_user(session, user):
            await callback.answer("Тестовый режим: пользователь не входит в список участников", show_alert=True)
            return
        await set_client(session, user)
        await callback.message.answer(f"{full_name(user)} теперь клиент.")
    await callback.answer()


@router.callback_query(F.data.startswith("admin:user_agent:"))
async def cb_make_agent(callback: CallbackQuery, session: AsyncSession, current_user: User) -> None:
    if not await _ensure_admin_callback(callback, current_user):
        return
    user = await session.get(User, int(callback.data.split(":")[-1]))
    if user:
        if await test_mode_enabled(session) and not await is_participant_user(session, user):
            await callback.answer("Тестовый режим: пользователь не входит в список участников", show_alert=True)
            return
        await set_agent(session, user)
        await callback.message.answer(f"{full_name(user)} теперь агент.")
    await callback.answer()


@router.callback_query(F.data.startswith("admin:user_regular:"))
async def cb_make_regular(callback: CallbackQuery, session: AsyncSession, current_user: User) -> None:
    if not await _ensure_admin_callback(callback, current_user):
        return
    user = await session.get(User, int(callback.data.split(":")[-1]))
    if user:
        if await test_mode_enabled(session) and not await is_participant_user(session, user):
            await callback.answer("Тестовый режим: пользователь не входит в список участников", show_alert=True)
            return
        await set_regular(session, user)
        await callback.message.answer(f"{full_name(user)} переведён в обычные пользователи.")
    await callback.answer()


@router.callback_query(F.data == "admin:agents")
async def cb_agents(callback: CallbackQuery, session: AsyncSession, current_user: User) -> None:
    if not await _ensure_admin_callback(callback, current_user):
        return
    agents = await list_agents(session, limit=20, platform="telegram")
    if not agents:
        await callback.message.answer("Агентов пока нет.", reply_markup=admin_back())
    for agent in agents:
        direct_refs, _ = await referral_counts(session, agent.id)
        from app.services.bonuses import bonus_totals

        bonuses = await bonus_totals(session, agent.id)
        await callback.message.answer(
            f"Агент: {full_name(agent)}\n"
            f"Username: {username_text(agent)}\n"
            f"Telegram ID: {agent.telegram_id}\n"
            f"Рефералов: {direct_refs}\n"
            f"Бонусов начислено: {bonuses['total']} ₽\n"
            f"Выплачено: {bonuses['paid']} ₽",
            reply_markup=user_admin_actions(agent.id),
        )
    await callback.answer()


def _bonus_actions(bonus: Bonus) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Отметить выплаченным", callback_data=f"bonus:paid:{bonus.id}", style="success")],
            [InlineKeyboardButton(text="Отменить бонус", callback_data=f"bonus:cancel:{bonus.id}", style="danger")],
            [InlineKeyboardButton(text="Назад", callback_data="admin:panel")],
        ]
    )


@router.callback_query(F.data == "admin:bonuses")
async def cb_bonuses(callback: CallbackQuery, session: AsyncSession, current_user: User) -> None:
    if not await _ensure_admin_callback(callback, current_user):
        return
    result = await session.execute(
        select(Bonus)
        .join(User, Bonus.agent_id == User.id)
        .where(User.platform == "telegram")
        .order_by(Bonus.created_at.desc())
        .limit(10)
    )
    bonuses = list(result.scalars().all())
    if not bonuses:
        await callback.message.answer("Бонусов пока нет. Начислить бонус можно из карточки заявки или пользователя.", reply_markup=admin_back())
    for bonus in bonuses:
        await session.refresh(bonus, ["agent"])
        await callback.message.answer(
            f"Бонус #{bonus.id}\n"
            f"Агент: {full_name(bonus.agent)}\n"
            f"Сумма: {money(bonus.amount)} ₽\n"
            f"Статус: {bonus_status_label(bonus.status)}\n"
            f"<b>Комментарий:</b> {h(bonus.comment or 'без комментария')}",
            reply_markup=_bonus_actions(bonus),
        )
    await callback.answer()


@router.callback_query(F.data.startswith("bonus:create:"))
async def cb_bonus_from_lead(callback: CallbackQuery, state: FSMContext, session: AsyncSession, current_user: User) -> None:
    if not await _ensure_admin_callback(callback, current_user):
        return
    lead = await get_lead(session, int(callback.data.split(":")[-1]))
    if not lead or not lead.agent_id:
        await callback.answer("У заявки нет агента для начисления бонуса", show_alert=True)
        return
    if not await can_touch_lead(session, lead):
        await callback.answer("Тестовый режим: заявка не входит в список участников", show_alert=True)
        return
    await state.set_state(BonusStates.waiting_amount)
    await state.update_data(agent_id=lead.agent_id, lead_id=lead.id)
    await callback.message.answer("Введите сумму бонуса в рублях.")
    await callback.answer()


@router.callback_query(F.data.startswith("bonus:user:"))
async def cb_bonus_from_user(callback: CallbackQuery, state: FSMContext, session: AsyncSession, current_user: User) -> None:
    if not await _ensure_admin_callback(callback, current_user):
        return
    user = await session.get(User, int(callback.data.split(":")[-1]))
    if not user or not user.is_agent:
        await callback.answer("Бонус можно начислить только агенту", show_alert=True)
        return
    if await test_mode_enabled(session) and not await is_participant_user(session, user):
        await callback.answer("Тестовый режим: пользователь не входит в список участников", show_alert=True)
        return
    await state.set_state(BonusStates.waiting_amount)
    await state.update_data(agent_id=user.id, lead_id=None)
    await callback.message.answer("Введите сумму бонуса в рублях.")
    await callback.answer()


@router.message(BonusStates.waiting_amount, ~F.text.startswith("/"))
async def bonus_amount(message: Message, state: FSMContext, current_user: User) -> None:
    if not await _ensure_admin_message(message, current_user):
        await state.clear()
        return
    amount = parse_positive_int(message.text)
    if not amount:
        await message.answer("Введите положительную сумму, например 10000.")
        return
    await state.update_data(amount=amount)
    await state.set_state(BonusStates.waiting_comment)
    await message.answer("Введите комментарий к бонусу.")


@router.message(BonusStates.waiting_comment, ~F.text.startswith("/"))
async def bonus_comment(message: Message, state: FSMContext, session: AsyncSession, current_user: User) -> None:
    if not await _ensure_admin_message(message, current_user):
        await state.clear()
        return
    data = await state.get_data()
    comment = clean_text(message.text, 1000) or "без комментария"
    bonus = await create_bonus(
        session,
        agent_id=data["agent_id"],
        lead_id=data.get("lead_id"),
        amount=data["amount"],
        comment=comment,
        admin_id=current_user.id,
    )
    await session.refresh(bonus, ["agent"])
    if not await can_send_to_user(session, bonus.agent, BONUS_NOTIFICATIONS):
        logger.info("Skipped bonus notification for agent %s by developer settings", bonus.agent_id)
    elif bonus.agent.platform != "telegram" or not bonus.agent.telegram_id:
        logger.info("Skipped Telegram bonus notification for non-Telegram agent %s", bonus.agent_id)
    else:
        try:
            await message.bot.send_message(
                bonus.agent.telegram_id,
                "Вам начислен новый бонус.\n\n"
                f"Сумма: {money(bonus.amount)} ₽\n"
                f"<b>Комментарий:</b> {h(comment)}\n\n"
                "<b>Статус:</b> ожидает выплаты.",
            )
        except TelegramAPIError:
            logger.exception("Failed to notify agent %s about bonus %s", bonus.agent.telegram_id, bonus.id)
    await state.clear()
    await message.answer(f"Бонус #{bonus.id} создан. Статус: ожидает выплаты.", reply_markup=admin_back())


@router.callback_query(F.data.startswith("bonus:paid:"))
async def cb_bonus_paid(callback: CallbackQuery, session: AsyncSession, current_user: User) -> None:
    if not await _ensure_admin_callback(callback, current_user):
        return
    bonus = await session.get(Bonus, int(callback.data.split(":")[-1]))
    if bonus:
        await set_bonus_status(session, bonus, BonusStatus.PAID)
        await callback.message.answer(f"Бонус #{bonus.id} отмечен выплаченным.")
    await callback.answer()


@router.callback_query(F.data.startswith("bonus:cancel:"))
async def cb_bonus_cancel(callback: CallbackQuery, session: AsyncSession, current_user: User) -> None:
    if not await _ensure_admin_callback(callback, current_user):
        return
    bonus = await session.get(Bonus, int(callback.data.split(":")[-1]))
    if bonus:
        await set_bonus_status(session, bonus, BonusStatus.CANCELED)
        await callback.message.answer(f"Бонус #{bonus.id} отменён.")
    await callback.answer()


@router.callback_query(F.data == "admin:managers")
async def cb_managers(callback: CallbackQuery, session: AsyncSession, current_user: User) -> None:
    if not await _ensure_admin_callback(callback, current_user):
        return
    managers = await list_sales_managers(session)
    if not managers:
        await callback.message.answer("Менеджеры продаж не настроены.", reply_markup=admin_back())
        await callback.answer()
        return

    await callback.message.answer(
        "<b>Очередь менеджеров продаж</b>\n\n"
        "Сделки распределяются по очереди между включенными менеджерами. "
        "Отключенного менеджера бот пропускает.\n\n"
        + "\n".join(h(sales_manager_line(manager)) for manager in managers),
        reply_markup=admin_back(),
    )
    for manager in managers:
        await callback.message.answer(
            f"<b>{h(manager.name)}</b>\n"
            f"Телефон: <code>{h(manager.phone)}</code>\n"
            f"amoCRM user ID: <code>{manager.amo_user_id or 'не указан'}</code>\n"
            f"Статус: {'включен' if manager.enabled else 'отключен'}",
            reply_markup=sales_manager_actions(manager.id, manager.enabled),
        )
    await callback.answer()


@router.callback_query(F.data.startswith("admin:sales_manager_toggle:"))
async def cb_sales_manager_toggle(callback: CallbackQuery, session: AsyncSession, current_user: User) -> None:
    if not await _ensure_admin_callback(callback, current_user):
        return
    manager = await session.get(SalesManager, int(callback.data.split(":")[-1]))
    if not manager:
        await callback.answer("Менеджер не найден", show_alert=True)
        return
    await set_sales_manager_enabled(session, manager, not manager.enabled)
    await callback.message.answer(
        f"{h(manager.name)}: {'включен' if manager.enabled else 'отключен'}.",
        reply_markup=sales_manager_actions(manager.id, manager.enabled),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin:sales_manager_edit:"))
async def cb_sales_manager_edit(callback: CallbackQuery, state: FSMContext, session: AsyncSession, current_user: User) -> None:
    if not await _ensure_admin_callback(callback, current_user):
        return
    manager = await session.get(SalesManager, int(callback.data.split(":")[-1]))
    if not manager:
        await callback.answer("Менеджер не найден", show_alert=True)
        return
    await state.set_state(SalesManagerStates.waiting_details)
    await state.update_data(sales_manager_id=manager.id)
    await callback.message.answer(
        "Отправьте новые данные менеджера в формате:\n"
        "<code>Имя | телефон | amoCRM user ID</code>\n\n"
        f"Сейчас: <code>{h(manager.name)} | {h(manager.phone)} | {manager.amo_user_id or ''}</code>"
    )
    await callback.answer()


@router.message(SalesManagerStates.waiting_details, ~F.text.startswith("/"))
async def process_sales_manager_details(message: Message, state: FSMContext, session: AsyncSession, current_user: User) -> None:
    if not await _ensure_admin_message(message, current_user):
        await state.clear()
        return
    data = await state.get_data()
    manager = await session.get(SalesManager, data.get("sales_manager_id"))
    if not manager:
        await state.clear()
        await message.answer("Менеджер не найден.", reply_markup=admin_back())
        return

    parts = [part.strip() for part in (message.text or "").split("|")]
    if len(parts) != 3:
        await message.answer("Нужно 3 части: Имя | телефон | amoCRM user ID")
        return
    name, phone, amo_user_id_raw = parts
    try:
        amo_user_id = int(amo_user_id_raw) if amo_user_id_raw else None
        await update_sales_manager_details(session, manager, name=name, phone=phone, amo_user_id=amo_user_id)
    except ValueError as exc:
        await message.answer(str(exc))
        return

    await state.clear()
    await message.answer(
        "Данные менеджера обновлены:\n" + h(sales_manager_line(manager)),
        reply_markup=sales_manager_actions(manager.id, manager.enabled),
    )


@router.callback_query(F.data == "admin:toggle_notifications")
async def cb_toggle_notifications(callback: CallbackQuery, session: AsyncSession, current_user: User, settings: Settings) -> None:
    if not await _ensure_admin_callback(callback, current_user):
        return
    current_user.admin_notifications_enabled = not current_user.admin_notifications_enabled
    await session.commit()
    await callback.message.answer(
        f"Уведомления {'включены' if current_user.admin_notifications_enabled else 'выключены'}.",
        reply_markup=admin_panel(current_user.admin_notifications_enabled, show_dev=is_developer(current_user, settings)),
    )
    await callback.answer()


@router.callback_query(F.data == "admin:broadcast")
async def cb_broadcast(callback: CallbackQuery, state: FSMContext, session: AsyncSession, current_user: User) -> None:
    if not await _ensure_admin_callback(callback, current_user):
        return
    if not await feature_enabled(session, BROADCASTS):
        await callback.answer("Рассылки выключены в Developer panel", show_alert=True)
        return
    await state.set_state(BroadcastStates.waiting_text)
    await callback.message.answer(
        "<b>Рассылка</b>\n\n"
        "Отправьте одно сообщение, которое нужно разослать пользователям.\n\n"
        "Можно отправить текст с форматированием, фото с подписью, видео, документ или другой поддерживаемый Telegram-контент. "
        "Бот скопирует сообщение без потери оформления."
    )
    await callback.answer()


@router.message(BroadcastStates.waiting_text, ~F.text.startswith("/"))
async def process_broadcast(message: Message, state: FSMContext, session: AsyncSession, bot: Bot, current_user: User) -> None:
    if not await _ensure_admin_message(message, current_user):
        await state.clear()
        return
    if not await feature_enabled(session, BROADCASTS):
        await state.clear()
        await message.answer("Рассылка отменена: функция выключена в Developer panel.", reply_markup=admin_back())
        return
    if await test_mode_enabled(session):
        recipients = await participant_recipients(session, "telegram")
        if not recipients and current_user.telegram_id is not None:
            recipients = [current_user]
    else:
        result = await session.execute(select(User).where(User.platform == "telegram", User.telegram_id.is_not(None)))
        recipients = list(result.scalars().all())
    recipients = [user for user in recipients if await can_send_to_user(session, user, BROADCASTS)]
    telegram_ids = [user.telegram_id for user in recipients if user.telegram_id is not None]
    sent = 0
    failed = 0
    for telegram_id in telegram_ids:
        try:
            await bot.copy_message(
                chat_id=telegram_id,
                from_chat_id=message.chat.id,
                message_id=message.message_id,
            )
            sent += 1
        except TelegramAPIError:
            failed += 1
            logger.exception("Broadcast failed for %s", telegram_id)
    await state.clear()
    await message.answer(f"Рассылка завершена. Отправлено: {sent}, ошибок: {failed}.", reply_markup=admin_back())
