from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def _button(text: str, callback_data: str, style: str | None = None) -> InlineKeyboardButton:
    kwargs = {"text": text, "callback_data": callback_data}
    if style:
        kwargs["style"] = style
    return InlineKeyboardButton(**kwargs)


def manager_panel() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_button("Новые заявки", "manager:leads_new", style="primary")],
            [_button("Мои заявки в работе", "manager:leads_my")],
            [_button("Очередь без менеджера", "manager:leads_open")],
            [_button("Активный чат", "manager:active_chat")],
            [_button("Статистика менеджера", "manager:stats")],
            [_button("Завершить чат", "chat:end", style="danger")],
            [_button("Главное меню", "user:main")],
        ]
    )


def lead_actions(
    lead_id: int,
    include_bonus: bool = True,
    can_take: bool = True,
    is_closed: bool = False,
) -> InlineKeyboardMarkup:
    rows = []
    if can_take and not is_closed:
        rows.append([_button("Взять в работу", f"lead:take:{lead_id}", style="success")])
    if not is_closed:
        rows.append([_button("Подключиться в чат", f"chat:lead:{lead_id}", style="primary")])
        rows.append([_button("Договор заключён", f"lead:client:{lead_id}", style="success")])
    if include_bonus and not is_closed:
        rows.append([_button("Начислить бонус", f"bonus:create:{lead_id}")])
    rows.append([_button("Профиль пользователя", f"profile:view:{lead_id}")])
    if not is_closed:
        rows.append([_button("Закрыть без договора", f"lead:close:{lead_id}", style="danger")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def lead_list_keyboard(
    leads,
    section: str,
    page: int,
    has_prev: bool,
    has_next: bool,
) -> InlineKeyboardMarkup:
    rows = [[_button(f"Заявка #{lead.id}", f"manager:lead_view:{section}:{lead.id}")] for lead in leads]
    nav = []
    if has_prev:
        nav.append(_button("←", f"manager:{section}:{page - 1}"))
    if has_next:
        nav.append(_button("→", f"manager:{section}:{page + 1}"))
    if nav:
        rows.append(nav)
    rows.append([_button("Назад в панель", "manager:panel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def my_lead_actions(lead_id: int, include_bonus: bool = True, is_closed: bool = False) -> InlineKeyboardMarkup:
    return lead_actions(lead_id, include_bonus=include_bonus, can_take=False, is_closed=is_closed)


def chat_manager_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[_button("Завершить чат", "chat:end", style="danger")]]
    )
