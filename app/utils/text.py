from __future__ import annotations

from html import escape

from app.config import Settings
from app.enums import BonusStatus, LeadStatus, LeadType
from app.models import Bonus, Lead, User
from app.utils.permissions import human_role


def h(value: object | None) -> str:
    return escape("" if value is None else str(value), quote=False)


def money(value: int) -> str:
    return f"{value:,}".replace(",", " ")


def full_name(user: User | None) -> str:
    if not user:
        return "Неизвестно"
    parts = [user.first_name, user.last_name]
    name = " ".join(part for part in parts if part)
    fallback = user.username or user.platform_user_id or user.telegram_id or "без имени"
    return h(name or fallback)


def username_text(user: User | None) -> str:
    if not user or not user.username:
        return "не указан"
    return f"@{h(user.username)}"


def platform_label(user: User | None) -> str:
    if not user:
        return "неизвестно"
    return "MAX" if user.platform == "max" else "Telegram"


def display_user_id(user: User | None) -> str:
    if not user:
        return "неизвестно"
    if user.platform == "max":
        return h(user.platform_user_id or user.telegram_id or "неизвестно")
    return h(user.telegram_id or user.platform_user_id or "неизвестно")


def lead_type_label(value: str | None) -> str:
    labels = {
        LeadType.CONSULTATION.value: "Консультация",
        LeadType.QUESTION.value: "Вопрос специалисту",
        LeadType.AGENT_CLIENT.value: "Клиент от агента",
    }
    return labels.get(value or "", h(value or "не указан"))


def lead_status_label(value: str | None) -> str:
    labels = {
        LeadStatus.NEW.value: "Новая",
        LeadStatus.IN_PROGRESS.value: "В работе",
        LeadStatus.CLOSED.value: "Закрыта",
        LeadStatus.CANCELED.value: "Отменена",
    }
    return labels.get(value or "", h(value or "не указан"))


def bonus_status_label(value: str | None) -> str:
    labels = {
        BonusStatus.PENDING.value: "Ожидает выплаты",
        BonusStatus.PAID.value: "Выплачен",
        BonusStatus.CANCELED.value: "Отменён",
    }
    return labels.get(value or "", h(value or "не указан"))


def welcome_text() -> str:
    return (
        "<b>Юридическая компания «А7 Консалт»</b>\n"
        "<i>Банкротство физических лиц и помощь с долговой нагрузкой</i>\n\n"
        "<b>Партнёрская программа</b>\n"
        "Передавайте контакты людей, которым нужна помощь с долгами, и получайте вознаграждение после заключения договора.\n\n"
        "<i>Конфиденциально. По делу. Без лишнего давления.</i>"
    )


def client_info_text() -> str:
    return (
        "<b>Помощь с долгами в правовом поле</b>\n\n"
        "«А7 Консалт» сопровождает клиентов по вопросам банкротства физических лиц, кредитов, займов, "
        "исполнительных производств и долговой нагрузки.\n\n"
        "<b>На первичной консультации специалист:</b>\n"
        "• уточнит вводные данные;\n"
        "• объяснит, подходит ли процедура;\n"
        "• обозначит возможные сроки и порядок действий;\n"
        "• честно скажет, если банкротство не лучший вариант.\n\n"
        "<b>Первичная консультация бесплатная.</b>\n"
        "Можно записаться сразу или задать вопрос одним сообщением."
    )


def consultation_prompt() -> str:
    return (
        "<b>Запись на бесплатную консультацию</b>\n\n"
        "Оставьте номер телефона. Менеджер «А7 Консалт» свяжется с вами, уточнит ситуацию и передаст обращение специалисту.\n\n"
        "Можно отправить контакт Telegram или ввести номер вручную.\n"
        "<i>Пример: +7 999 000 00 00</i>\n\n"
        "<i>Если передумали, отправьте /cancel.</i>"
    )


