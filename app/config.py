from __future__ import annotations

from dataclasses import dataclass
import os


DEFAULT_ACCOUNT_TYPES: list[dict[str, float | str]] = [
    {"name": "Galaxy", "price": 0.7},
    {"name": "Hornet", "price": 0.7},
    {"name": "Mamba", "price": 0.7},
    {"name": "SunLight", "price": 0.7},
    {"name": "Tabor", "price": 0.7},
    {"name": "Teamo", "price": 0.7},
    {"name": "Telegram", "price": 0.7},
    {"name": "VK", "price": 0.7},
    {"name": "WhatsApp", "price": 0.7},
    {"name": "ДругВокруг", "price": 0.7},
    {"name": "Золотое Яблоко", "price": 0.7},
    {"name": "Max", "price": 0.7},
]


def _env(name: str, default: str | None = None) -> str:
    value = os.getenv(name, default)
    if value is None or value == "":
        raise RuntimeError(f"Не задана переменная окружения: {name}")
    return value


def _env_int(name: str, default: int | None = None) -> int:
    value = os.getenv(name)
    if value is None or value == "":
        if default is None:
            raise RuntimeError(f"Не задана переменная окружения: {name}")
        return default
    return int(value)


def _parse_int_list(raw: str) -> list[int]:
    result: list[int] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        result.append(int(part))
    return result


@dataclass(frozen=True)
class Config:
    bot_token: str
    owner_admin_id: int
    admin_ids: list[int]
    cryptobot_api_key: str
    auto_withdraw: bool
    watcher_interval_sec: int

    @property
    def all_admin_ids(self) -> set[int]:
        return {self.owner_admin_id, *self.admin_ids}


def load_config() -> Config:
    import os
    auto_wd = os.getenv("AUTO_WITHDRAW", "0")
    print(f"🔧 DEBUG config.py: AUTO_WITHDRAW env = '{auto_wd}'")
    print(f"🔧 DEBUG config.py: in set = {auto_wd in {'1', 'true', 'True'}}")
    
    return Config(
        bot_token=_env("BOT_TOKEN"),
        owner_admin_id=_env_int("OWNER_ADMIN_ID"),
        admin_ids=_parse_int_list(os.getenv("ADMIN_IDS", "")),
        cryptobot_api_key=_env("CRYPTOBOT_API_KEY"),
        auto_withdraw=auto_wd in {"1", "true", "True"},
        watcher_interval_sec=_env_int("WATCHER_INTERVAL_SEC", 10),
    )


def is_admin(user_id: int, cfg: Config) -> bool:
    return user_id in cfg.all_admin_ids
