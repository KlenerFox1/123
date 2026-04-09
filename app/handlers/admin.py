from __future__ import annotations

import csv
from pathlib import Path

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, FSInputFile, Message

from app.config import Config, is_admin
from app.db import Database
from app.fsm import AdminBroadcastFlow, AdminNoteFlow, AdminSettingsFlow, AdminTopupUserFlow, AdminTreasuryTopupFlow
from app.services.cryptobot import CryptoBotAPI, CryptoBotError
from app.ui import keyboards as kb

router = Router(name="admin")


def _guard(message_user_id: int, cfg: Config) -> bool:
    return is_admin(message_user_id, cfg)


def _request_text(request_id: int, user_id: int, account_type: str, phone: str, status: str, note: str | None, code_value: str | None) -> str:
    return (
        f"📦 Заявка #{request_id}\n\n"
        f"👤 User: <code>{user_id}</code>\n"
        f"🛰 Сервис: {account_type}\n"
        f"📱 Номер: <code>{phone}</code>\n"
        f"📌 Статус: {status}\n"
        f"📝 Заметка: {note or '—'}\n"
        f"🔐 Код: {code_value or '—'}"
    )


@router.message(Command("admin"))
async def admin_cmd(message: Message, cfg: Config) -> None:
    if not _guard(message.from_user.id, cfg):
        return
    await message.answer("🛠 <b>Админ панель</b>", reply_markup=kb.admin_menu())


@router.callback_query(F.data == "a:home")
async def admin_home(cb: CallbackQuery, cfg: Config) -> None:
    if not _guard(cb.from_user.id, cfg):
        await cb.answer("Нет доступа", show_alert=True)
        return
    await cb.message.edit_text("🛠 <b>Админ панель</b>", reply_markup=kb.admin_menu())
    await cb.answer()


@router.callback_query(F.data == "a:reqs")
async def admin_requests(cb: CallbackQuery, db: Database, cfg: Config) -> None:
    if not _guard(cb.from_user.id, cfg):
        return
    items = await db.list_pending_requests(limit=100)
    if not items:
        await cb.message.edit_text("📦 Заявок нет.", reply_markup=kb.admin_cancel_menu("a:home"))
        await cb.answer()
        return
    await cb.message.edit_text("📦 <b>Очередь заявок</b>", reply_markup=kb.admin_requests_menu(items))
    await cb.answer()


@router.callback_query(F.data.startswith("a:r:"))
async def admin_request_card(cb: CallbackQuery, db: Database, cfg: Config, state: FSMContext) -> None:
    if not _guard(cb.from_user.id, cfg):
        return
    parts = cb.data.split(":")
    request_id = int(parts[2])
    action = parts[3] if len(parts) > 3 else "open"
    request = await db.get_request(request_id)
    if request is None:
        await cb.answer("Заявка не найдена", show_alert=True)
        return

    if action == "ok":
        if request.status != "approved":
            await db.set_request_status(request_id, "approved")
            price = await db.get_account_type_price(request.account_type)
            await db.add_balance(request.user_id, price)
            try:
                await cb.bot.send_message(request.user_id, f"✅ Ваш номер одобрен. Начислено ${price:.2f}")
            except Exception:
                pass
    elif action == "take":
        await db.set_request_status(request_id, "taken")
        try:
            await cb.bot.send_message(request.user_id, "🙅 Администратор взял номер в работу.")
        except Exception:
            pass
    elif action == "ask":
        await db.set_request_status(request_id, "code_requested")
        try:
            await cb.bot.send_message(request.user_id, "📨 Администратор запросил код\nОтветом выдайте код на это сообщение")
        except Exception:
            pass
    elif action == "rej":
        await db.set_request_status(request_id, "rejected")
        try:
            await cb.bot.send_message(request.user_id, "❌ Ваш номер отклонён.")
        except Exception:
            pass
    elif action == "wk":
        request = await db.toggle_request_flag(request_id, "is_work") or request
    elif action == "vip":
        request = await db.toggle_request_flag(request_id, "is_vip") or request
    elif action == "code":
        await cb.answer(request.code_value or "Код отсутствует", show_alert=True)
    elif action == "note":
        await state.set_state(AdminNoteFlow.text)
        await state.update_data(request_id=request_id)
        await cb.message.edit_text("📝 Отправьте заметку одним сообщением.", reply_markup=kb.admin_cancel_menu("a:home", "a:reqs"))
        await cb.answer()
        return
    elif action == "log":
        await cb.message.edit_text(f"📜 Лог заявки #{request_id}\n\n{request.logs or '—'}", reply_markup=kb.admin_cancel_menu("a:home", "a:reqs"))
        await cb.answer()
        return

    request = await db.get_request(request_id) or request
    await cb.message.edit_text(
        _request_text(request.request_id, request.user_id, request.account_type, request.phone, request.status, request.admin_note, request.code_value),
        reply_markup=kb.admin_request_card(request.request_id, is_work=request.is_work, is_vip=request.is_vip, has_code=bool(request.code_value)),
    )
    await cb.answer()