def company_text() -> str:
    return (
        "<b>О компании «А7 Консалт»</b>\n\n"
        "Юридическая компания работает с долговыми вопросами, банкротством физических лиц и судебной защитой клиентов. "
        "Подход строится на спокойной коммуникации, проверяемых действиях и понятном сопровождении на каждом этапе.\n\n"
        "<b>Что важно для нас:</b>\n"
        "• <b>доказательная практика</b> - результат подтверждается документами и судебными актами;\n"
        "• <b>конфиденциальность</b> - обращение обрабатывается аккуратно;\n"
        "• <b>реалистичная оценка</b> - без обещаний, которые нельзя проверить;\n"
        "• <b>понятный маршрут</b> - клиент знает, что происходит сейчас и что будет дальше.\n\n"
        "Головной офис компании находится в Красноярске. Практика по делам представлена в разных регионах РФ.\n\n"
        "<i>Надёжно. Профессионально. Конфиденциально.</i>"
    )


def agent_welcome_text(settings: Settings) -> str:
    return (
        "<b>Партнёрская программа «А7 Консалт»</b>\n\n"
        "Вы можете рекомендовать компанию людям с долговой нагрузкой, которым может подойти процедура банкротства "
        "физических лиц, и получать вознаграждение за успешные рекомендации.\n\n"
        "<b>Как это работает:</b>\n"
        "• вы передаёте контакт человека или отправляете ему реферальную ссылку;\n"
        "• команда «А7 Консалт» связывается с ним, проводит консультацию и оценивает ситуацию;\n"
        "• после заключения договора администратор начисляет вам бонус.\n\n"
        f"<b>Вознаграждение:</b> от {money(settings.default_bonus_per_client)} ₽ за клиента.\n"
        f"<b>Второй уровень:</b> дополнительный бонус {money(settings.second_level_bonus)} ₽, если клиента привёл ваш агент.\n\n"
        "Вам не нужно вести юридическую часть, консультировать клиента или сопровождать процедуру. "
        "Ваша задача - рекомендация или передача контакта. Остальное берёт на себя компания.\n\n"
        "<i>Простой формат сотрудничества с прозрачной историей заявок и начислений в боте.</i>"
    )


def referral_rules_text(settings: Settings) -> str:
    return (
        "<b>Правила партнёрской программы</b>\n\n"
        "<b>Кто такой агент</b>\n"
        "Агент рекомендует «А7 Консалт» людям, которым актуальна помощь с кредитами, займами, просрочками, "
        "исполнительными производствами или общей долговой нагрузкой.\n\n"
        "<b>Схема работы</b>\n"
        "1. Вы передаёте контакт или отправляете реферальную ссылку.\n"
        "2. Мы связываемся с человеком и проводим консультацию.\n"
        "3. Если клиент заключает договор, администратор вручную начисляет бонус.\n\n"
        "<b>Первый уровень</b>\n"
        f"За клиента, которого передали вы, может быть начислено от {money(settings.default_bonus_per_client)} ₽.\n\n"
        "<b>Второй уровень</b>\n"
        f"Если приглашённый вами агент приводит клиента, вам может быть начислен дополнительный бонус "
        f"{money(settings.second_level_bonus)} ₽.\n\n"
        "<b>Какие обращения подходят</b>\n"
        "Кредиты, микрозаймы, долги перед банками, просрочки, исполнительные производства и ситуации, "
        "где человеку нужна юридическая оценка.\n\n"
        "<b>Почему это законно</b>\n"
        "Банкротство физических лиц предусмотрено законодательством РФ. На консультации специалист оценивает, "
        "применима ли процедура именно к конкретной ситуации.\n\n"
        "<b>Как начать</b>\n"
        "Получите реферальную ссылку или добавьте клиента через кнопку <b>+ Новый клиент</b>."
    )


