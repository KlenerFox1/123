from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, Message
from aiogram.types import InlineKeyboardMarkup as IKMK


def _one_col(buttons: list[InlineKeyboardButton]) -> IKMK:
    return IKMK(inline_keyboard=[[button] for button in buttons])

from app.config import Config
from app.db import Database
from app.fsm import DepositFlow, SellFlow, WithdrawFlow
from app.services.cryptobot import CryptoBotAPI, CryptoBotError
from app.ui import keyboards as kb

router = Router(name="user")


def _money(value: float) -> str:
    return f"${value:.2f}"


async def _current_service(state: FSMContext) -> str:
    data = await state.get_data()
    return str(data.get("selected_service") or "VK")


async def _home_text(message_user_id: int, db: Database, state: FSMContext) -> str:
    user = await db.get_or_create_user(message_user_id)
    service = await _current_service(state)
    price = await db.get_account_type_price(service)
    my_items = await db.list_user_requests(message_user_id, limit=100)
    pending_all = await db.list_pending_requests(limit=1000)
    maintenance = await db.get_maintenance_mode()
    work_status = "🟥" if maintenance else "✅"
    return (
        f"✨ <b>Приветствую!</b>\n\n"
        f"Статус ворка: {work_status}\n"
        f"📡 Текущий сервис: <b>{service}</b>\n\n"
        f"💎 Ваш баланс: {_money(user.balance)}\n"
        f"📋 Прайс: {_money(price)} за номер\n\n"
        f"Статистика:\n"
        f"├ Ваших номеров в очереди: {len([x for x in my_items if x.status in {'pending', 'taken', 'code_requested', 'code_received'}])}\n"
        f"└ Всего в очереди: {len(pending_all)}\n\n"
        f"Выберите действие:"
    )


@router.message(CommandStart())
async def start_cmd(message: Message, db: Database, state: FSMContext) -> None:
    await db.get_or_create_user(message.from_user.id)
    if not (await state.get_data()).get("selected_service"):
        await state.update_data(selected_service="VK")
    text = await _home_text(message.from_user.id, db, state)
    await message.answer(text, reply_markup=kb.user_main_menu())


@router.callback_query(F.data == "u:home")
async def home(cb: CallbackQuery, db: Database, state: FSMContext) -> None:
    text = await _home_text(cb.from_user.id, db, state)
    await cb.message.edit_text(text, reply_markup=kb.user_main_menu())
    await cb.answer()


@router.callback_query(F.data == "u:svc")
async def service_menu(cb: CallbackQuery, db: Database) -> None:
    items = await db.get_account_types_full()
    await cb.message.edit_text("🛰 <b>Выберите сервис:</b>", reply_markup=kb.service_menu(items))
    await cb.answer()


@router.callback_query(F.data.startswith("u:sv:"))
async def service_select(cb: CallbackQuery, db: Database, state: FSMContext) -> None:
    service = cb.data.split(":", 2)[2]
    await state.update_data(selected_service=service)
    text = await _home_text(cb.from_user.id, db, state)
    await cb.message.edit_text(text, reply_markup=kb.user_main_menu())
    await cb.answer(f"Выбран сервис: {service}")


@router.callback_query(F.data == "u:add")
async def add_number(cb: CallbackQuery, db: Database, state: FSMContext) -> None:
    if await db.get_maintenance_mode():
        await cb.message.edit_text(
            "🛠 Сейчас в боте технический перерыв.\n\nДобавление номеров и основные операции временно недоступны.\nПопробуйте позже.",
            reply_markup=kb.back_home(),
        )
        await cb.answer()
        return
    service = await _current_service(state)
    price = await db.get_account_type_price(service)
    await state.set_state(SellFlow.phone)
    await cb.message.edit_text(
        f"📲 Сервис: <b>{service}</b>\n💰 Прайс: {_money(price)}\n\nОтправьте номер одним сообщением.",
        reply_markup=kb.back_home(),
    )
    await cb.answer()


