from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from dotenv import load_dotenv

from app.config import load_config
from app.db import Database
from app.fsm_storage import SQLiteFSMStorage
from app.handlers import admin as admin_handlers
from app.handlers import user as user_handlers
from app.middlewares import AppContextMiddleware
from app.services.cryptobot import CryptoBotAPI
from app.services.payments import invoice_watcher, treasury_balance_watcher, withdrawal_watcher


async def main() -> None:
    env_path = Path(__file__).with_name(".env")
    load_dotenv(dotenv_path=env_path, override=True, encoding="utf-8")
    load_dotenv(override=True, encoding="utf-8")

    cfg = load_config()
    logging.basicConfig(level=logging.INFO)

    db = Database(Path("bot_database.db").resolve())
    await db.connect()

    cryptobot = CryptoBotAPI(cfg.cryptobot_api_key)
    session = AiohttpSession(timeout=60)
    bot = Bot(token=cfg.bot_token, session=session, default=DefaultBotProperties(parse_mode="HTML"))
    dp = Dispatcher(storage=SQLiteFSMStorage(Path("bot_database.db").resolve()))

    dp.update.middleware(AppContextMiddleware(db=db, cfg=cfg, cryptobot=cryptobot))
    dp.include_router(user_handlers.router)
    dp.include_router(admin_handlers.router)

    me = await bot.get_me()
    logging.info("Bot started: @%s (%s)", me.username, me.id)
    logging.info("Config: auto_withdraw=%s, watcher_interval=%d", cfg.auto_withdraw, cfg.watcher_interval_sec)

    watcher_tasks: list[asyncio.Task] = [
        asyncio.create_task(invoice_watcher(db=db, cryptobot=cryptobot, bot=bot, interval_sec=cfg.watcher_interval_sec)),
        asyncio.create_task(treasury_balance_watcher(db=db, cryptobot=cryptobot, interval_sec=5)),
        asyncio.create_task(
            withdrawal_watcher(
                db=db,
                cryptobot=cryptobot,
                bot=bot,
                interval_sec=cfg.watcher_interval_sec,
                auto_withdraw=cfg.auto_withdraw,
            )
        ),
    ]

    try:
        await dp.start_polling(bot)
    finally:
        for task in watcher_tasks:
            task.cancel()
        await asyncio.gather(*watcher_tasks, return_exceptions=True)
        await cryptobot.aclose()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
