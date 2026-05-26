from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import set_committed_value

from app.config import Settings, get_settings
from app.models import DeveloperParticipant, DeveloperSetting, DeveloperUserMute, Lead, User
from app.utils.text import full_name, username_text

TEST_MODE = "test_mode_enabled"
STAFF_NOTIFICATIONS = "staff_notifications_enabled"
BROADCASTS = "broadcasts_enabled"
BONUS_NOTIFICATIONS = "bonus_notifications_enabled"
CHAT_BRIDGE = "chat_bridge_enabled"
ALL_DELIVERIES = "all_deliveries"

SETTING_DEFAULTS = {
    TEST_MODE: False,
    STAFF_NOTIFICATIONS: True,
    BROADCASTS: True,
    BONUS_NOTIFICATIONS: True,
    CHAT_BRIDGE: True,
}

FEATURE_LABELS = {
    TEST_MODE: "Тестовый режим",
    STAFF_NOTIFICATIONS: "Уведомления по заявкам",
    BROADCASTS: "Рассылки",
    BONUS_NOTIFICATIONS: "Уведомления о бонусах",
    CHAT_BRIDGE: "Чаты менеджер-клиент",
}

USER_MUTE_LABELS = {
    ALL_DELIVERIES: "Все рассылки и уведомления",
    STAFF_NOTIFICATIONS: "Новые заявки / новый клиент",
    BROADCASTS: "Обычные рассылки",
    BONUS_NOTIFICATIONS: "Уведомления о бонусах",
}

MUTE_FIELD_BY_KEY = {
    ALL_DELIVERIES: "mute_all",
    STAFF_NOTIFICATIONS: "mute_staff_notifications",
    BROADCASTS: "mute_broadcasts",
    BONUS_NOTIFICATIONS: "mute_bonus_notifications",
}

ROLE_LABELS = {
    "user": "Пользователь",
    "manager": "Менеджер",
    "admin": "Админ",
}


def is_developer(user: User | None, settings: Settings) -> bool:
    return bool(user and settings.dev_id and user.telegram_id == settings.dev_id)


def _bool_to_value(value: bool) -> str:
    return "1" if value else "0"


def _value_to_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on", "да", "вкл"}


async def get_bool(session: AsyncSession, key: str) -> bool:
    default = SETTING_DEFAULTS.get(key, False)
    setting = await session.get(DeveloperSetting, key)
    return _value_to_bool(setting.value if setting else None, default)


async def set_bool(session: AsyncSession, key: str, value: bool) -> bool:
    setting = await session.get(DeveloperSetting, key)
    if setting is None:
        setting = DeveloperSetting(key=key, value=_bool_to_value(value))
        session.add(setting)
    else:
        setting.value = _bool_to_value(value)
    await session.commit()
    return value


async def toggle_bool(session: AsyncSession, key: str) -> bool:
    return await set_bool(session, key, not await get_bool(session, key))


async def test_mode_enabled(session: AsyncSession) -> bool:
    return await get_bool(session, TEST_MODE)


async def feature_enabled(session: AsyncSession, key: str) -> bool:
    if not await test_mode_enabled(session):
        return True
    return await get_bool(session, key)


async def status(session: AsyncSession) -> dict[str, bool | int]:
    participants_total = await session.scalar(select(func.count(DeveloperParticipant.id)))
    participants_enabled = await session.scalar(
        select(func.count(DeveloperParticipant.id)).where(DeveloperParticipant.enabled.is_(True))
    )
    data: dict[str, bool | int] = {
        key: await get_bool(session, key)
        for key in SETTING_DEFAULTS
    }
    data["participants_total"] = int(participants_total or 0)
    data["participants_enabled"] = int(participants_enabled or 0)
    return data


