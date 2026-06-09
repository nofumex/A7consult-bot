from __future__ import annotations

import logging
import re

from sqlalchemy import func, select

from app.adapters.max import keyboards
from app.adapters.max.client import MaxBotClient
from app.adapters.max.mapper import IncomingEvent
from app.adapters.max.states import clear_state, get_state, set_state
from app.config import Settings
from app.database import SessionLocal
from app.enums import BonusStatus, LeadStatus
from app.models import Bonus, ChatSession, Lead, User
from app.services.bonuses import bonus_totals, create_bonus, recent_bonuses, set_bonus_status
from app.services.chat_sessions import (
    close_session,
    connect_manager,
    get_manager_active_session,
    get_session,
    get_user_active_session,
    open_session,
    save_message,
)
from app.services.developer import (
    BONUS_NOTIFICATIONS,
    CHAT_BRIDGE,
    apply_developer_role_override,
    can_send_to_user,
    can_touch_lead,
    filter_leads,
    is_participant_user,
    test_mode_enabled,
)
from app.services.leads import (
    close_lead,
    create_agent_client_lead_draft,
    create_consultation_lead,
    create_question_lead,
    get_lead,
    list_leads_by_platform,
    take_lead,
    update_agent_client_lead,
)
from app.services.referrals import (
    attach_referrer_by_internal_id,
    referral_counts,
    referral_leads_count,
    recent_referrals,
)
from app.services.sheets import enqueue_lead_sync
from app.services.stats import admin_stats, manager_stats
from app.services.users import get_or_create_platform_user, list_staff_by_platform, set_agent, set_client
from app.utils.permissions import is_admin, is_manager
from app.utils.text import (
    agent_welcome_text,
    bonus_line,
    bonus_status_label,
    client_info_text,
    company_text,
    consultation_prompt,
    full_name,
    h,
    lead_summary,
    money,
    new_lead_notification,
    profile_text,
    referral_rules_text,
    username_text,
    welcome_text,
)
from app.utils.validators import clean_text, normalize_phone, parse_positive_int

logger = logging.getLogger(__name__)

ESCAPE_TEXTS = {
    keyboards.MAIN_MENU_TEXT.lower(),
    "\u043c\u0435\u043d\u044e",
    "\u0432 \u043c\u0435\u043d\u044e",
    "\u043d\u0430\u0437\u0430\u0434",
    "\u043e\u0442\u043c\u0435\u043d\u0430",
    "/menu",
}

TEXT_TO_CALLBACK = {
    "Списать долги законно": "user:debts",
    "Хочу стать агентом": "agent:join",
    "Партнёрская программа": "agent:join",
    "Записаться на консультацию": "user:consultation",
    "Задать вопрос специалисту": "user:question",
    "О компании": "user:about",
    "Профиль": "profile:show",
    "Правила программы": "agent:rules",
    "Реферальная ссылка": "agent:ref_url",
    "Мои рефералы": "agent:referrals",
    "Заработанные бонусы": "agent:bonuses",
    "Связь с менеджером": "chat:start_agent",
    "Связь с менеджером": "chat:start_user",
    "+ Новый клиент": "agent:new_client",
    "Главное меню": "user:main",
    "Новые заявки": "manager:leads_new",
    "Мои заявки в работе": "manager:leads_my",
    "Очередь без менеджера": "manager:leads_open",
    "Активный чат": "manager:active_chat",
    "Завершить чат": "chat:end",
    "Статистика менеджера": "manager:stats",
    "Статистика": "admin:stats",
    "Заявки": "admin:leads",
    "Агенты": "admin:agents",
    "Бонусы": "admin:bonuses",
}


async def send(client: MaxBotClient, event: IncomingEvent, text: str, keyboard=None) -> None:
    await client.send_message(chat_id=event.chat_id, text=text, keyboard=keyboard or keyboards.main_menu_only())


def _form_stat_line(label: str, item: dict[str, int | float]) -> str:
    return f"{label}: {item['count']} ({item['percent']}%)"


async def notify_staff(client: MaxBotClient, text: str, keyboard=None) -> None:
    async with SessionLocal() as session:
        for user in await list_staff_by_platform(session, "max"):
            if not user.platform_user_id:
                continue
            await client.safe_send(user_id=user.platform_user_id, text=text, keyboard=keyboard)


def _extract_ref(text: str | None) -> int | None:
    if not text:
        return None
    match = re.search(r"ref_(\d+)", text)
    return int(match.group(1)) if match else None


