from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from app.config import Settings
from app.database import SessionLocal
from app.services.developer import apply_developer_role_override
from app.services.users import get_or_create_user


class DbUserMiddleware(BaseMiddleware):
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        async with SessionLocal() as session:
            data["session"] = session
            from_user = None
            if isinstance(event, Message):
                from_user = event.from_user
            elif isinstance(event, CallbackQuery):
                from_user = event.from_user

            if from_user and not from_user.is_bot:
                user, _ = await get_or_create_user(session, from_user, self.settings)
                await apply_developer_role_override(session, user)
                data["current_user"] = user

            return await handler(event, data)
