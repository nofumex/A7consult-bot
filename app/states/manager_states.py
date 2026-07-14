from aiogram.fsm.state import State, StatesGroup


class AgentClientStates(StatesGroup):
    waiting_name = State()
    waiting_phone = State()
    waiting_relation = State()
    waiting_source_permission = State()
    waiting_payout_phone = State()
    waiting_client_warning = State()
    waiting_call_phone_share = State()


class ChatStates(StatesGroup):
    waiting_user_message = State()
