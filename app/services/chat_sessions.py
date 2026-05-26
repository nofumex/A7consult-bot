from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import ChatStatus
from app.models import ChatMessage, ChatSession, User


async def open_session(session: AsyncSession, user: User) -> ChatSession:
    existing = await get_user_active_session(session, user.id)
    if existing:
        return existing
    chat = ChatSession(user_id=user.id, status=ChatStatus.OPEN.value)
    session.add(chat)
    await session.commit()
    await session.refresh(chat, ["user"])
    return chat


async def get_session(session: AsyncSession, session_id: int) -> ChatSession | None:
    return await session.get(ChatSession, session_id)


async def get_user_active_session(session: AsyncSession, user_id: int) -> ChatSession | None:
    result = await session.execute(
        select(ChatSession)
        .where(ChatSession.user_id == user_id, ChatSession.status.in_([ChatStatus.OPEN.value, ChatStatus.ACTIVE.value]))
        .order_by(ChatSession.created_at.desc())
    )
    return result.scalars().first()


async def get_manager_active_session(session: AsyncSession, manager_id: int) -> ChatSession | None:
    result = await session.execute(
        select(ChatSession)
        .where(ChatSession.manager_id == manager_id, ChatSession.status == ChatStatus.ACTIVE.value)
        .order_by(ChatSession.connected_at.desc())
    )
    return result.scalars().first()


async def connect_manager(session: AsyncSession, chat: ChatSession, manager: User) -> tuple[ChatSession, bool, bool]:
    current = await get_manager_active_session(session, manager.id)
    if current and current.id != chat.id:
        return current, False, True
    if chat.manager_id and chat.manager_id != manager.id:
        return chat, False, False
    chat.manager_id = manager.id
    chat.status = ChatStatus.ACTIVE.value
    chat.connected_at = datetime.utcnow()
    await session.commit()
    await session.refresh(chat, ["user", "manager"])
    return chat, True, False


async def close_session(session: AsyncSession, chat: ChatSession) -> ChatSession:
    chat.status = ChatStatus.CLOSED.value
    chat.closed_at = datetime.utcnow()
    await session.commit()
    await session.refresh(chat)
    return chat


async def save_message(session: AsyncSession, chat: ChatSession, sender: User, text: str, sender_role: str) -> ChatMessage:
    message = ChatMessage(session_id=chat.id, sender_id=sender.id, sender_role=sender_role, text=text)
    session.add(message)
    await session.commit()
    await session.refresh(message)
    return message