async def add_or_update_participant(session: AsyncSession, user: User, role: str) -> DeveloperParticipant:
    role = role if role in ROLE_LABELS else "user"
    result = await session.execute(
        select(DeveloperParticipant).where(
            DeveloperParticipant.platform == (user.platform or "telegram"),
            DeveloperParticipant.platform_user_id == str(user.platform_user_id or user.telegram_id),
        )
    )
    participant = result.scalar_one_or_none()
    if participant is None:
        participant = DeveloperParticipant(
            platform=user.platform or "telegram",
            platform_user_id=str(user.platform_user_id or user.telegram_id),
            user_id=user.id,
            role=role,
            label=full_name(user),
            enabled=True,
        )
        session.add(participant)
    else:
        participant.user_id = user.id
        participant.role = role
        participant.label = full_name(user)
        participant.enabled = True
    await session.commit()
    await session.refresh(participant)
    return participant


async def get_participant(session: AsyncSession, participant_id: int) -> DeveloperParticipant | None:
    return await session.get(DeveloperParticipant, participant_id)


async def list_participants(session: AsyncSession, platform: str | None = None) -> list[DeveloperParticipant]:
    stmt = select(DeveloperParticipant).order_by(DeveloperParticipant.created_at.desc())
    if platform:
        stmt = stmt.where(DeveloperParticipant.platform == platform)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def toggle_participant(session: AsyncSession, participant: DeveloperParticipant) -> DeveloperParticipant:
    participant.enabled = not participant.enabled
    await session.commit()
    await session.refresh(participant)
    return participant


async def remove_participant(session: AsyncSession, participant: DeveloperParticipant) -> None:
    await session.delete(participant)
    await session.commit()


async def participant_user_ids(session: AsyncSession, platform: str | None = None) -> set[int]:
    stmt = select(DeveloperParticipant.user_id).where(
        DeveloperParticipant.enabled.is_(True),
        DeveloperParticipant.user_id.is_not(None),
    )
    if platform:
        stmt = stmt.where(DeveloperParticipant.platform == platform)
    result = await session.execute(stmt)
    ids = {int(user_id) for user_id in result.scalars().all() if user_id is not None}
    settings = get_settings()
    if (platform in {None, "telegram"}) and settings.dev_id:
        dev_result = await session.execute(select(User.id).where(User.platform == "telegram", User.telegram_id == settings.dev_id))
        dev_user_id = dev_result.scalar_one_or_none()
        if dev_user_id is not None:
            ids.add(int(dev_user_id))
    return ids


async def participant_recipients(
    session: AsyncSession,
    platform: str,
    roles: set[str] | None = None,
) -> list[User]:
    stmt = (
        select(User)
        .join(DeveloperParticipant, DeveloperParticipant.user_id == User.id)
        .where(
            DeveloperParticipant.platform == platform,
            DeveloperParticipant.enabled.is_(True),
            User.platform == platform,
        )
    )
    if roles:
        stmt = stmt.where(DeveloperParticipant.role.in_(roles))
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def fallback_developer_recipient(session: AsyncSession, settings: Settings) -> list[User]:
    if not settings.dev_id:
        return []
    result = await session.execute(select(User).where(User.platform == "telegram", User.telegram_id == settings.dev_id))
    user = result.scalar_one_or_none()
    return [user] if user else []


async def apply_developer_role_override(session: AsyncSession, user: User) -> None:
    if not await test_mode_enabled(session):
        return
    result = await session.execute(
        select(DeveloperParticipant).where(
            DeveloperParticipant.platform == (user.platform or "telegram"),
            DeveloperParticipant.platform_user_id == str(user.platform_user_id or user.telegram_id),
            DeveloperParticipant.enabled.is_(True),
        )
    )
    participant = result.scalar_one_or_none()
    if not participant:
        return
    if participant.role == "admin":
        set_committed_value(user, "is_admin", True)
        set_committed_value(user, "is_manager", True)
        set_committed_value(user, "role", "admin")
    elif participant.role == "manager":
        set_committed_value(user, "is_manager", True)
        set_committed_value(user, "role", "manager")


async def is_participant_user(session: AsyncSession, user: User | None) -> bool:
    if user is None:
        return False
    settings = get_settings()
    if user.platform == "telegram" and settings.dev_id and user.telegram_id == settings.dev_id:
        return True
    result = await session.execute(
        select(DeveloperParticipant.id).where(
            DeveloperParticipant.platform == (user.platform or "telegram"),
            DeveloperParticipant.platform_user_id == str(user.platform_user_id or user.telegram_id),
            DeveloperParticipant.enabled.is_(True),
        )
    )
    return result.scalar_one_or_none() is not None


