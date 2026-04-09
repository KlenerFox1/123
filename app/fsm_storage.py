from __future__ import annotations

from pathlib import Path

from aiogram.fsm.storage.memory import MemoryStorage


def create_fsm_storage(db_path: Path) -> MemoryStorage:
    return MemoryStorage()