async def _current_user(event: IncomingEvent, settings: Settings):
    async with SessionLocal() as session:
        user, _ = await get_or_create_platform_user(
            session,
            "max",
            event.platform_user_id,
            settings,
            username=event.username,
            first_name=event.first_name,
            last_name=event.last_name,
        )
        await apply_developer_role_override(session, user)
        return user


async def handle_update(client: MaxBotClient, event: IncomingEvent, settings: Settings) -> None:
    async with SessionLocal() as session:
        user, _ = await get_or_create_platform_user(
            session,
            "max",
            event.platform_user_id,
            settings,
            username=event.username,
            first_name=event.first_name,
            last_name=event.last_name,
        )
        await apply_developer_role_override(session, user)

        raw_text = (event.text or "").strip()
        normalized_text = raw_text.lower()

        data = event.callback_data or TEXT_TO_CALLBACK.get(raw_text)
        if not data and raw_text.startswith("Уведомления:"):
            data = "admin:toggle_notifications"
        if raw_text.startswith("/"):
            data = None

        if event.callback_id:
            await client.answer_callback(event.callback_id)

        if raw_text.startswith("/start"):
            referrer_id = _extract_ref(raw_text)
            if referrer_id:
                await attach_referrer_by_internal_id(session, user, referrer_id)
            await clear_state(session, event.platform_user_id)
            await send(client, event, welcome_text(), keyboards.main_menu())
            return

        if data == keyboards.MAIN_MENU_CALLBACK or normalized_text in ESCAPE_TEXTS:
            await clear_state(session, event.platform_user_id)
            await send(client, event, welcome_text(), keyboards.main_menu())
            return

        if raw_text == "/cancel":
            await clear_state(session, event.platform_user_id)
            await send(client, event, "Текущее действие отменено.", keyboards.main_menu())
            return

        if event.text == "/help":
            await send(
                client,
                event,
                "<b>Помощь по боту «А7 Консалт»</b>\n\n"
                "<b>Для клиента</b>\n"
                "/start - главное меню\n"
                "/consultation - бесплатная консультация\n"
                "/tutor - связаться с менеджером\n"
                "/profile - открыть профиль\n\n"
                "<b>Для агента</b>\n"
                "/ref_url - реферальная ссылка\n"
                "/new_client - передать нового клиента\n\n"
                "<b>Для команды</b>\n"
                "/manager - панель менеджера\n"
                "/admin - админ-панель\n"
                "/endchat - завершить активный чат\n"
                "/cancel - отменить текущий сценарий",
            )
            return

        if event.text == "/endchat" or data == "chat:end":
            await _end_chat(client, event, session, user)
            return

        if event.text == "/profile" or data == "profile:show":
            await _send_profile(client, event, session, user)
            return

        if event.text == "/consultation" or data == "user:consultation":
            await set_state(session, event.platform_user_id, "consultation_phone")
            await send(client, event, consultation_prompt(), keyboards.consultation_phone_menu())
            return

        if event.text == "/ref_url" or data == "agent:ref_url":
            await _send_ref_url(client, event, settings, user)
            return

        if event.text == "/tutor" or data in {"chat:start_user", "chat:start_agent"}:
            await _start_chat(client, event, session, user)
            return

        if event.text == "/new_client" or data == "agent:new_client":
            if await test_mode_enabled(session) and not await is_participant_user(session, user):
                await send(client, event, "Сейчас включен тестовый режим. Передача клиентов доступна только участникам теста.")
                return
            if not user.is_agent:
                await set_agent(session, user)
            if not user.phone:
                await set_state(session, event.platform_user_id, "new_client_agent_phone")
                await send(
                    client,
                    event,
                    "<b>Новый клиент</b>\n\nСначала поделитесь вашим номером телефона для связи и выплаты бонуса.",
                    keyboards.agent_phone_menu(),
                )
                return
            await set_state(session, event.platform_user_id, "new_client_name")
            await send(client, event, "<b>Новый клиент</b>\n\nВведите имя клиента.")
            return

        if event.text == "/manager" or data == "manager:panel":
            if not is_manager(user):
                await send(client, event, "Эта команда доступна только менеджерам и администраторам.")
                return
            await send(client, event, "<b>Панель менеджера</b>", keyboards.manager_panel())
            return

        if event.text == "/admin" or data == "admin:panel":
            if not is_admin(user):
                await send(client, event, "Эта команда доступна только администраторам.")
                return
            await send(client, event, "<b>Админ-панель</b>", keyboards.admin_panel(user.admin_notifications_enabled))
            return

        state, state_data = await get_state(session, event.platform_user_id)
        if state:
            handled = await _handle_state(client, event, session, user, state, state_data)
            if handled:
                return

        if data:
            await _handle_callback(client, event, session, settings, user, data)
            return

        if await _relay_chat_message(client, event, session, user):
            return

        if event.text:
            await send(client, event, welcome_text(), keyboards.main_menu())