@router.message(SellFlow.phone)
async def save_number(message: Message, db: Database, state: FSMContext, cfg: Config) -> None:
    phone = (message.text or "").strip()
    digits = "".join(ch for ch in phone if ch.isdigit())
    if digits.startswith("8") and len(digits) == 11:
        digits = "7" + digits[1:]
    if digits.startswith("7") and len(digits) == 11:
        phone = "+7" + digits[1:]
    else:
        await message.answer("❌ Номер должен быть в формате +7XXXXXXXXXX")
        return

    service = await _current_service(state)
    request_id = await db.create_request(user_id=message.from_user.id, account_type=service, phone=phone)
    await state.clear()
    await state.update_data(selected_service=service)
    await message.answer(f"✅ Номер добавлен в очередь.\nЗаявка #{request_id}\nСервис: {service}\nНомер: {phone}")

    admin_text = (
        f"📥 Новый номер\n\n"
        f"Заявка: #{request_id}\n"
        f"Пользователь: <code>{message.from_user.id}</code>\n"
        f"Сервис: {service}\n"
        f"Номер: <code>{phone}</code>"
    )
    for admin_id in cfg.all_admin_ids:
        try:
            await message.bot.send_message(
                admin_id,
                admin_text,
                reply_markup=kb.admin_request_card(request_id, is_work=0, is_vip=0, has_code=False),
            )
        except Exception:
            continue


@router.callback_query(F.data == "u:reqs")
async def user_requests(cb: CallbackQuery, db: Database) -> None:
    items = await db.list_user_requests(cb.from_user.id, limit=50)
    if not items:
        await cb.message.edit_text("📋 У вас пока нет добавленных номеров.", reply_markup=kb.back_home())
        await cb.answer()
        return
    await cb.message.edit_text("📋 <b>Мои номера</b>", reply_markup=kb.my_requests_menu(items))
    await cb.answer()


@router.callback_query(F.data.startswith("u:r:"))
async def user_request_card(cb: CallbackQuery, db: Database) -> None:
    request_id = int(cb.data.split(":")[2])
    request = await db.get_request(request_id)
    if request is None or request.user_id != cb.from_user.id:
        await cb.answer("Не найдено", show_alert=True)
        return
    text = (
        f"📦 Заявка #{request.request_id}\n\n"
        f"Сервис: {request.account_type}\n"
        f"Номер: <code>{request.phone}</code>\n"
        f"Статус: {request.status}\n"
        f"Код: {request.code_value or '—'}"
    )
    await cb.message.edit_text(text, reply_markup=kb.back_home())
    await cb.answer()


@router.callback_query(F.data == "u:pf")
async def profile(cb: CallbackQuery, db: Database) -> None:
    user = await db.get_or_create_user(cb.from_user.id)
    min_withdraw = await db.get_min_withdraw()
    text = (
        f"👤 <b>Профиль</b>\n\n"
        f"💎 Баланс: {_money(user.balance)}\n"
        f"🧊 Заморожено: {_money(user.frozen)}\n"
        f"🤖 CryptoBot ID: {user.cryptobot_id if user.cryptobot_id is not None else 'не указан'}\n"
        f"💸 Минимальный вывод: {_money(min_withdraw)}"
    )
    await cb.message.edit_text(
        text,
        reply_markup=_one_col(
            [
                InlineKeyboardButton(text="💳 Пополнить", callback_data="u:dep"),
                InlineKeyboardButton(text="⬅️ Назад", callback_data="u:home"),
            ]
        ),
    )
    await cb.answer()


@router.callback_query(F.data == "u:hp")
async def help_menu(cb: CallbackQuery) -> None:
    await cb.message.edit_text(
        "❓ Помощь\n\n1. Выберите сервис.\n2. Добавьте номер.\n3. Ждите решения администратора.\n4. Если попросят код — ответьте кодом на сообщение бота.",
        reply_markup=kb.back_home(),
    )
    await cb.answer()


