from __future__ import annotations

import hashlib

from aiogram.types import User as TgUser
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.enums import UserRole
from app.models import User
from app.services.amocrm import enqueue_agent_amocrm_sync
from app.utils.permissions import apply_env_roles


async def get_by_telegram_id(session: AsyncSession, telegram_id: int) -> User | None:
    result = await session.execute(select(User).where(User.telegram_id == telegram_id))
    return result.scalar_one_or_none()


async def get_by_platform_id(session: AsyncSession, platform: str, platform_user_id: str | int) -> User | None:
    result = await session.execute(
        select(User).where(User.platform == platform, User.platform_user_id == str(platform_user_id))
    )
    return result.scalar_one_or_none()


async def get_by_id(session: AsyncSession, user_id: int) -> User | None:
    return await session.get(User, user_id)


async def get_or_create_user(session: AsyncSession, tg_user: TgUser, settings: Settings) -> tuple[User, bool]:
    user = await get_by_telegram_id(session, tg_user.id)
    created = False
    if user is None:
        user = User(
            telegram_id=tg_user.id,
            platform="telegram",
            platform_user_id=str(tg_user.id),
            username=tg_user.username,
            first_name=tg_user.first_name,
            last_name=tg_user.last_name,
        )
        session.add(user)
        created = True
    else:
        user.username = tg_user.username
        user.first_name = tg_user.first_name
        user.last_name = tg_user.last_name
        user.platform = user.platform or "telegram"
        user.platform_user_id = user.platform_user_id or str(tg_user.id)

    apply_env_roles(user, settings)
    await session.commit()
    await session.refresh(user)
    return user, created


def legacy_id_for_platform(platform: str, platform_user_id: str | int) -> int:
    if platform == "telegram":
        return int(platform_user_id)
    value = str(platform_user_id)
    if value.isdigit():
        return -int(value)
    # Keep the value inside signed 63-bit range for SQLite BigInteger compatibility.
    digest = hashlib.sha256(f"{platform}:{value}".encode("utf-8")).hexdigest()
    return -(int(digest[:15], 16) % 9_000_000_000_000_000_000)


async def get_or_create_platform_user(
    session: AsyncSession,
    platform: str,
    platform_user_id: str | int,
    settings: Settings,
    username: str | None = None,
    first_name: str | None = None,
    last_name: str | None = None,
) -> tuple[User, bool]:
    platform_user_id_str = str(platform_user_id)
    user = await get_by_platform_id(session, platform, platform_user_id_str)
    created = False
    if user is None:
        user = User(
            telegram_id=legacy_id_for_platform(platform, platform_user_id_str),
            platform=platform,
            platform_user_id=platform_user_id_str,
            username=username,
            first_name=first_name,
            last_name=last_name,
        )
        session.add(user)
        created = True
    else:
        user.username = username
        user.first_name = first_name
        user.last_name = last_name

    apply_env_roles(user, settings)
    await session.commit()
    await session.refresh(user)
    return user, created


async def set_agent(session: AsyncSession, user: User) -> User:
    user.is_agent = True
    if not user.is_admin and not user.is_manager:
        user.role = UserRole.AGENT.value
    await session.commit()
    await session.refresh(user)
    # Always reconcile the CRM stage. Existing users may already have is_agent=True
    # from before the separate agent funnel was introduced.
    enqueue_agent_amocrm_sync(user.id, "became_agent")
    return user


async def set_client(session: AsyncSession, user: User) -> User:
    user.is_client = True
    if not user.is_admin and not user.is_manager and not user.is_agent:
        user.role = UserRole.CLIENT.value
    await session.commit()
    await session.refresh(user)
    return user


async def set_regular(session: AsyncSession, user: User) -> User:
    user.is_client = False
    user.is_agent = False
    if not user.is_admin and not user.is_manager:
        user.role = UserRole.USER.value
    await session.commit()
    await session.refresh(user)
    return user


async def search_user(session: AsyncSession, query: str) -> User | None:
    value = query.strip().lstrip("@")
    if value.isdigit():
        stmt: Select[tuple[User]] = select(User).where(
            (User.telegram_id == int(value)) | (User.id == int(value)) | (User.platform_user_id == value)
        )
    else:
        stmt = select(User).where((func.lower(User.username) == value.lower()) | (User.platform_user_id == value))
    result = await session.execute(stmt)
    return result.scalars().first()


async def list_agents(session: AsyncSession, limit: int = 20, platform: str | None = None) -> list[User]:
    stmt = select(User).where(User.is_agent.is_(True)).order_by(User.created_at.desc()).limit(limit)
    if platform:
        stmt = stmt.where(User.platform == platform)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def list_managers(session: AsyncSession, platform: str | None = None) -> list[User]:
    stmt = select(User).where(User.is_manager.is_(True)).order_by(User.created_at.desc())
    if platform:
        stmt = stmt.where(User.platform == platform)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def list_staff_by_platform(session: AsyncSession, platform: str) -> list[User]:
    from app.services.developer import (
        STAFF_NOTIFICATIONS,
        can_send_to_user,
        fallback_developer_recipient,
        get_bool,
        participant_recipients,
        test_mode_enabled,
    )

    if await test_mode_enabled(session):
        if not await get_bool(session, STAFF_NOTIFICATIONS):
            return []
        recipients = await participant_recipients(session, platform, roles={"manager", "admin"})
        if recipients:
            return [user for user in recipients if await can_send_to_user(session, user, STAFF_NOTIFICATIONS)]
        if platform == "telegram":
            from app.config import get_settings

            fallback = await fallback_developer_recipient(session, get_settings())
            return [user for user in fallback if await can_send_to_user(session, user, STAFF_NOTIFICATIONS)]
        return []

    result = await session.execute(
        select(User).where(
            User.platform == platform,
            ((User.is_manager.is_(True)) | (User.is_admin.is_(True))),
            ((User.is_admin.is_(False)) | (User.admin_notifications_enabled.is_(True))),
        )
    )
    users = list(result.scalars().all())
    return [user for user in users if await can_send_to_user(session, user, STAFF_NOTIFICATIONS)]
