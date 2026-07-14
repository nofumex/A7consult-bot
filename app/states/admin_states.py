from aiogram.fsm.state import State, StatesGroup


class AdminSearchStates(StatesGroup):
    waiting_user_query = State()


class BonusStates(StatesGroup):
    waiting_amount = State()
    waiting_comment = State()


class BroadcastStates(StatesGroup):
    waiting_text = State()


class DeveloperStates(StatesGroup):
    waiting_user_query = State()
    waiting_mute_user_query = State()


class SalesManagerStates(StatesGroup):
    waiting_details = State()