async def _handle_callback(client: MaxBotClient, event: IncomingEvent, session, settings: Settings, user: User, data: str) -> None:
    if data == "user:main":
        await clear_state(session, event.platform_user_id)
        await send(client, event, welcome_text(), keyboards.main_menu())
    elif data == "user:debts":
        await send(client, event, client_info_text(), keyboards.client_menu())
    elif data == "user:question":
        await set_state(session, event.platform_user_id, "question_text")
        await send(client, event, "<b>Вопрос специалисту</b>\n\nНапишите ваш вопрос одним сообщением.")
    elif data == "user:about":
        if settings.company_video_url:
            await send(client, event, f"Видео о компании: {h(settings.company_video_url)}")
        await send(client, event, company_text(), keyboards.client_menu())
    elif data == "agent:join":
        if not user.is_agent:
            await set_agent(session, user)
        await send(client, event, agent_welcome_text(settings), keyboards.agent_menu())
    elif data == "agent:rules":
        await send(client, event, referral_rules_text(settings), keyboards.rules_menu())
    elif data == "agent:bonuses":
        totals = await bonus_totals(session, user.id)
        bonuses = await recent_bonuses(session, user.id)
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
        await send(client, event, "\n".join(lines), keyboards.agent_menu())
    elif data == "agent:referrals":
        if not user.is_agent:
            await send(
                client,
                event,
                "Список рефералов доступен агентам. Нажмите «Хочу стать агентом» в Главном меню, чтобы подключиться.",
                keyboards.main_menu(),
            )
            return
        referrals = await recent_referrals(session, user.id, limit=10)
        if not referrals:
            await send(
                client,
                event,
                "Рефералов пока нет. Получите ссылку и отправьте её тем, кому может быть полезна консультация.",
                keyboards.agent_menu(),
            )
            return
        lines = ["<b>Последние рефералы</b>", ""]
        for item in referrals:
            await session.refresh(item, ["referred"])
            lines.append(f"Уровень {item.level}: {full_name(item.referred)} ({username_text(item.referred)})")
        await send(client, event, "\n".join(lines), keyboards.agent_menu())
    elif data.startswith("manager:"):
        await _handle_manager_callback(client, event, session, user, data)
    elif data.startswith("admin:"):
        await _handle_admin_callback(client, event, session, user, data)
    elif data.startswith("lead:") or data.startswith("profile:view:") or data.startswith("bonus:"):
        await _handle_lead_bonus_callback(client, event, session, user, data)
    elif data.startswith("chat:"):
        await _handle_chat_callback(client, event, session, user, data)


