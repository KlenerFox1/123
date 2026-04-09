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
    import logging
    log = logging.getLogger("withdrawal_watcher")
    log.info("Withdrawal watcher started: auto_withdraw=%s", auto_withdraw)
    
    while True:
        try:
            items = await db.list_pending_withdrawals(limit=50)
            if items:
                log.info("Found %d pending withdrawals", len(items))
            if not auto_withdraw:
                log.debug("auto_withdraw=False, skipping")
                await asyncio.sleep(interval_sec)
                continue
            for item in items:
                user = await db.get_or_create_user(item.user_id)
                log.info("Checking withdrawal %d: user_id=%d, cryptobot_id=%s", item.withdrawal_id, item.user_id, user.cryptobot_id)
                if user.cryptobot_id is None:
                    log.warning("User %d has NO cryptobot_id! User must set it via /wd menu. Skipping withdrawal %d", item.user_id, item.withdrawal_id)
                    await bot.send_message(item.user_id, "⚠️ Для вывода средств необходимо указать CryptoBot ID!\n\nПерейдите в меню: 💸 Вывод")
                    continue
                try:
                    log.info("Processing withdrawal %d: user=%d, amount=%.2f, cryptobot_id=%d", item.withdrawal_id, item.user_id, item.net, user.cryptobot_id)
                    transfer = await cryptobot.transfer(user_id=user.cryptobot_id, amount=item.net)
                    await db.set_withdrawal_status(item.withdrawal_id, status="done", cryptobot_transfer_id=transfer.transfer_id)
                    await db.deduct_frozen(item.user_id, item.amount)
                    log.info("Withdrawal %d completed: transfer_id=%s", item.withdrawal_id, transfer.transfer_id)
                    with contextlib.suppress(Exception):
                        await bot.send_message(item.user_id, f"✅ Вывод выполнен: {item.net:.2f} USDT\n\nID перевода: {transfer.transfer_id}")
                except Exception as e:
                    log.error("Withdrawal %d failed: %s", item.withdrawal_id, e)
                    await bot.send_message(item.user_id, f"❌ Ошибка вывода: {e}")
                    continue
            await asyncio.sleep(interval_sec)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.error("Watcher error: %s", e)
            await asyncio.sleep(interval_sec)
