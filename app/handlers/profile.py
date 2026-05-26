from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.keyboards.user_keyboards import main_menu, profile_menu
from app.models import User
from app.services.bonuses import bonus_totals
from app.services.referrals import build_ref_link, referral_counts, referral_leads_count
from app.utils.text import profile_text

router = Router(name="profile")


async def send_profile(message: Message, session: AsyncSession, user: User) -> None:
    direct_refs, second_refs = await referral_counts(session, user.id)
    referral_leads = await referral_leads_count(session, user.id)
    bonuses = await bonus_totals(session, user.id)
    await message.answer(
        profile_text(user, direct_refs, second_refs, referral_leads, bonuses, include_service_fields=False),
        reply_markup=profile_menu(),
    )


@router.message(Command("profile"))
async def cmd_profile(message: Message, session: AsyncSession, current_user: User) -> None:
    await send_profile(message, session, current_user)


@router.callback_query(F.data == "profile:show")
async def cb_profile(callback: CallbackQuery, session: AsyncSession, current_user: User) -> None:
    await send_profile(callback.message, session, current_user)
    await callback.answer()


@router.message(Command("ref_url"))
@router.callback_query(F.data == "agent:ref_url")
async def ref_url(event: Message | CallbackQuery, bot: Bot, current_user: User) -> None:
    target = event.message if isinstance(event, CallbackQuery) else event
    if not current_user.is_agent:
        await target.answer(
            "<b>Реферальная ссылка доступна агентам.</b>\n\n"
            "Нажмите «Хочу стать агентом» в Главном меню, чтобы подключиться к сотрудничеству.",
            reply_markup=main_menu(),
        )
        if isinstance(event, CallbackQuery):
            await event.answer()
        return
    me = await bot.get_me()
    link = build_ref_link(me.username, current_user.telegram_id)
    await target.answer(f"<b>Ваша реферальная ссылка (Нажмите, чтобы скопировать)</b>\n\n<code>{link}</code>")
    if isinstance(event, CallbackQuery):
        await event.answer()
