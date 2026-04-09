from __future__ import annotations

from pathlib import Path

from aiogram.fsm.storage.memory import MemoryStorage


class SQLiteFSMStorage(MemoryStorage):
    def __init__(self, db_path: Path) -> None:
        super().__init__()
        self.db_path = db_path
