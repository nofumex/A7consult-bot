from __future__ import annotations

import re

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, ReplyKeyboardRemove
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.keyboards.manager_keyboards import lead_actions
from app.keyboards.user_keyboards import about_menu, client_menu, main_menu, request_phone_reply
from app.models import User
from app.services.leads import create_consultation_lead, create_question_lead
from app.services.notifications import notify_staff
from app.services.developer import is_participant_user, test_mode_enabled
from app.services.referrals import attach_referrer
from app.states.user_states import ConsultationStates, QuestionStates
from app.utils.assets import CONSULTATION_IMAGE, DEBT_IMAGE, local_photo
from app.utils.text import client_info_text, company_text, consultation_prompt, new_lead_notification, welcome_text
from app.utils.validators import clean_text, normalize_phone

router = Router(name="user")


def _extract_referrer_id(text: str | None) -> int | None:
    if not text:
        return None
    match = re.search(r"ref_(\d+)", text)
    return int(match.group(1)) if match else None


@router.message(CommandStart())
async def cmd_start(
    message: Message,
    session: AsyncSession,
    current_user: User,
    settings: Settings,
    state: FSMContext,
) -> None:
    await state.clear()
    referrer_telegram_id = _extract_referrer_id(message.text)
    if referrer_telegram_id:
        await attach_referrer(session, current_user, referrer_telegram_id)
    await message.answer(welcome_text(), reply_markup=main_menu())


@router.callback_query(F.data == "user:main")
async def cb_main(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.answer(welcome_text(), reply_markup=main_menu())
    await callback.answer()


@router.callback_query(F.data == "user:debts")
async def cb_debts(callback: CallbackQuery) -> None:
    photo = local_photo(DEBT_IMAGE)
    if photo:
        await callback.message.answer_photo(photo)
    await callback.message.answer(client_info_text(), reply_markup=client_menu())
    await callback.answer()


@router.message(Command("consultation"))
@router.callback_query(F.data == "user:consultation")
async def start_consultation(event: Message | CallbackQuery, state: FSMContext) -> None:
    await state.set_state(ConsultationStates.waiting_phone)
    photo = local_photo(CONSULTATION_IMAGE)
    if isinstance(event, CallbackQuery):
        if photo:
            await event.message.answer_photo(photo)
        await event.message.answer(consultation_prompt(), reply_markup=request_phone_reply())
        await event.answer()
    else:
        if photo:
            await event.answer_photo(photo)
        await event.answer(consultation_prompt(), reply_markup=request_phone_reply())


@router.message(ConsultationStates.waiting_phone, ~F.text.startswith("/"))
async def process_phone(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    current_user: User,
    bot: Bot,
) -> None:
    raw_phone = message.contact.phone_number if message.contact else message.text
    phone = normalize_phone(raw_phone)
    if not phone:
        await message.answer("Похоже, номер введён некорректно. Введите телефон ещё раз или отправьте контакт.")
        return
    if await test_mode_enabled(session) and not await is_participant_user(session, current_user):
        await state.clear()
        await message.answer("Сейчас включен тестовый режим. Заявки принимаются только от участников теста.")
        return

    lead = await create_consultation_lead(session, current_user, phone)
    await state.clear()
    await message.answer(
        "<b>Спасибо. Заявка принята.</b>\n\nМенеджер «А7 Консалт» скоро свяжется с вами.",
        reply_markup=ReplyKeyboardRemove(),
    )
    await message.answer(
        "Пока заявка передана в работу, можно посмотреть информацию о компании или задать дополнительный вопрос.",
        reply_markup=client_menu(),
    )
    await notify_staff(
        bot,
        session,
        new_lead_notification(lead, "Новая заявка на консультацию"),
        reply_markup=lead_actions(lead.id, include_bonus=False),
    )


@router.callback_query(F.data == "user:question")
async def cb_question(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(QuestionStates.waiting_question)
    await callback.message.answer("<b>Вопрос специалисту</b>\n\nНапишите ваш вопрос одним сообщением.")
    await callback.answer()


@router.message(QuestionStates.waiting_question, ~F.text.startswith("/"))
async def process_question(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    current_user: User,
    bot: Bot,
) -> None:
    question = clean_text(message.text, 3000)
    if not question:
        await message.answer("Пожалуйста, отправьте вопрос текстом.")
        return
    if await test_mode_enabled(session) and not await is_participant_user(session, current_user):
        await state.clear()
        await message.answer("Сейчас включен тестовый режим. Вопросы принимаются только от участников теста.")
        return
    lead = await create_question_lead(session, current_user, question)
    await state.clear()
    await message.answer(
        "<b>Спасибо.</b> Вопрос передан менеджеру. Мы скоро вернёмся с ответом.",
        reply_markup=client_menu(),
    )
    await notify_staff(
        bot,
        session,
        new_lead_notification(lead, "Новый вопрос от пользователя"),
        reply_markup=lead_actions(lead.id, include_bonus=False),
    )


@router.callback_query(F.data == "user:about")
async def cb_about(callback: CallbackQuery, settings: Settings) -> None:
    if settings.company_video_url:
        await callback.message.answer_video(settings.company_video_url)
    await callback.message.answer(company_text(), reply_markup=about_menu())
    await callback.answer()
