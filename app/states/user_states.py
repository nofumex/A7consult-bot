from aiogram.fsm.state import State, StatesGroup


class ConsultationStates(StatesGroup):
    waiting_phone = State()


class QuestionStates(StatesGroup):
    waiting_question = State()
