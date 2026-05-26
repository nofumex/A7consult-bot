from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.services.developer import (
    ALL_DELIVERIES,
    BONUS_NOTIFICATIONS,
    BROADCASTS,
    CHAT_BRIDGE,
    FEATURE_LABELS,
    STAFF_NOTIFICATIONS,
    TEST_MODE,
    USER_MUTE_LABELS,
)


def _button(text: str, callback_data: str, style: str | None = None) -> InlineKeyboardButton:
    kwargs = {"text": text, "callback_data": callback_data}
    if style:
        kwargs["style"] = style
    return InlineKeyboardButton(**kwargs)


def admin_panel(notifications_enabled: bool = True, show_dev: bool = False) -> InlineKeyboardMarkup:
    status = "Вкл" if notifications_enabled else "Выкл"
    rows = [
        [_button("Статистика", "admin:stats", style="primary")],
        [_button("Заявки", "admin:leads"), _button("Пользователи", "admin:users")],
        [_button("Агенты", "admin:agents"), _button("Бонусы", "admin:bonuses")],
        [_button("Менеджеры", "admin:managers"), _button("Рассылка", "admin:broadcast")],
        [_button(f"Уведомления: {status}", "admin:toggle_notifications")],
        [_button("Главное меню", "user:main")],
    ]
    if show_dev:
        rows.insert(-1, [_button("Developer panel", "dev:panel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_back() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[_button("Назад в админ-панель", "admin:panel")]]
    )


def user_admin_actions(user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_button("Сделать клиентом", f"admin:user_client:{user_id}")],
            [_button("Сделать агентом", f"admin:user_agent:{user_id}")],
            [_button("Сделать пользователем", f"admin:user_regular:{user_id}")],
            [_button("Начислить бонус", f"bonus:user:{user_id}", style="success")],
            [_button("Открыть чат", f"chat:user:{user_id}", style="primary")],
            [_button("Назад к поиску", "admin:users")],
        ]
    )


def developer_panel(status: dict[str, bool | int]) -> InlineKeyboardMarkup:
    def toggle_label(key: str) -> str:
        value = "Вкл" if status.get(key) else "Выкл"
        return f"{FEATURE_LABELS[key]}: {value}"

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_button(toggle_label(TEST_MODE), f"dev:toggle:{TEST_MODE}", style="primary")],
            [_button(toggle_label(STAFF_NOTIFICATIONS), f"dev:toggle:{STAFF_NOTIFICATIONS}")],
            [_button(toggle_label(BROADCASTS), f"dev:toggle:{BROADCASTS}")],
            [_button(toggle_label(BONUS_NOTIFICATIONS), f"dev:toggle:{BONUS_NOTIFICATIONS}")],
            [_button(toggle_label(CHAT_BRIDGE), f"dev:toggle:{CHAT_BRIDGE}")],
            [_button("Участники теста", "dev:participants"), _button("Добавить участника", "dev:add")],
            [_button("Отключения по ID", "dev:mutes")],
            [_button("Админ-панель", "admin:panel")],
        ]
    )


def developer_back() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[_button("Назад в Developer panel", "dev:panel")]])


def developer_role_choice(user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_button("Как пользователь", f"dev:add_role:{user_id}:user")],
            [_button("Как менеджер", f"dev:add_role:{user_id}:manager")],
            [_button("Как админ", f"dev:add_role:{user_id}:admin")],
            [_button("Назад", "dev:panel")],
        ]
    )


def developer_participant_actions(participant_id: int, enabled: bool) -> InlineKeyboardMarkup:
    toggle_text = "Выключить" if enabled else "Включить"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_button(toggle_text, f"dev:participant_toggle:{participant_id}")],
            [_button("Удалить", f"dev:participant_remove:{participant_id}", style="danger")],
            [_button("Назад", "dev:participants")],
        ]
    )


def developer_mute_actions(user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_button(USER_MUTE_LABELS[ALL_DELIVERIES], f"dev:mute_toggle:{user_id}:{ALL_DELIVERIES}")],
            [_button(USER_MUTE_LABELS[STAFF_NOTIFICATIONS], f"dev:mute_toggle:{user_id}:{STAFF_NOTIFICATIONS}")],
            [_button(USER_MUTE_LABELS[BROADCASTS], f"dev:mute_toggle:{user_id}:{BROADCASTS}")],
            [_button(USER_MUTE_LABELS[BONUS_NOTIFICATIONS], f"dev:mute_toggle:{user_id}:{BONUS_NOTIFICATIONS}")],
            [_button("Выбрать другого", "dev:mutes")],
            [_button("Назад", "dev:panel")],
        ]
    )
