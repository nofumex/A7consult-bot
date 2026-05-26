from __future__ import annotations

from app.config import Settings
from app.models import User


def apply_env_roles(user: User, settings: Settings) -> None:
    platform = user.platform or "telegram"
    platform_user_id = str(user.platform_user_id or user.telegram_id or "")
    if platform == "max":
        user.is_admin = platform_user_id in settings.max_admin_ids
        user.is_manager = platform_user_id in settings.max_manager_ids or user.is_admin or user.is_manager
    else:
        user.is_admin = bool(user.telegram_id in settings.telegram_admin_ids or user.telegram_id == settings.dev_id)
        user.is_manager = bool(user.telegram_id in settings.telegram_manager_ids or user.is_admin or user.is_manager)
    if user.is_admin:
        user.role = "admin"
    elif user.is_manager:
        user.role = "manager"
    elif user.is_agent:
        user.role = "agent"
    elif user.is_client:
        user.role = "client"
    else:
        user.role = "user"


def is_admin(user: User | None) -> bool:
    return bool(user and user.is_admin)


def is_manager(user: User | None) -> bool:
    return bool(user and (user.is_manager or user.is_admin))


def human_role(user: User) -> str:
    if user.is_admin:
        return "Админ"
    if user.is_manager:
        return "Менеджер"
    if user.is_agent:
        return "Агент"
    if user.is_client:
        return "Клиент"
    return "Пользователь"