def profile_text(
    user: User,
    direct_refs: int,
    second_refs: int,
    referral_leads: int,
    bonuses: dict[str, int],
    include_service_fields: bool = True,
) -> str:
    created = user.created_at.strftime("%d.%m.%Y %H:%M") if user.created_at else "неизвестно"
    service_fields = (
        f"<b>Username:</b> {username_text(user)}\n"
        f"<b>Платформа:</b> {platform_label(user)}\n"
        f"<b>ID:</b> <code>{display_user_id(user)}</code>\n"
        if include_service_fields
        else ""
    )
    return (
        "<b>Профиль</b>\n\n"
        f"<b>Имя:</b> {full_name(user)}\n"
        f"{service_fields}"
        f"<b>Статус:</b> {h(human_role(user))}\n"
        f"<b>Регистрация:</b> {h(created)}\n\n"
        "<b>Партнёрские показатели</b>\n"
        f"• Прямые рефералы: {direct_refs}\n"
        f"• Второй уровень: {second_refs}\n"
        f"• Заявки от рефералов: {referral_leads}\n\n"
        "<b>Бонусы</b>\n"
        f"• Начислено: {money(bonuses['total'])} ₽\n"
        f"• Выплачено: {money(bonuses['paid'])} ₽\n"
        f"• Ожидает выплаты: {money(bonuses['pending'])} ₽"
    )


def lead_summary(lead: Lead) -> str:
    user = lead.user
    created = lead.created_at.strftime("%d.%m.%Y %H:%M") if lead.created_at else "неизвестно"
    title = lead_type_label(lead.type)
    details = [
        f"<b>{title} #{lead.id}</b>",
        f"<b>Статус:</b> {lead_status_label(lead.status)}",
        f"<b>Дата:</b> {h(created)}",
    ]
    if lead.assigned_manager:
        details.append(f"<b>Ответственный:</b> {full_name(lead.assigned_manager)}")
    details.extend(
        [
            "",
            f"<b>Контакт:</b> {h(lead.client_name) if lead.client_name else full_name(user)}",
        ]
    )
    if user:
        details.extend(
            [
                f"<b>Username:</b> {username_text(user)}",
                f"<b>{platform_label(user)} ID:</b> <code>{display_user_id(user)}</code>",
            ]
        )
    if lead.phone:
        details.append(f"<b>Телефон:</b> <code>{h(lead.phone)}</code>")
    if lead.city:
        details.append(f"<b>Город:</b> {h(lead.city)}")
    if lead.debt_amount:
        details.append(f"<b>Сумма долга:</b> {h(lead.debt_amount)}")
    if lead.relation_to_agent:
        details.append(f"<b>Связь с агентом:</b> {h(lead.relation_to_agent)}")
    if lead.agent_payout_phone:
        details.append(f"<b>Телефон агента для выплаты:</b> <code>{h(lead.agent_payout_phone)}</code>")
    if lead.question_text:
        details.extend(["", f"<b>Вопрос:</b>\n{h(lead.question_text)}"])
    if lead.comment:
        details.extend(["", f"<b>Комментарий:</b>\n{h(lead.comment)}"])
    if lead.agent:
        details.extend(
            [
                "",
                f"<b>Агент:</b> {full_name(lead.agent)}",
                f"<b>Username агента:</b> {username_text(lead.agent)}",
                f"<b>Агент ID:</b> <code>{display_user_id(lead.agent)}</code>",
            ]
        )
        if lead.agent.phone:
            details.append(f"<b>Телефон агента:</b> <code>{h(lead.agent.phone)}</code>")
    return "\n".join(details)


def new_lead_notification(lead: Lead, title: str = "Новая заявка") -> str:
    return f"<b>{h(title)}</b>\n\n{lead_summary(lead)}"


def bonus_line(bonus: Bonus) -> str:
    created = bonus.created_at.strftime("%d.%m.%Y") if bonus.created_at else "без даты"
    comment = bonus.comment or "без комментария"
    return f"• {h(created)}: <b>{money(bonus.amount)} ₽</b> - {bonus_status_label(bonus.status)}\n  <i>{h(comment)}</i>"