async def _handle_state(client: MaxBotClient, event: IncomingEvent, session, user: User, state: str, data: dict) -> bool:
    text = clean_text(event.text, 3000)
    if state == "consultation_phone":
        phone = normalize_phone(event.contact_phone or event.text)
        if not phone:
            await send(client, event, "Похоже, номер введён некорректно. Введите телефон ещё раз.")
            return True
        if await test_mode_enabled(session) and not await is_participant_user(session, user):
            await clear_state(session, event.platform_user_id)
            await send(client, event, "Сейчас включен тестовый режим. Заявки принимаются только от участников теста.")
            return True
        lead = await create_consultation_lead(session, user, phone)
        await clear_state(session, event.platform_user_id)
        await send(
            client,
            event,
            "<b>Спасибо. Заявка принята.</b>\n\n"
            "Менеджер «А7 Консалт» скоро свяжется с вами. Пока заявка передана в работу, можно посмотреть информацию о компании или задать дополнительный вопрос.",
            keyboards.client_menu(),
        )
        await notify_staff(client, new_lead_notification(lead, "Новая заявка на консультацию"), keyboards.lead_actions(lead.id, include_bonus=False))
        return True
    if state == "question_text":
        if not text:
            await send(client, event, "Пожалуйста, отправьте вопрос текстом.")
            return True
        if await test_mode_enabled(session) and not await is_participant_user(session, user):
            await clear_state(session, event.platform_user_id)
            await send(client, event, "Сейчас включен тестовый режим. Вопросы принимаются только от участников теста.")
            return True
        lead = await create_question_lead(session, user, text)
        await clear_state(session, event.platform_user_id)
        await send(client, event, "<b>Спасибо.</b> Вопрос передан менеджеру.", keyboards.client_menu())
        await notify_staff(client, new_lead_notification(lead, "Новый вопрос от пользователя"), keyboards.lead_actions(lead.id, include_bonus=False))
        return True
    if state.startswith("new_client_"):
        return await _handle_new_client_state(client, event, session, user, state, data)
    if state == "bonus_amount":
        amount = parse_positive_int(event.text)
        if not amount:
            await send(client, event, "Введите положительную сумму, например 10000.")
            return True
        data["amount"] = amount
        await set_state(session, event.platform_user_id, "bonus_comment", data)
        await send(client, event, "Введите комментарий к бонусу.")
        return True
    if state == "bonus_comment":
        comment = clean_text(event.text, 1000) or "без комментария"
        bonus = await create_bonus(session, data["agent_id"], data["amount"], comment, user.id, data.get("lead_id"))
        await session.refresh(bonus, ["agent"])
        if await can_send_to_user(session, bonus.agent, BONUS_NOTIFICATIONS) and bonus.agent.platform == "max" and bonus.agent.platform_user_id:
            await client.safe_send(
                user_id=bonus.agent.platform_user_id,
                text=f"<b>Вам начислен новый бонус.</b>\n\n<b>Сумма:</b> {money(bonus.amount)} ₽\n<b>Комментарий:</b> {h(comment)}\n\n<b>Статус:</b> ожидает выплаты.",
            )
        await clear_state(session, event.platform_user_id)
        await send(client, event, f"Бонус #{bonus.id} создан. Статус: ожидает выплаты.")
        return True
    return False


async def _handle_new_client_state(client: MaxBotClient, event: IncomingEvent, session, user: User, state: str, data: dict) -> bool:
    if state == "new_client_agent_phone":
        phone = normalize_phone(event.contact_phone or event.text)
        if not phone:
            await send(
                client,
                event,
                "Телефон выглядит некорректно. Поделитесь контактом кнопкой или введите номер вручную.",
                keyboards.agent_phone_menu(),
            )
            return True
        user.phone = phone
        await session.commit()
        await session.refresh(user)
        result = await session.execute(select(Lead.id).where(Lead.platform == "max", Lead.agent_id == user.id))
        for lead_id in result.scalars().all():
            enqueue_lead_sync(int(lead_id))
        await set_state(session, event.platform_user_id, "new_client_name")
        await send(client, event, "<b>Новый клиент</b>\n\nВведите имя клиента.")
    elif state == "new_client_name":
        name = clean_text(event.text, 255)
        if not name:
            await send(client, event, "Имя не должно быть пустым. Введите имя клиента.")
            return True
        lead = await create_agent_client_lead_draft(session, user, name)
        await set_state(session, event.platform_user_id, "new_client_phone", {"lead_id": lead.id, "client_name": name})
        await send(client, event, "Введите телефон клиента.")
    elif state == "new_client_phone":
        phone = normalize_phone(event.text)
        if not phone:
            await send(client, event, "Телефон выглядит некорректно. Введите номер ещё раз.")
            return True
        data["phone"] = phone
        lead = await get_lead(session, data["lead_id"])
        if lead:
            await update_agent_client_lead(session, lead, phone=phone)
        await set_state(session, event.platform_user_id, "new_client_relation", data)
        await send(client, event, "Кем клиент вам приходится? Может ли он на вас сослаться?")
    elif state == "new_client_relation":
        relation = clean_text(event.text, 255) or "не указано"
        data["relation_to_agent"] = relation
        lead = await get_lead(session, data["lead_id"])
        if lead:
            await update_agent_client_lead(session, lead, relation_to_agent=relation)
        await set_state(session, event.platform_user_id, "new_client_source_permission", data)
        await send(client, event, "Можно ли сообщить, что номер получили от вас?")
    elif state == "new_client_source_permission":
        permission = clean_text(event.text, 255) or "не указано"
        data["source_permission"] = permission
        lead = await get_lead(session, data["lead_id"])
        if lead:
            await update_agent_client_lead(
                session,
                lead,
                comment=f"Можно ли сообщить, что номер получили от вас? {permission}",
            )
        await set_state(session, event.platform_user_id, "new_client_payout_phone", data)
        await send(client, event, "По какому номеру с вами связываться для выплаты бонуса?")
    elif state == "new_client_payout_phone":
        payout_phone = normalize_phone(event.text)
        if not payout_phone:
            await send(client, event, "Телефон выглядит некорректно. Введите номер ещё раз.")
            return True
        data["agent_payout_phone"] = payout_phone
        lead = await get_lead(session, data["lead_id"])
        if lead:
            await update_agent_client_lead(session, lead, agent_payout_phone=payout_phone)
        await clear_state(session, event.platform_user_id)
        await send(client, event, "<b>Спасибо.</b> Данные клиента переданы менеджерам «А7 Консалт».", keyboards.agent_menu())
    return True