@router.callback_query(F.data == "u:dep")
async def deposit(cb: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(DepositFlow.amount)
    await cb.message.edit_text("💳 Введите сумму пополнения в USDT.", reply_markup=kb.back_home())
    await cb.answer()


@router.message(DepositFlow.amount)
async def deposit_amount(message: Message, db: Database, cryptobot: CryptoBotAPI, state: FSMContext) -> None:
    raw = (message.text or "").replace(",", ".").strip()
    try:
        amount = float(raw)
    except ValueError:
        await message.answer("Введите число, например 10")
        return
    if amount <= 0:
        await message.answer("Сумма должна быть больше 0")
        return
    try:
        invoice = await cryptobot.create_invoice(amount=amount, asset="USDT", description="Balance topup")
    except (CryptoBotError, Exception):
        await state.clear()
        await message.answer("Не удалось создать инвойс.")
        return
    await db.create_invoice(invoice_id=invoice.invoice_id, user_id=message.from_user.id, amount=amount, status=invoice.status, pay_url=invoice.pay_url)
    await state.clear()
    await message.answer(f"💳 Инвойс создан на {amount:.2f} USDT", reply_markup=kb.deposit_menu(invoice.invoice_id, invoice.pay_url))


@router.callback_query(F.data.startswith("u:dep:"))
async def deposit_check(cb: CallbackQuery, db: Database, cryptobot: CryptoBotAPI) -> None:
    invoice_id = cb.data.split(":")[2]
    invoices = await cryptobot.get_invoices(invoice_ids=[invoice_id])
    if not invoices:
        await cb.answer("Инвойс не найден", show_alert=True)
        return
    invoice = invoices[0]
    await db.update_invoice_status(invoice_id, invoice.status)
    if invoice.status == "paid":
        credited = await db.credit_invoice_once(invoice_id)
        user = await db.get_or_create_user(cb.from_user.id)
        await cb.message.edit_text(
            f"✅ Оплата подтверждена\nЗачислено: {'да' if credited else 'уже было'}\nБаланс: {_money(user.balance)}",
            reply_markup=kb.back_home(),
        )
    else:
        await cb.answer(f"Статус: {invoice.status}", show_alert=True)


@router.callback_query(F.data == "u:wd")
async def withdraw(cb: CallbackQuery, db: Database, state: FSMContext) -> None:
    user = await db.get_or_create_user(cb.from_user.id)
    if user.cryptobot_id is None:
        await state.set_state(WithdrawFlow.cryptobot_id)
        await cb.message.edit_text(
            "💸 <b>Первый вывод средств</b>\n\n"
            "🤖 Введите ваш CryptoBot user_id для получения выплат.\n\n"
            "ℹ️ Узнать свой ID можно через бота @userinfobot\n\n"
            "📝 Отправьте ID одним сообщением:",
            reply_markup=kb.back_home(),
        )
        await cb.answer()
        return
    await state.set_state(WithdrawFlow.amount)
    await cb.message.edit_text("💸 Введите сумму вывода в USDT.", reply_markup=kb.back_home())
    await cb.answer()


@router.message(WithdrawFlow.cryptobot_id)
async def set_withdraw_id(message: Message, db: Database, state: FSMContext) -> None:
    raw = (message.text or "").strip()
    try:
        cryptobot_id = int(raw)
    except ValueError:
        await message.answer("Нужно указать число.")
        return
    await db.set_cryptobot_id(message.from_user.id, cryptobot_id)
    await state.set_state(WithdrawFlow.amount)
    await message.answer("✅ ID сохранён. Теперь введите сумму вывода.")


@router.message(WithdrawFlow.amount)
async def withdraw_amount(message: Message, db: Database, state: FSMContext) -> None:
    raw = (message.text or "").replace(",", ".").strip()
    try:
        amount = float(raw)
    except ValueError:
        await message.answer("Введите число.")
        return
    user = await db.get_or_create_user(message.from_user.id)
    min_withdraw = await db.get_min_withdraw()
    if amount < min_withdraw:
        await message.answer(f"Минимальный вывод: {_money(min_withdraw)}")
        return
    if user.balance < amount:
        await message.answer(f"Недостаточно средств. Баланс: {_money(user.balance)}")
        return
    withdrawal_id = await db.create_withdrawal(user_id=message.from_user.id, amount=amount, fee=0.0)
    await db.move_balance_to_frozen(message.from_user.id, amount)
    await state.clear()
    await message.answer(f"✅ Заявка на вывод создана #{withdrawal_id}\nСумма: {_money(amount)}")


@router.message(F.reply_to_message.as_("reply_msg"))
async def code_reply(message: Message, reply_msg: Message, db: Database, cfg: Config) -> None:
    text = reply_msg.text or ""
    if "Администратор запросил код" not in text:
        return
    code = (message.text or "").strip()
    if not code:
        return
    requests = await db.list_user_requests(message.from_user.id, limit=20)
    target = next((item for item in requests if item.status == "code_requested"), None)
    if target is None:
        await message.answer("Не найдена заявка для кода.")
        return
    await db.set_request_code(target.request_id, code)
    await db.set_request_status(target.request_id, "code_received")
    await message.answer("✅ Код отправлен администратору.")
    admin_text = (
        f"📨 Пользователь дал код\n\n"
        f"Заявка: #{target.request_id}\n"
        f"Пользователь: <code>{target.user_id}</code>\n"
        f"Сервис: {target.account_type}"
    )
    for admin_id in cfg.all_admin_ids:
        try:
            await message.bot.send_message(
                admin_id,
                admin_text,
                reply_markup=kb.admin_request_card(target.request_id, is_work=target.is_work, is_vip=target.is_vip, has_code=True),
            )
        except Exception:
            continue
