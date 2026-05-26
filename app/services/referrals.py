from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Lead, Referral, User


async def attach_referrer(session: AsyncSession, user: User, referrer_telegram_id: int) -> bool:
    if user.telegram_id == referrer_telegram_id or user.referrer_id is not None:
        return False
    result = await session.execute(select(User).where(User.telegram_id == referrer_telegram_id))
    referrer = result.scalar_one_or_none()
    if not referrer or not referrer.is_agent:
        return False

    user.referrer_id = referrer.id
    session.add(Referral(referrer_id=referrer.id, referred_id=user.id, level=1))
    if referrer.referrer_id:
        session.add(Referral(referrer_id=referrer.referrer_id, referred_id=user.id, level=2))
    await session.commit()
    return True


async def attach_referrer_by_internal_id(session: AsyncSession, user: User, referrer_id: int) -> bool:
    if user.id == referrer_id or user.referrer_id is not None:
        return False
    referrer = await session.get(User, referrer_id)
    if not referrer or not referrer.is_agent:
        return False

    user.referrer_id = referrer.id
    session.add(Referral(referrer_id=referrer.id, referred_id=user.id, level=1))
    if referrer.referrer_id:
        session.add(Referral(referrer_id=referrer.referrer_id, referred_id=user.id, level=2))
    await session.commit()
    return True


async def referral_counts(session: AsyncSession, user_id: int) -> tuple[int, int]:
    direct = await session.scalar(
        select(func.count(Referral.id)).where(Referral.referrer_id == user_id, Referral.level == 1)
    )
    second = await session.scalar(
        select(func.count(Referral.id)).where(Referral.referrer_id == user_id, Referral.level == 2)
    )
    return int(direct or 0), int(second or 0)


async def referral_leads_count(session: AsyncSession, user_id: int) -> int:
    referred_ids = select(Referral.referred_id).where(Referral.referrer_id == user_id)
    total = await session.scalar(select(func.count(Lead.id)).where(Lead.user_id.in_(referred_ids)))
    return int(total or 0)


async def recent_referrals(session: AsyncSession, user_id: int, limit: int = 10) -> list[Referral]:
    result = await session.execute(
        select(Referral)
        .where(Referral.referrer_id == user_id)
        .order_by(Referral.created_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


def build_ref_link(bot_username: str, telegram_id: int) -> str:
    return f"https://t.me/{bot_username}?start=ref_{telegram_id}"