async def _send_profile(client: MaxBotClient, event: IncomingEvent, session, user: User, include_service_fields: bool = False) -> None:
    direct_refs, second_refs = await referral_counts(session, user.id)
    referral_leads = await referral_leads_count(session, user.id)
    bonuses = await bonus_totals(session, user.id)
    text = profile_text(user, direct_refs, second_refs, referral_leads, bonuses, include_service_fields=include_service_fields)
    await send(client, event, text, keyboards.profile_menu())


async def _send_ref_url(client: MaxBotClient, event: IncomingEvent, settings: Settings, user: User) -> None:
    if not user.is_agent:
        await send(
            client,
            event,
            "<b>Реферальная ссылка доступна агентам.</b>\n\n"
            "Нажмите «Хочу стать агентом» в Главном меню, чтобы подключиться.",
            keyboards.main_menu(),
        )
        return
    code = f"ref_{user.id}"
    if settings.max_bot_link:
        await send(client, event, f"<b>Ваша реферальная ссылка (Нажмите, чтобы скопировать) </b>\n\n{h(settings.max_bot_link)}?start={code}\n\n<code>{code}</code>")
    else:
        await send(client, event, f"<b>Ваш реферальный код:</b> <code>{code}</code>")


async def _handle_manager_callback(client: MaxBotClient, event: IncomingEvent, session, user: User, data: str) -> None:
    if not is_manager(user):
        await send(client, event, "Недостаточно прав.")
        return
    if data == "manager:leads_new":
        leads = await filter_leads(session, await list_leads_by_platform(session, "max", status=LeadStatus.NEW.value, only_unassigned=True, limit=10))
        await _send_leads(client, event, leads, "Новых заявок нет.", can_take=True)
    elif data == "manager:leads_my":
        leads = await filter_leads(session, await list_leads_by_platform(session, "max", manager_id=user.id, limit=10))
        await _send_leads(client, event, leads, "У вас пока нет заявок.", can_take=False)
    elif data == "manager:leads_open":
        leads = await filter_leads(session, await list_leads_by_platform(session, "max", status=LeadStatus.NEW.value, only_unassigned=True, limit=10))
        await _send_leads(client, event, leads, "Открытых заявок нет.", can_take=True)
    elif data == "manager:active_chat":
        chat = await get_manager_active_session(session, user.id)
        if not chat:
            await send(client, event, "Активного чата сейчас нет.")
        else:
            await session.refresh(chat, ["user"])
            await send(client, event, f"Активный чат: {full_name(chat.user)}. Напишите сообщение сюда или завершите чат.")
    elif data == "manager:stats":
        stats = await manager_stats(session, user.id)
        await send(client, event, f"<b>Статистика менеджера</b>\n\nВ работе: {stats['my_in_progress']}\nЗакрыто: {stats['my_closed']}", keyboards.manager_panel())


async def _send_leads(client: MaxBotClient, event: IncomingEvent, leads: list[Lead], empty_text: str, can_take: bool) -> None:
    if not leads:
        await send(client, event, empty_text)
        return
    for lead in leads:
        is_closed = lead.status in {LeadStatus.CLOSED.value, LeadStatus.CANCELED.value}
        await send(
            client,
            event,
            lead_summary(lead),
            keyboards.lead_actions(
                lead.id,
                include_bonus=bool(lead.agent_id),
                can_take=can_take,
                is_closed=is_closed,
            ),
        )


