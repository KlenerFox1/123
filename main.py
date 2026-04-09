from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from dotenv import load_dotenv

from app.config import load_config
from app.db import Database
from app.fsm_storage import create_fsm_storage
from app.handlers import admin as admin_handlers
from app.handlers import user as user_handlers
from app.middlewares import AppContextMiddleware
from app.services.cryptobot import CryptoBotAPI
from app.services.payments import invoice_watcher, treasury_balance_watcher, withdrawal_watcher


async def main() -> None:
    import os
    # Загружаем .env вручную из папки с ботом
    env_file = Path(__file__).parent / ".env"
    print(f"🔍 Looking for .env at: {env_file}")
    print(f"🔍 Exists: {env_file.exists()}")
    
    if env_file.exists():
        with open(env_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    os.environ[key] = value
        print(f"✅ Loaded .env file: AUTO_WITHDRAW = {os.environ.get('AUTO_WITHDRAW')}")
    else:
        print("❌ .env file not found!")
    
    cfg = load_config()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    db = Database(Path("bot_database.db").resolve())
    await db.connect()

    cryptobot = CryptoBotAPI(cfg.cryptobot_api_key)
    
    proxy_url = os.getenv("PROXY_URL")
    if proxy_url:
        logging.info("Using proxy: %s", proxy_url)
        session = AiohttpSession(timeout=60, proxy=proxy_url)
    else:
        session = AiohttpSession(timeout=60)
    
    bot = Bot(token=cfg.bot_token, session=session, default=DefaultBotProperties(parse_mode="HTML"))
    dp = Dispatcher(storage=create_fsm_storage(Path("bot_database.db").resolve()))

    dp.update.middleware(AppContextMiddleware(db=db, cfg=cfg, cryptobot=cryptobot))
    dp.include_router(user_handlers.router)
    dp.include_router(admin_handlers.router)

    me = await bot.get_me()
    logging.info("Bot started: @%s (%s)", me.username, me.id)
    logging.info("Config: auto_withdraw=%s, watcher_interval=%d", cfg.auto_withdraw, cfg.watcher_interval_sec)
    print(f"🔧 DEBUG: auto_withdraw from config = {cfg.auto_withdraw}")
    print(f"🔧 DEBUG: type = {type(cfg.auto_withdraw)}")

    async def run_watchers():
        print(f"🔧 DEBUG in run_watchers: cfg.auto_withdraw = {cfg.auto_withdraw}")
        await asyncio.gather(
            invoice_watcher(db=db, cryptobot=cryptobot, bot=bot, interval_sec=cfg.watcher_interval_sec),
            treasury_balance_watcher(db=db, cryptobot=cryptobot, interval_sec=5),
            withdrawal_watcher(db=db, cryptobot=cryptobot, bot=bot, interval_sec=cfg.watcher_interval_sec, auto_withdraw=cfg.auto_withdraw),
        )

    async def run_polling():
        await dp.start_polling(bot)

    try:
        await asyncio.gather(run_watchers(), run_polling())
    finally:
        await cryptobot.aclose()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
