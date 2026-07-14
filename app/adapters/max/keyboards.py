from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class MaxButton:
    text: str
    callback_data: str | None = None
    url: str | None = None
    request_contact: bool = False


MaxKeyboard = list[list[MaxButton]]


def _btn(text: str, callback_data: str | None = None, url: str | None = None, request_contact: bool = False) -> MaxButton:
    return MaxButton(text=text, callback_data=callback_data, url=url, request_contact=request_contact)


def to_attachments(keyboard: MaxKeyboard | None) -> list[dict] | None:
    if not keyboard:
        return None
    rows = []
    for row in keyboard:
        buttons = []
        for button in row:
            if button.url:
                buttons.append({"type": "link", "text": button.text, "url": button.url})
            elif button.request_contact:
                buttons.append({"type": "request_contact", "text": button.text})
            elif button.callback_data:
                buttons.append({"type": "callback", "text": button.text, "payload": button.callback_data})
            else:
                buttons.append({"type": "message", "text": button.text})
        rows.append(buttons)
    return [{"type": "inline_keyboard", "payload": {"buttons": rows}}]


def main_menu() -> MaxKeyboard:
    return [[_btn("Хочу стать агентом", "agent:join")]]


def yes_no_menu(yes_callback: str, no_callback: str) -> MaxKeyboard:
    return [[_btn("Да", yes_callback), _btn("Нет", no_callback)]]


def client_menu() -> MaxKeyboard:
    return [
        [_btn("Записаться на консультацию", "user:consultation")],
        [_btn("Задать вопрос специалисту", "user:question")],
        [_btn("О компании", "user:about")],
        [_btn("Профиль", "profile:show"), _btn("Связь с менеджером", "chat:start_user")],
        [_btn("Главное меню", "user:main")],
    ]


def consultation_phone_menu() -> MaxKeyboard:
    return [[_btn("Поделиться контактом", request_contact=True)]]


def agent_phone_menu() -> MaxKeyboard:
    return [[_btn("Поделиться контактом", request_contact=True)]]


def agent_menu() -> MaxKeyboard:
    return [
        [_btn("Профиль", "profile:show")],
        [_btn("Правила программы", "agent:rules")],
        [_btn("Реферальная ссылка", "agent:ref_url")],
        [_btn("Заработанные бонусы", "agent:bonuses")],
        [_btn("Связь с менеджером", "chat:start_agent")],
        [_btn("+ Новый клиент", "agent:new_client")],
        [_btn("Главное меню", "user:main")],
    ]


def profile_menu() -> MaxKeyboard:
    return [
        [_btn("Реферальная ссылка", "agent:ref_url")],
        [_btn("Мои рефералы", "agent:referrals")],
        [_btn("Связь с менеджером", "chat:start_user")],
        [_btn("+ Новый клиент", "agent:new_client")],
        [_btn("Главное меню", "user:main")],
    ]


def rules_menu() -> MaxKeyboard:
    return [
        [_btn("Реферальная ссылка", "agent:ref_url")],
        [_btn("Заработанные бонусы", "agent:bonuses")],
        [_btn("Связь с менеджером", "chat:start_agent")],
        [_btn("+ Новый клиент", "agent:new_client")],
        [_btn("Главное меню", "user:main")],
    ]


def lead_actions(
    lead_id: int,
    include_bonus: bool = True,
    can_take: bool = True,
    is_closed: bool = False,
) -> MaxKeyboard:
    rows: MaxKeyboard = []
    if can_take and not is_closed:
        rows.append([_btn("Взять в работу", f"lead:take:{lead_id}")])
    if not is_closed:
        rows.append([_btn("Подключиться в чат", f"chat:lead:{lead_id}")])
        rows.append([_btn("Договор заключён", f"lead:client:{lead_id}")])
    if include_bonus and not is_closed:
        rows.append([_btn("Начислить бонус", f"bonus:create:{lead_id}")])
    rows.append([_btn("Профиль пользователя", f"profile:view:{lead_id}")])
    if not is_closed:
        rows.append([_btn("Закрыть без договора", f"lead:close:{lead_id}")])
    return rows


def manager_panel() -> MaxKeyboard:
    return [
        [_btn("Новые заявки", "manager:leads_new")],
        [_btn("Мои заявки в работе", "manager:leads_my")],
        [_btn("Очередь без менеджера", "manager:leads_open")],
        [_btn("Активный чат", "manager:active_chat")],
        [_btn("Статистика менеджера", "manager:stats")],
        [_btn("Завершить чат", "chat:end")],
        [_btn("Главное меню", "user:main")],
    ]


def admin_panel(notifications_enabled: bool = True) -> MaxKeyboard:
    status = "Вкл" if notifications_enabled else "Выкл"
    return [
        [_btn("Статистика", "admin:stats")],
        [_btn("Заявки", "admin:leads")],
        [_btn("Агенты", "admin:agents")],
        [_btn("Бонусы", "admin:bonuses")],
        [_btn(f"Уведомления: {status}", "admin:toggle_notifications")],
        [_btn("Главное меню", "user:main")],
    ]


def sales_manager_actions(manager_id: int, enabled: bool) -> MaxKeyboard:
    toggle_text = "Отключить" if enabled else "Включить"
    return [[_btn(toggle_text, f"admin:sales_manager_toggle:{manager_id}")], [_btn("Назад", "admin:managers")]]


def chat_end_menu() -> MaxKeyboard:
    return [[_btn("Завершить чат", "chat:end")]]


def connect_chat_keyboard(session_id: int) -> MaxKeyboard:
    return [[_btn("Подключиться в чат", f"chat:session:{session_id}")]]
