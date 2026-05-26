from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.sheets import clear_sheet_rows


TABLES_TO_RESET = [
    "bonuses",
    "chat_messages",
    "chat_sessions",
    "referrals",
    "leads",
    "developer_user_mutes",
    "developer_participants",
    "developer_settings",
    "user_states",
    "users",
]


async def reset_database_and_sheet(session: AsyncSession) -> None:
    for table in TABLES_TO_RESET:
        await session.execute(text(f"DELETE FROM {table}"))
    sequence_exists = await session.scalar(
        text("SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'sqlite_sequence'")
    )
    if sequence_exists:
        quoted_names = ", ".join(f"'{table}'" for table in TABLES_TO_RESET)
        await session.execute(text(f"DELETE FROM sqlite_sequence WHERE name IN ({quoted_names})"))
    await session.commit()
    await clear_sheet_rows()
