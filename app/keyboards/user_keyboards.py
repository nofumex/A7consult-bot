from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup


def _button(text: str, callback_data: str | None = None, url: str | None = None, style: str | None = None) -> InlineKeyboardButton:
    kwargs = {"text": text}
    if callback_data:
        kwargs["callback_data"] = callback_data
    if url:
        kwargs["url"] = url
    if style:
        kwargs["style"] = style
    return InlineKeyboardButton(**kwargs)


def main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_button("Списать долги законно", "user:debts", style="success")],
            [_button("Хочу стать агентом", "agent:join", style="primary")],
        ]
    )


def client_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_button("Записаться на консультацию", "user:consultation", style="success")],
            [_button("Задать вопрос специалисту", "user:question", style="primary")],
            [_button("О компании", "user:about")],
            [
                _button("Профиль", "profile:show"),
                _button("Связь с менеджером", "chat:start_user"),
            ],
            [_button("Главное меню", "user:main")],
        ]
    )


def request_phone_reply() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="Отправить телефон", request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
        input_field_placeholder="Введите телефон или отправьте контакт",
    )


def profile_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_button("Реферальная ссылка", "agent:ref_url")],
            [_button("Мои рефералы", "agent:referrals")],
            [_button("Связь с менеджером", "chat:start_user")],
            [_button("+ Новый клиент", "agent:new_client", style="success")],
            [_button("Главное меню", "user:main")],
        ]
    )


def about_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_button("Записаться на консультацию", "user:consultation", style="success")],
            [_button("Задать вопрос специалисту", "user:question")],
            [_button("Главное меню", "user:main")],
        ]
    )


def chat_end_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[_button("Завершить чат", "chat:end", style="danger")]]
    )


def agent_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_button("Профиль", "profile:show", style="primary")],
            [_button("Правила программы", "agent:rules")],
            [_button("Реферальная ссылка", "agent:ref_url")],
            [_button("Заработанные бонусы", "agent:bonuses")],
            [_button("Связь с менеджером", "chat:start_agent")],
            [_button("+ Новый клиент", "agent:new_client", style="success")],
            [_button("Главное меню", "user:main")],
        ]
    )


def agent_rules_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_button("Реферальная ссылка", "agent:ref_url")],
            [_button("Заработанные бонусы", "agent:bonuses")],
            [_button("Связь с менеджером", "chat:start_agent")],
            [_button("+ Новый клиент", "agent:new_client", style="success")],
            [_button("Главное меню", "user:main")],
        ]
    )
