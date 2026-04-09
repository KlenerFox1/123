from __future__ import annotations

import asyncio
import contextlib

from aiogram import Bot

from app.db import Database
from app.services.cryptobot import CryptoBotAPI, CryptoBotError


async def invoice_watcher(*, db: Database, cryptobot: CryptoBotAPI, bot: Bot, interval_sec: int = 10) -> None:
    while True:
        try:
            items = await db.list_uncredited_invoices(limit=100)
            for item in items:
                try:
                    invoices = await cryptobot.get_invoices(invoice_ids=[item["invoice_id"]])
                except CryptoBotError:
                    continue
                if not invoices:
                    continue
                invoice = invoices[0]
                await db.update_invoice_status(item["invoice_id"], invoice.status)
                if invoice.status == "paid":
                    await db.credit_invoice_once(item["invoice_id"])

            treasury_items = await db.list_paid_treasury_invoices_without_notify(limit=20)
            for item in treasury_items:
                text = (
                    "💰 <b>Бот пополнен</b>\n\n"
                    "Касса пополнена — можно выводить выплаты.\n"
                    "👤 Профиль → 💸 Вывести заработок"
                )
                sent_count = 0
                for user in await db.list_users():
                    if user.balance <= 0:
                        continue
                    try:
                        await bot.send_message(user.user_id, text)
                        sent_count += 1
                    except Exception:
                        continue
                await db.mark_invoice_notify_sent(item["invoice_id"])
            await asyncio.sleep(interval_sec)
        except asyncio.CancelledError:
            raise
        except Exception:
            await asyncio.sleep(interval_sec)


async def treasury_balance_watcher(*, db: Database, cryptobot: CryptoBotAPI, interval_sec: int = 5) -> None:
    while True:
        try:
            balance = await cryptobot.get_asset_balance("USDT")
            await db.set_setting("crypto_asset_balance", str(balance))
            await asyncio.sleep(interval_sec)
        except asyncio.CancelledError:
            raise
        except Exception:
            await asyncio.sleep(interval_sec)


async def withdrawal_watcher(
    *,
    db: Database,
    cryptobot: CryptoBotAPI,
    bot: Bot,
    interval_sec: int = 10,
    auto_withdraw: bool = False,
) -> None:
    while True:
        try:
            items = await db.list_pending_withdrawals(limit=50)
            if not auto_withdraw:
                await asyncio.sleep(interval_sec)
                continue
            for item in items:
                user = await db.get_or_create_user(item.user_id)
                if user.cryptobot_id is None:
                    continue
                try:
                    transfer = await cryptobot.transfer(user_id=user.cryptobot_id, amount=item.net)
                    await db.set_withdrawal_status(item.withdrawal_id, status="done", cryptobot_transfer_id=transfer.transfer_id)
                    await db.deduct_frozen(item.user_id, item.amount)
                    with contextlib.suppress(Exception):
                        await bot.send_message(item.user_id, f"✅ Вывод выполнен: {item.net:.2f} USDT")
                except Exception:
                    continue
            await asyncio.sleep(interval_sec)
        except asyncio.CancelledError:
            raise
        except Exception:
            await asyncio.sleep(interval_sec)