async def _handle_lead_bonus_callback(client: MaxBotClient, event: IncomingEvent, session, user: User, data: str) -> None:
    if not is_manager(user):
        await send(client, event, "Недостаточно прав.")
        return
    if data.startswith("lead:take:"):
        lead = await get_lead(session, int(data.split(":")[-1]))
        if not lead or lead.platform != "max":
            await send(client, event, "Заявка не найдена.")
            return
        if not await can_touch_lead(session, lead):
            await send(client, event, "Тестовый режим: заявка не входит в список участников.")
            return
        lead, ok = await take_lead(session, lead, user)
        if not ok:
            await send(client, event, "Уже в работе у другого менеджера.")
            return
        await send(
            client,
            event,
            f"<b>Заявка #{lead.id} закреплена за вами.</b>\n\n"
            "Следующий шаг - подключиться в чат или связаться с клиентом по телефону.",
            keyboards.lead_actions(lead.id, include_bonus=bool(lead.agent_id), can_take=False),
        )
    elif data.startswith("lead:close:"):
        lead = await get_lead(session, int(data.split(":")[-1]))
        if lead and lead.platform == "max":
            if not await can_touch_lead(session, lead):
                await send(client, event, "Тестовый режим: заявка не входит в список участников.")
                return
            if lead.status in {LeadStatus.CLOSED.value, LeadStatus.CANCELED.value}:
                await send(client, event, "Заявка уже закрыта.")
                return
            await close_lead(session, lead)
            await send(client, event, f"Заявка #{lead.id} закрыта.")
    elif data.startswith("lead:client:"):
        lead = await get_lead(session, int(data.split(":")[-1]))
        if not lead or lead.platform != "max":
            await send(client, event, "Заявка не найдена.")
            return
        if not await can_touch_lead(session, lead):
            await send(client, event, "Тестовый режим: заявка не входит в список участников.")
            return
        if lead.status in {LeadStatus.CLOSED.value, LeadStatus.CANCELED.value}:
            await send(client, event, "Заявка уже закрыта.")
            return
        await session.refresh(lead, ["user", "agent"])
        target = lead.user
        if target:
            await set_client(session, target)
            await close_lead(session, lead)
            await send(
                client,
                event,
                f"Договор по заявке #{lead.id} отмечен как заключён.\n"
                f"{full_name(target)} теперь отображается как клиент.",
            )
        else:
            await close_lead(session, lead)
            await send(
                client,
                event,
                f"Договор по заявке #{lead.id} отмечен как заключён.\n"
                "Заявка закрыта и больше не отображается в активных списках.",
            )
    elif data.startswith("profile:view:"):
        lead = await get_lead(session, int(data.split(":")[-1]))
        if not lead or lead.platform != "max":
            await send(client, event, "Заявка не найдена.")
            return
        if not await can_touch_lead(session, lead):
            await send(client, event, "Тестовый режим: заявка не входит в список участников.")
            return
        await session.refresh(lead, ["user", "agent"])
        target = lead.user or lead.agent
        if target:
            await _send_profile(client, event, session, target, include_service_fields=True)
    elif data.startswith("bonus:create:"):
        if not is_admin(user):
            await send(client, event, "Бонусы может начислять только администратор.")
            return
        lead = await get_lead(session, int(data.split(":")[-1]))
        if not lead or not lead.agent_id or lead.platform != "max":
            await send(client, event, "У заявки нет агента для начисления бонуса.")
            return
        if not await can_touch_lead(session, lead):
            await send(client, event, "Тестовый режим: заявка не входит в список участников.")
            return
        await set_state(session, event.platform_user_id, "bonus_amount", {"lead_id": lead.id, "agent_id": lead.agent_id})
        await send(client, event, "Введите сумму бонуса в рублях.")
    elif data.startswith("bonus:paid:") or data.startswith("bonus:cancel:"):
        if not is_admin(user):
            await send(client, event, "Недостаточно прав.")
            return
        bonus = await session.get(Bonus, int(data.split(":")[-1]))
        if bonus:
            status = BonusStatus.PAID if data.startswith("bonus:paid:") else BonusStatus.CANCELED
            await set_bonus_status(session, bonus, status)
            await send(client, event, f"Бонус #{bonus.id} обновлён: {status.value}.")


async def _handle_chat_callback(client: MaxBotClient, event: IncomingEvent, session, user: User, data: str) -> None:
    if data.startswith("chat:session:"):
        if not is_manager(user):
            await send(client, event, "Недостаточно прав.")
            return
        chat = await get_session(session, int(data.split(":")[-1]))
        if not chat:
            await send(client, event, "Чат не найден.")
            return
        await _connect_chat(client, event, session, user, chat)
    elif data.startswith("chat:lead:"):
        if not is_manager(user):
            await send(client, event, "Недостаточно прав.")
            return
        lead = await get_lead(session, int(data.split(":")[-1]))
        if not lead or lead.platform != "max":
            await send(client, event, "Заявка не найдена.")
            return
        if not await can_touch_lead(session, lead):
            await send(client, event, "Тестовый режим: заявка не входит в список участников.")
            return
        await session.refresh(lead, ["user", "agent"])
        target = lead.user or lead.agent
        if target:
            chat = await open_session(session, target)
            await _connect_chat(client, event, session, user, chat)


