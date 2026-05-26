from aiogram.fsm.state import State, StatesGroup


class AgentClientStates(StatesGroup):
    waiting_name = State()
    waiting_phone = State()
    waiting_relation = State()
    waiting_payout_phone = State()


class ChatStates(StatesGroup):
    waiting_user_message = State()