@router.message(AdminNoteFlow.text)
async def save_note(message: Message, db: Database, state: FSMContext, cfg: Config) -> None:
    if not _guard(message.from_user.id, cfg):
        return
    data = await state.get_data()
    request_id = int(data.get("request_id") or 0)
    note = (message.text or "").strip()
    if request_id <= 0 or not note:
        await message.answer("Ошибка заметки.")
        return
    await db.set_admin_note(request_id, note)
    await state.clear()
    await message.answer("✅ Заметка сохранена.", reply_markup=kb.admin_menu())


@router.callback_query(F.data == "a:types")
async def types_menu(cb: CallbackQuery, db: Database, cfg: Config, state: FSMContext) -> None:
    if not _guard(cb.from_user.id, cfg):
        return
    items = await db.get_account_types_full()
    await state.set_state(AdminSettingsFlow.account_types)
    await cb.message.edit_text("🧾 <b>Типы аккаунтов</b>\nОтправьте новую цену сообщением в формате: Название=0.7", reply_markup=kb.admin_types_menu(items))
    await cb.answer()


@router.callback_query(F.data.startswith("a:type:"))
async def type_hint(cb: CallbackQuery, state: FSMContext, cfg: Config) -> None:
    if not _guard(cb.from_user.id, cfg):
        return
    name = cb.data.split(":", 2)[2]
    await state.set_state(AdminSettingsFlow.account_types)
    await state.update_data(target_type=name)
    await cb.message.edit_text(
        f"🧾 Обновление цены для <b>{name}</b>\n\nОтправьте новую цену одним сообщением в формате: 0.7",
        reply_markup=kb.admin_cancel_menu("a:home", "a:types"),
    )
    await cb.answer()


@router.message(AdminSettingsFlow.account_types)
async def update_type_price(message: Message, db: Database, state: FSMContext, cfg: Config) -> None:
    if not _guard(message.from_user.id, cfg):
        return
    data = await state.get_data()
    name = data.get("target_type", "")
    if not name:
        await state.clear()
        await message.answer("Ошибка процесса.")
        return
    raw = (message.text or "").strip()
    try:
        price = float(raw.replace(",", ".").strip())
    except ValueError:
        await message.answer("Введите число, например: 0.7")
        return
    items = await db.get_account_types_full()
    updated = False
    for item in items:
        if str(item.get("name")) == name:
            item["price"] = price
            updated = True
            break
    if updated:
        await db.set_account_types(items)
        await state.clear()
        await message.answer(f"✅ Цена для {name} обновлена: ${price:.2f}", reply_markup=kb.admin_menu())
    else:
        await state.clear()
        await message.answer("Тип аккаунта не найден.")


@router.callback_query(F.data == "a:set")
async def settings_menu(cb: CallbackQuery, db: Database, cfg: Config) -> None:
    if not _guard(cb.from_user.id, cfg):
        return
    min_withdraw = await db.get_min_withdraw()
    maintenance = await db.get_maintenance_mode()
    text = (
        f"⚙️ <b>Настройки бота</b>\n\n"
        f"min_withdraw: {min_withdraw}\n"
        f"maintenance_mode: {'ON' if maintenance else 'OFF'}"
    )
    await cb.message.edit_text(text, reply_markup=kb.admin_settings_menu())
    await cb.answer()


@router.callback_query(F.data == "a:set:minw")
async def settings_min_withdraw(cb: CallbackQuery, state: FSMContext, cfg: Config) -> None:
    if not _guard(cb.from_user.id, cfg):
        return
    await state.set_state(AdminSettingsFlow.min_withdraw)
    await cb.message.edit_text("💸 Отправьте новое значение min_withdraw числом.", reply_markup=kb.admin_cancel_menu("a:home", "a:set"))
    await cb.answer()


@router.message(AdminSettingsFlow.min_withdraw)
async def save_min_withdraw(message: Message, db: Database, state: FSMContext, cfg: Config) -> None:
    if not _guard(message.from_user.id, cfg):
        return
    raw = (message.text or "").replace(",", ".").strip()
    try:
        value = float(raw)
    except ValueError:
        await message.answer("Введите число.")
        return
    await db.set_min_withdraw(value)
    await state.clear()
    await message.answer(f"✅ min_withdraw обновлён: {value}", reply_markup=kb.admin_menu())


@router.callback_query(F.data == "a:set:maint")
async def toggle_maintenance(cb: CallbackQuery, db: Database, cfg: Config) -> None:
    if not _guard(cb.from_user.id, cfg):
        return
    value = await db.toggle_maintenance_mode()
    await cb.answer(f"Тех. перерыв: {'включён' if value else 'выключен'}", show_alert=True)