async def can_touch_lead(session: AsyncSession, lead: Lead | None) -> bool:
    if not lead or not await test_mode_enabled(session):
        return True
    ids = await participant_user_ids(session, platform=lead.platform)
    return bool((lead.user_id and lead.user_id in ids) or (lead.agent_id and lead.agent_id in ids))


async def filter_leads(session: AsyncSession, leads: list[Lead]) -> list[Lead]:
    if not await test_mode_enabled(session):
        return leads
    if not leads:
        return []
    ids = await participant_user_ids(session, platform=leads[0].platform)
    return [
        lead
        for lead in leads
        if (lead.user_id and lead.user_id in ids) or (lead.agent_id and lead.agent_id in ids)
    ]


async def can_send_to_user(session: AsyncSession, user: User | None, feature_key: str) -> bool:
    if await is_user_muted(session, user, feature_key):
        return False
    if not await test_mode_enabled(session):
        return True
    if not await get_bool(session, feature_key):
        return False
    return await is_participant_user(session, user)


async def get_user_mute(session: AsyncSession, user_id: int) -> DeveloperUserMute | None:
    result = await session.execute(select(DeveloperUserMute).where(DeveloperUserMute.user_id == user_id))
    return result.scalar_one_or_none()


async def get_or_create_user_mute(session: AsyncSession, user: User) -> DeveloperUserMute:
    mute = await get_user_mute(session, user.id)
    if mute is None:
        mute = DeveloperUserMute(user_id=user.id)
        session.add(mute)
        await session.commit()
        await session.refresh(mute, ["user"])
    return mute


async def toggle_user_mute(session: AsyncSession, user: User, key: str) -> DeveloperUserMute:
    if key not in MUTE_FIELD_BY_KEY:
        raise ValueError(f"Unknown mute key: {key}")
    mute = await get_or_create_user_mute(session, user)
    field = MUTE_FIELD_BY_KEY[key]
    setattr(mute, field, not getattr(mute, field))
    await session.commit()
    await session.refresh(mute, ["user"])
    return mute


async def is_user_muted(session: AsyncSession, user: User | None, feature_key: str) -> bool:
    if user is None:
        return False
    mute = await get_user_mute(session, user.id)
    if mute is None:
        return False
    if mute.mute_all:
        return True
    field = MUTE_FIELD_BY_KEY.get(feature_key)
    return bool(field and getattr(mute, field))


def user_mute_line(user: User, mute: DeveloperUserMute | None) -> str:
    def value(enabled: bool) -> str:
        return "отключено" if enabled else "включено"

    all_muted = bool(mute and mute.mute_all)
    return (
        f"<b>{full_name(user)}</b> ({username_text(user)})\n"
        f"ID: <code>{user.telegram_id or user.platform_user_id or user.id}</code>\n\n"
        f"{USER_MUTE_LABELS[ALL_DELIVERIES]}: <b>{value(all_muted)}</b>\n"
        f"{USER_MUTE_LABELS[STAFF_NOTIFICATIONS]}: <b>{value(all_muted or bool(mute and mute.mute_staff_notifications))}</b>\n"
        f"{USER_MUTE_LABELS[BROADCASTS]}: <b>{value(all_muted or bool(mute and mute.mute_broadcasts))}</b>\n"
        f"{USER_MUTE_LABELS[BONUS_NOTIFICATIONS]}: <b>{value(all_muted or bool(mute and mute.mute_bonus_notifications))}</b>"
    )


def participant_line(participant: DeveloperParticipant) -> str:
    label = participant.label or "Без имени"
    role = ROLE_LABELS.get(participant.role, participant.role)
    enabled = "вкл" if participant.enabled else "выкл"
    user_part = ""
    if participant.user:
        user_part = f", {username_text(participant.user)}"
    return f"#{participant.id}: {label}{user_part} - {role}, {enabled}"