async def _start_chat(client: MaxBotClient, event: IncomingEvent, session, user: User) -> None:
    if await test_mode_enabled(session) and not await is_participant_user(session, user):
        await send(client, event, "Сейчас включен тестовый режим. Чат доступен только участникам теста.")
        return
    existing = await get_user_active_session(session, user.id)
    chat = existing or await open_session(session, user)
    if existing:
        await send(
            client,
            event,
            "У вас уже открыт чат с менеджером. Напишите сообщение здесь, и оно попадёт в текущий диалог.",
            keyboards.chat_end_menu(),
        )
        return
    await send(client, event, "Напишите сообщение, и свободный менеджер подключится к диалогу.", keyboards.chat_end_menu())
    await notify_staff(
        client,
        f"<b>Пользователь хочет связаться с менеджером</b>\n\n<b>Имя:</b> {full_name(user)}\n<b>MAX ID:</b> <code>{h(user.platform_user_id)}</code>",
        keyboards.connect_chat_keyboard(chat.id),
    )


async def _connect_chat(client: MaxBotClient, event: IncomingEvent, session, manager: User, chat: ChatSession) -> None:
    await session.refresh(chat, ["user"])
    if chat.user.platform != manager.platform:
        await send(client, event, "Этот чат относится к другой платформе.")
        return
    if not await can_send_to_user(session, chat.user, CHAT_BRIDGE):
        await send(client, event, "Тестовый режим: чат не входит в список участников.")
        return
    chat, connected, manager_busy = await connect_manager(session, chat, manager)
    if manager_busy:
        await send(client, event, "У вас уже есть активный чат.")
        return
    if not connected:
        await send(client, event, "Уже подключился другой менеджер.")
        return
    await session.refresh(chat, ["user"])
    await send(client, event, f"Вы подключились к чату с пользователем {full_name(chat.user)}.", keyboards.chat_end_menu())
    if chat.user.platform_user_id and await can_send_to_user(session, chat.user, CHAT_BRIDGE):
        await client.safe_send(user_id=chat.user.platform_user_id, text="Менеджер подключился к диалогу.", keyboard=keyboards.chat_end_menu())


async def _end_chat(client: MaxBotClient, event: IncomingEvent, session, user: User) -> None:
    chat = await get_manager_active_session(session, user.id) if is_manager(user) else None
    chat = chat or await get_user_active_session(session, user.id)
    if not chat:
        await send(client, event, "Активного чата сейчас нет.")
        return
    await session.refresh(chat, ["user", "manager"])
    await close_session(session, chat)
    await send(client, event, "Чат завершён.")
    for participant in (chat.user, chat.manager):
        if (
            participant
            and participant.id != user.id
            and participant.platform == "max"
            and participant.platform_user_id
            and await can_send_to_user(session, participant, CHAT_BRIDGE)
        ):
            await client.safe_send(user_id=participant.platform_user_id, text="Чат завершён.")


async def _relay_chat_message(client: MaxBotClient, event: IncomingEvent, session, user: User) -> bool:
    if not event.text or event.text.startswith("/"):
        return False
    if is_manager(user):
        chat = await get_manager_active_session(session, user.id)
        if chat:
            await session.refresh(chat, ["user"])
            await save_message(session, chat, user, event.text, "manager")
            if chat.user.platform == "max" and chat.user.platform_user_id and await can_send_to_user(session, chat.user, CHAT_BRIDGE):
                await client.safe_send(user_id=chat.user.platform_user_id, text=f"<b>Менеджер:</b>\n{h(event.text)}", keyboard=keyboards.chat_end_menu())
            else:
                await send(client, event, "Тестовый режим: сообщение не отправлено пользователю вне списка участников.")
            return True
    chat = await get_user_active_session(session, user.id)
    if not chat:
        return False
    await session.refresh(chat, ["manager"])
    await save_message(session, chat, user, event.text, "user")
    if chat.manager and chat.manager.platform == "max" and chat.manager.platform_user_id and await can_send_to_user(session, chat.manager, CHAT_BRIDGE):
        await client.safe_send(user_id=chat.manager.platform_user_id, text=f"{full_name(user)} ({username_text(user)}):\n{h(event.text)}", keyboard=keyboards.chat_end_menu())
    else:
        await send(client, event, "Сообщение сохранено. Менеджер подключится, как только освободится.", keyboards.chat_end_menu())
    return True


