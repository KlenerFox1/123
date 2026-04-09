from aiogram.fsm.state import State, StatesGroup


class SellFlow(StatesGroup):
    phone = State()


class DepositFlow(StatesGroup):
    amount = State()


class WithdrawFlow(StatesGroup):
    cryptobot_id = State()
    amount = State()


class AdminNoteFlow(StatesGroup):
    text = State()


class AdminSettingsFlow(StatesGroup):
    account_types = State()
    min_withdraw = State()


class AdminTreasuryTopupFlow(StatesGroup):
    amount = State()


class AdminTopupUserFlow(StatesGroup):
    user_id = State()
    amount = State()


class AdminBroadcastFlow(StatesGroup):
    text = State()
