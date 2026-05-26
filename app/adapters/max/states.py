from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import UserState


async def get_state(session: AsyncSession, platform_user_id: str) -> tuple[str | None, dict[str, Any]]:
    result = await session.execute(
        select(UserState).where(UserState.platform == "max", UserState.platform_user_id == str(platform_user_id))
    )
    row = result.scalar_one_or_none()
    if not row:
        return None, {}
    try:
        data = json.loads(row.data_json or "{}")
    except json.JSONDecodeError:
        data = {}
    return row.state, data


async def set_state(session: AsyncSession, platform_user_id: str, state: str | None, data: dict[str, Any] | None = None) -> None:
    result = await session.execute(
        select(UserState).where(UserState.platform == "max", UserState.platform_user_id == str(platform_user_id))
    )
    row = result.scalar_one_or_none()
    if not row:
        row = UserState(platform="max", platform_user_id=str(platform_user_id))
        session.add(row)
    row.state = state
    row.data_json = json.dumps(data or {}, ensure_ascii=False)
    await session.commit()


async def update_state_data(session: AsyncSession, platform_user_id: str, **kwargs: Any) -> dict[str, Any]:
    state, data = await get_state(session, platform_user_id)
    data.update(kwargs)
    await set_state(session, platform_user_id, state, data)
    return data


async def clear_state(session: AsyncSession, platform_user_id: str) -> None:
    await set_state(session, platform_user_id, None, {})