async def _handle_admin_callback(client: MaxBotClient, event: IncomingEvent, session, user: User, data: str) -> None:
    if not is_admin(user):
        await send(client, event, "Недостаточно прав.")
        return
    if data == "admin:stats":
        stats = await admin_stats(session)
        form_stats = stats["agent_form_stats"]
        telegram_users = int(await session.scalar(select(func.count(User.id)).where(User.platform == "telegram")) or 0)
        max_users = int(await session.scalar(select(func.count(User.id)).where(User.platform == "max")) or 0)
        await send(
            client,
            event,
            "<b>Статистика</b>\n\n"
            f"Пользователей всего: {stats['users_total']}\n"
            f"Telegram пользователей: {telegram_users}\n"
            f"MAX пользователей: {max_users}\n"
            f"Клиентов: {stats['clients_total']}\n"
            f"Агентов: {stats['agents_total']}\n"
            f"Заявок всего: {stats['leads_total']}\n"
            f"Заявок сегодня: {stats['leads_today']}\n"
            f"Заявок за неделю: {stats['leads_week']}\n"
            "\n<b>Анкета нового клиента</b>\n"
            f"Всего анкет: {form_stats['total']}\n"
            f"{_form_stat_line('Только имя', form_stats['only_name'])}\n"
            f"{_form_stat_line('Имя + телефон', form_stats['name_phone'])}\n"
            f"{_form_stat_line('Имя + телефон + связь', form_stats['name_phone_relation'])}\n"
            f"{_form_stat_line('Заполнено полностью', form_stats['completed'])}\n\n"
            f"Бонусов начислено: {stats['bonus_total']} ₽\n"
            f"Бонусов выплачено: {stats['bonus_paid_total']} ₽\n"
            f"Активных чатов: {stats['chats_active']}",
            keyboards.admin_panel(user.admin_notifications_enabled),
        )
    elif data == "admin:leads":
        leads = await filter_leads(session, await list_leads_by_platform(session, "max", limit=10))
        await _send_leads(client, event, leads, "Заявок пока нет.", can_take=True)
    elif data == "admin:agents":
        result = await session.execute(select(User).where(User.platform == "max", User.is_agent.is_(True)).order_by(User.created_at.desc()).limit(20))
        agents = list(result.scalars().all())
        if not agents:
            await send(client, event, "Агентов пока нет.", keyboards.admin_panel(user.admin_notifications_enabled))
        for agent in agents:
            totals = await bonus_totals(session, agent.id)
            direct, _ = await referral_counts(session, agent.id)
            await send(
                client,
                event,
                f"<b>Агент:</b> {full_name(agent)}\n"
                f"<b>MAX ID:</b> <code>{h(agent.platform_user_id)}</code>\n"
                f"<b>Рефералов:</b> {direct}\n"
                f"<b>Начислено:</b> {money(totals['total'])} ₽\n"
                f"<b>Выплачено:</b> {money(totals['paid'])} ₽",
            )
    elif data == "admin:bonuses":
        result = await session.execute(select(Bonus).join(User, Bonus.agent_id == User.id).where(User.platform == "max").order_by(Bonus.created_at.desc()).limit(10))
        bonuses = list(result.scalars().all())
        if not bonuses:
            await send(client, event, "Бонусов пока нет.")
        for bonus in bonuses:
            await session.refresh(bonus, ["agent"])
            await send(
                client,
                event,
                f"<b>Бонус #{bonus.id}</b>\n"
                f"Агент: {full_name(bonus.agent)}\n"
                f"Сумма: {money(bonus.amount)} ₽\n"
                f"Статус: {bonus_status_label(bonus.status)}\n"
                f"Комментарий: {h(bonus.comment or 'без комментария')}",
                [
                    [keyboards.MaxButton("Отметить выплаченным", f"bonus:paid:{bonus.id}")],
                    [keyboards.MaxButton("Отменить бонус", f"bonus:cancel:{bonus.id}")],
                ],
            )
    elif data == "admin:toggle_notifications":
        user.admin_notifications_enabled = not user.admin_notifications_enabled
        await session.commit()
        await send(client, event, f"Уведомления {'включены' if user.admin_notifications_enabled else 'выключены'}.", keyboards.admin_panel(user.admin_notifications_enabled))