@router.callback_query(F.data == "a:users")
async def users_export(cb: CallbackQuery, db: Database, cfg: Config) -> None:
    if not _guard(cb.from_user.id, cfg):
        return
    from openpyxl import Workbook

    workbook = Workbook()
    ws = workbook.active
    ws.title = "users"
    ws.append(["user_id", "balance", "bonus", "frozen", "cryptobot_id"])
    for user in await db.list_users():
        ws.append([user.user_id, user.balance, user.bonus, user.frozen, user.cryptobot_id or ""])
    path = Path("users.xlsx").resolve()
    workbook.save(path)
    await cb.message.answer_document(FSInputFile(str(path), filename="users.xlsx"))
    await cb.answer()


@router.callback_query(F.data == "a:backup")
async def backup_db(cb: CallbackQuery, cfg: Config) -> None:
    if not _guard(cb.from_user.id, cfg):
        return
    path = Path("bot_database.db").resolve()
    await cb.message.answer_document(FSInputFile(str(path), filename="bot_database.db"))
    await cb.answer()


@router.callback_query(F.data == "a:broadcast")
async def broadcast_start(cb: CallbackQuery, state: FSMContext, cfg: Config) -> None:
    if not _guard(cb.from_user.id, cfg):
        return
    await state.set_state(AdminBroadcastFlow.text)
    await cb.message.edit_text("📣 Отправьте текст рассылки одним сообщением.", reply_markup=kb.admin_cancel_menu("a:home"))
    await cb.answer()


@router.message(AdminBroadcastFlow.text)
async def broadcast_send(message: Message, db: Database, state: FSMContext, cfg: Config) -> None:
    if not _guard(message.from_user.id, cfg):
        return
    text = (message.text or "").strip()
    if not text:
        return
    count = 0
    for user in await db.list_users():
        try:
            await message.bot.send_message(user.user_id, text)
            count += 1
        except Exception:
            continue
    await state.clear()
    await message.answer(f"✅ Рассылка завершена. Отправлено: {count}", reply_markup=kb.admin_menu())


@router.callback_query(F.data == "a:topup")
async def topup_start(cb: CallbackQuery, state: FSMContext, cfg: Config) -> None:
    if not _guard(cb.from_user.id, cfg):
        return
    await state.set_state(AdminTopupUserFlow.user_id)
    await cb.message.edit_text("➕ Отправьте user_id пользователя.", reply_markup=kb.admin_cancel_menu("a:home"))
    await cb.answer()


@router.message(AdminTopupUserFlow.user_id)
async def topup_user_id(message: Message, state: FSMContext, cfg: Config) -> None:
    if not _guard(message.from_user.id, cfg):
        return
    try:
        user_id = int((message.text or "").strip())
    except ValueError:
        await message.answer("Нужен user_id числом.")
        return
    await state.update_data(user_id=user_id)
    await state.set_state(AdminTopupUserFlow.amount)
    await message.answer("💰 Теперь отправьте сумму.")


@router.message(AdminTopupUserFlow.amount)
async def topup_amount(message: Message, db: Database, state: FSMContext, cfg: Config) -> None:
    if not _guard(message.from_user.id, cfg):
        return
    data = await state.get_data()
    user_id = int(data.get("user_id") or 0)
    try:
        amount = float((message.text or "").replace(",", ".").strip())
    except ValueError:
        await message.answer("Введите число.")
        return
    await db.add_balance(user_id, amount)
    await state.clear()
    await message.answer(f"✅ Пользователю {user_id} начислено ${amount:.2f}", reply_markup=kb.admin_menu())


@router.callback_query(F.data == "a:treasury")
async def treasury_start(cb: CallbackQuery, db: Database, state: FSMContext, cfg: Config) -> None:
    if not _guard(cb.from_user.id, cfg):
        return
    balance = await db.get_treasury_balance()
    await state.set_state(AdminTreasuryTopupFlow.amount)
    await cb.message.edit_text(f"🏦 Баланс казны: ${balance:.2f}\n\nОтправьте сумму пополнения казны.", reply_markup=kb.admin_cancel_menu("a:home"))
    await cb.answer()


@router.message(AdminTreasuryTopupFlow.amount)
async def treasury_amount(message: Message, db: Database, state: FSMContext, cryptobot: CryptoBotAPI, cfg: Config) -> None:
    if not _guard(message.from_user.id, cfg):
        return
    try:
        amount = float((message.text or "").replace(",", ".").strip())
    except ValueError:
        await message.answer("Введите число.")
        return
    try:
        invoice = await cryptobot.create_invoice(amount=amount, asset="USDT", description="Treasury topup")
    except (CryptoBotError, Exception):
        await state.clear()
        await message.answer("Не удалось создать инвойс.", reply_markup=kb.admin_menu())
        return
    await db.create_invoice(invoice_id=invoice.invoice_id, user_id=message.from_user.id, amount=amount, status=invoice.status, pay_url=invoice.pay_url, target="treasury")
    await state.clear()
    await message.answer(f"🏦 Инвойс для казны создан на ${amount:.2f}\n{invoice.pay_url or ''}", reply_markup=kb.admin_menu())


@router.callback_query(F.data == "a:home:none")
async def _noop(cb: CallbackQuery) -> None:
    await cb.answer()
