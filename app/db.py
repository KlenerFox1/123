from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import aiosqlite

from app.config import DEFAULT_ACCOUNT_TYPES


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class User:
    user_id: int
    balance: float
    bonus: float
    frozen: float
    cryptobot_id: int | None


@dataclass(frozen=True)
class Request:
    request_id: int
    user_id: int
    account_type: str
    phone: str
    status: str
    is_work: int
    is_vip: int
    admin_note: str | None
    code_value: str | None
    logs: str
    created_at: str


@dataclass(frozen=True)
class Withdrawal:
    withdrawal_id: int
    user_id: int
    amount: float
    net: float
    fee: float
    status: str
    cryptobot_transfer_id: str | None
    created_at: str


class Database:
    def __init__(self, db_path: str | Path) -> None:
        self._path = str(db_path)

    async def connect(self) -> None:
        async with aiosqlite.connect(self._path) as db:
            await db.execute("PRAGMA journal_mode=WAL;")
            await db.execute("PRAGMA foreign_keys=ON;")
            await db.commit()
        await self.ensure_schema()

    async def ensure_schema(self) -> None:
        async with aiosqlite.connect(self._path) as db:
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    balance REAL NOT NULL DEFAULT 0,
                    bonus REAL NOT NULL DEFAULT 0,
                    frozen REAL NOT NULL DEFAULT 0,
                    cryptobot_id INTEGER,
                    created_at TEXT NOT NULL
                )
                """
            )
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS requests (
                    request_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    account_type TEXT NOT NULL,
                    phone TEXT NOT NULL,
                    status TEXT NOT NULL,
                    is_work INTEGER NOT NULL DEFAULT 0,
                    is_vip INTEGER NOT NULL DEFAULT 0,
                    admin_note TEXT,
                    code_value TEXT,
                    logs TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(user_id) REFERENCES users(user_id)
                )
                """
            )
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS cryptobot_invoices (
                    invoice_id TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    amount REAL NOT NULL,
                    status TEXT NOT NULL,
                    credited INTEGER NOT NULL DEFAULT 0,
                    notify_sent INTEGER NOT NULL DEFAULT 0,
                    target TEXT NOT NULL DEFAULT 'user',
                    pay_url TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(user_id) REFERENCES users(user_id)
                )
                """
            )
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS withdrawals (
                    withdrawal_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    amount REAL NOT NULL,
                    net REAL NOT NULL,
                    fee REAL NOT NULL,
                    status TEXT NOT NULL,
                    cryptobot_transfer_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(user_id) REFERENCES users(user_id)
                )
                """
            )
            await db.commit()
        await self._ensure_defaults()

    async def _ensure_defaults(self) -> None:
        async with aiosqlite.connect(self._path) as db:
            try:
                await db.execute("ALTER TABLE cryptobot_invoices ADD COLUMN notify_sent INTEGER NOT NULL DEFAULT 0")
                await db.commit()
            except Exception:
                pass
        if await self.get_setting("account_types") is None:
            await self.set_setting("account_types", json.dumps(DEFAULT_ACCOUNT_TYPES, ensure_ascii=False))
        if await self.get_setting("min_withdraw") is None:
            await self.set_setting("min_withdraw", "1")
        if await self.get_setting("treasury_balance") is None:
            await self.set_setting("treasury_balance", "0")
        if await self.get_setting("maintenance_mode") is None:
            await self.set_setting("maintenance_mode", "0")

    async def _fetchone(self, db: aiosqlite.Connection, sql: str, params: tuple[Any, ...] = ()) -> tuple[Any, ...] | None:
        async with db.execute(sql, params) as cur:
            return await cur.fetchone()

    async def _fetchall(self, db: aiosqlite.Connection, sql: str, params: tuple[Any, ...] = ()) -> list[tuple[Any, ...]]:
        async with db.execute(sql, params) as cur:
            rows = await cur.fetchall()
        return list(rows)

    async def get_setting(self, key: str) -> str | None:
        async with aiosqlite.connect(self._path) as db:
            row = await self._fetchone(db, "SELECT value FROM settings WHERE key=?", (key,))
            return None if row is None else str(row[0])

    async def set_setting(self, key: str, value: str) -> None:
        now = _utcnow_iso()
        async with aiosqlite.connect(self._path) as db:
            await db.execute(
                """
                INSERT INTO settings(key, value, updated_at)
                VALUES(?,?,?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
                """,
                (key, value, now),
            )
            await db.commit()

    async def get_account_types_full(self) -> list[dict[str, Any]]:
        raw = await self.get_setting("account_types")
        if not raw:
            return []
        try:
            data = json.loads(raw)
            if isinstance(data, list):
                return [item for item in data if isinstance(item, dict) and item.get("name")]
        except Exception:
            return []
        return []

    async def set_account_types(self, items: list[dict[str, Any]]) -> None:
        await self.set_setting("account_types", json.dumps(items, ensure_ascii=False))

    async def get_account_type_price(self, name: str) -> float:
        for item in await self.get_account_types_full():
            if str(item.get("name")) == name:
                try:
                    return float(item.get("price") or 0)
                except Exception:
                    return 0.0
        return 0.0

    async def get_min_withdraw(self) -> float:
        raw = await self.get_setting("min_withdraw")
        try:
            return float(raw or 0)
        except Exception:
            return 0.0

    async def set_min_withdraw(self, value: float) -> None:
        await self.set_setting("min_withdraw", str(value))

    async def get_maintenance_mode(self) -> bool:
        raw = await self.get_setting("maintenance_mode")
        return str(raw or "0") in {"1", "true", "True"}

    async def toggle_maintenance_mode(self) -> bool:
        new_value = "0" if await self.get_maintenance_mode() else "1"
        await self.set_setting("maintenance_mode", new_value)
        return await self.get_maintenance_mode()

    async def get_treasury_balance(self) -> float:
        raw = await self.get_setting("treasury_balance")
        try:
            return float(raw or 0)
        except Exception:
            return 0.0

    async def add_treasury_balance(self, amount: float) -> None:
        current = await self.get_treasury_balance()
        await self.set_setting("treasury_balance", str(max(0.0, current + amount)))

    async def deduct_treasury_balance(self, amount: float) -> None:
        current = await self.get_treasury_balance()
        await self.set_setting("treasury_balance", str(max(0.0, current - amount)))

    async def get_or_create_user(self, user_id: int) -> User:
        async with aiosqlite.connect(self._path) as db:
            await db.execute(
                "INSERT OR IGNORE INTO users(user_id, balance, bonus, frozen, cryptobot_id, created_at) VALUES(?,?,?,?,?,?)",
                (user_id, 0.0, 0.0, 0.0, None, _utcnow_iso()),
            )
            await db.commit()
            row = await self._fetchone(db, "SELECT user_id, balance, bonus, frozen, cryptobot_id FROM users WHERE user_id=?", (user_id,))
        return User(
            user_id=int(row[0]),
            balance=float(row[1]),
            bonus=float(row[2]),
            frozen=float(row[3]),
            cryptobot_id=None if row[4] is None else int(row[4]),
        )

    async def list_users(self, limit: int = 50000) -> list[User]:
        async with aiosqlite.connect(self._path) as db:
            rows = await self._fetchall(db, "SELECT user_id, balance, bonus, frozen, cryptobot_id FROM users ORDER BY user_id ASC LIMIT ?", (limit,))
        return [User(int(r[0]), float(r[1]), float(r[2]), float(r[3]), None if r[4] is None else int(r[4])) for r in rows]

    async def count_users(self) -> int:
        async with aiosqlite.connect(self._path) as db:
            row = await self._fetchone(db, "SELECT COUNT(*) FROM users")
        return int(row[0]) if row else 0

    async def set_cryptobot_id(self, user_id: int, cryptobot_id: int) -> None:
        await self.get_or_create_user(user_id)
        async with aiosqlite.connect(self._path) as db:
            await db.execute("UPDATE users SET cryptobot_id=? WHERE user_id=?", (cryptobot_id, user_id))
            await db.commit()

    async def add_balance(self, user_id: int, amount: float) -> None:
        await self.get_or_create_user(user_id)
        async with aiosqlite.connect(self._path) as db:
            await db.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (amount, user_id))
            await db.commit()

    async def move_balance_to_frozen(self, user_id: int, amount: float) -> None:
        async with aiosqlite.connect(self._path) as db:
            await db.execute("UPDATE users SET balance = balance - ?, frozen = frozen + ? WHERE user_id=?", (amount, amount, user_id))
            await db.commit()

    async def move_frozen_to_balance(self, user_id: int, amount: float) -> None:
        async with aiosqlite.connect(self._path) as db:
            await db.execute("UPDATE users SET frozen = frozen - ?, balance = balance + ? WHERE user_id=?", (amount, amount, user_id))
            await db.commit()

    async def deduct_frozen(self, user_id: int, amount: float) -> None:
        async with aiosqlite.connect(self._path) as db:
            await db.execute("UPDATE users SET frozen = frozen - ? WHERE user_id=?", (amount, user_id))
            await db.commit()

    async def create_request(self, *, user_id: int, account_type: str, phone: str) -> int:
        await self.get_or_create_user(user_id)
        now = _utcnow_iso()
        async with aiosqlite.connect(self._path) as db:
            cur = await db.execute(
                "INSERT INTO requests(user_id, account_type, phone, status, is_work, is_vip, admin_note, code_value, logs, created_at) VALUES(?,?,?,?,0,0,NULL,NULL,?,?)",
                (user_id, account_type, phone, "pending", f"{now} created\n", now),
            )
            await db.commit()
            return int(cur.lastrowid)

    async def list_user_requests(self, user_id: int, limit: int = 20) -> list[Request]:
        async with aiosqlite.connect(self._path) as db:
            rows = await self._fetchall(db, "SELECT request_id, user_id, account_type, phone, status, is_work, is_vip, admin_note, code_value, logs, created_at FROM requests WHERE user_id=? ORDER BY request_id DESC LIMIT ?", (user_id, limit))
        return [self._row_to_request(r) for r in rows]

    async def list_pending_requests(self, limit: int = 50) -> list[Request]:
        async with aiosqlite.connect(self._path) as db:
            rows = await self._fetchall(db, "SELECT request_id, user_id, account_type, phone, status, is_work, is_vip, admin_note, code_value, logs, created_at FROM requests WHERE status IN ('pending','code_requested','code_received','taken') ORDER BY request_id ASC LIMIT ?", (limit,))
        return [self._row_to_request(r) for r in rows]

    async def get_request(self, request_id: int) -> Request | None:
        async with aiosqlite.connect(self._path) as db:
            row = await self._fetchone(db, "SELECT request_id, user_id, account_type, phone, status, is_work, is_vip, admin_note, code_value, logs, created_at FROM requests WHERE request_id=?", (request_id,))
        return None if row is None else self._row_to_request(row)

    async def set_request_status(self, request_id: int, status: str) -> None:
        now = _utcnow_iso()
        async with aiosqlite.connect(self._path) as db:
            await db.execute("UPDATE requests SET status=? WHERE request_id=?", (status, request_id))
            await db.execute("UPDATE requests SET logs = logs || ? WHERE request_id=?", (f"{now} status={status}\n", request_id))
            await db.commit()

    async def append_request_log(self, request_id: int, line: str) -> None:
        now = _utcnow_iso()
        async with aiosqlite.connect(self._path) as db:
            await db.execute("UPDATE requests SET logs = logs || ? WHERE request_id=?", (f"{now} {line}\n", request_id))
            await db.commit()

    async def set_admin_note(self, request_id: int, note: str) -> None:
        async with aiosqlite.connect(self._path) as db:
            await db.execute("UPDATE requests SET admin_note=? WHERE request_id=?", (note, request_id))
            await db.commit()

    async def set_request_code(self, request_id: int, code: str) -> None:
        async with aiosqlite.connect(self._path) as db:
            await db.execute("UPDATE requests SET code_value=? WHERE request_id=?", (code, request_id))
            await db.commit()
        await self.append_request_log(request_id, f"code={code}")

    async def toggle_request_flag(self, request_id: int, flag: str) -> Request | None:
        if flag not in {"is_work", "is_vip"}:
            raise ValueError("Недопустимый флаг")
        async with aiosqlite.connect(self._path) as db:
            await db.execute(f"UPDATE requests SET {flag} = CASE WHEN {flag}=1 THEN 0 ELSE 1 END WHERE request_id=?", (request_id,))
            await db.commit()
        return await self.get_request(request_id)

    async def create_invoice(self, *, invoice_id: str, user_id: int, amount: float, status: str, pay_url: str | None, target: str = "user") -> None:
        now = _utcnow_iso()
        await self.get_or_create_user(user_id)
        async with aiosqlite.connect(self._path) as db:
            await db.execute(
                "INSERT OR IGNORE INTO cryptobot_invoices(invoice_id, user_id, amount, status, credited, target, pay_url, created_at, updated_at) VALUES(?,?,?,?,0,?,?,?,?)",
                (invoice_id, user_id, amount, status, target, pay_url, now, now),
            )
            await db.commit()

    async def list_uncredited_invoices(self, limit: int = 100) -> list[dict[str, Any]]:
        async with aiosqlite.connect(self._path) as db:
            rows = await self._fetchall(db, "SELECT invoice_id, user_id, amount, status, credited, notify_sent, target FROM cryptobot_invoices WHERE credited=0 ORDER BY created_at ASC LIMIT ?", (limit,))
        return [
            {
                "invoice_id": str(r[0]),
                "user_id": int(r[1]),
                "amount": float(r[2]),
                "status": str(r[3]),
                "credited": int(r[4]),
                "notify_sent": int(r[5]),
                "target": str(r[6]),
            }
            for r in rows
        ]

    async def update_invoice_status(self, invoice_id: str, status: str) -> None:
        async with aiosqlite.connect(self._path) as db:
            await db.execute("UPDATE cryptobot_invoices SET status=?, updated_at=? WHERE invoice_id=?", (status, _utcnow_iso(), invoice_id))
            await db.commit()

    async def credit_invoice_once(self, invoice_id: str) -> bool:
        async with aiosqlite.connect(self._path) as db:
            await db.execute("BEGIN IMMEDIATE")
            row = await self._fetchone(db, "SELECT user_id, amount, credited, target FROM cryptobot_invoices WHERE invoice_id=?", (invoice_id,))
            if row is None or int(row[2]) == 1:
                await db.execute("ROLLBACK")
                return False
            user_id, amount, _, target = int(row[0]), float(row[1]), int(row[2]), str(row[3])
            await db.execute("UPDATE cryptobot_invoices SET credited=1, status='paid', updated_at=? WHERE invoice_id=?", (_utcnow_iso(), invoice_id))
            if target == "treasury":
                settings_row = await self._fetchone(db, "SELECT value FROM settings WHERE key='treasury_balance'")
                current = float(settings_row[0]) if settings_row and settings_row[0] is not None else 0.0
                await db.execute(
                    "INSERT INTO settings(key, value, updated_at) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
                    ("treasury_balance", str(current + amount), _utcnow_iso()),
                )
            else:
                await db.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (amount, user_id))
            await db.commit()
            return True

    async def list_paid_treasury_invoices_without_notify(self, limit: int = 50) -> list[dict[str, Any]]:
        async with aiosqlite.connect(self._path) as db:
            rows = await self._fetchall(
                db,
                "SELECT invoice_id, amount FROM cryptobot_invoices WHERE target='treasury' AND credited=1 AND notify_sent=0 ORDER BY updated_at ASC LIMIT ?",
                (limit,),
            )
        return [{"invoice_id": str(r[0]), "amount": float(r[1])} for r in rows]

    async def mark_invoice_notify_sent(self, invoice_id: str) -> None:
        async with aiosqlite.connect(self._path) as db:
            await db.execute("UPDATE cryptobot_invoices SET notify_sent=1, updated_at=? WHERE invoice_id=?", (_utcnow_iso(), invoice_id))
            await db.commit()

    async def create_withdrawal(self, *, user_id: int, amount: float, fee: float) -> int:
        net = max(0.0, amount - fee)
        now = _utcnow_iso()
        async with aiosqlite.connect(self._path) as db:
            cur = await db.execute(
                "INSERT INTO withdrawals(user_id, amount, net, fee, status, cryptobot_transfer_id, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?)",
                (user_id, amount, net, fee, "pending", None, now, now),
            )
            await db.commit()
            return int(cur.lastrowid)

    async def list_pending_withdrawals(self, limit: int = 50) -> list[Withdrawal]:
        async with aiosqlite.connect(self._path) as db:
            rows = await self._fetchall(db, "SELECT withdrawal_id, user_id, amount, net, fee, status, cryptobot_transfer_id, created_at FROM withdrawals WHERE status='pending' ORDER BY withdrawal_id ASC LIMIT ?", (limit,))
        return [self._row_to_withdrawal(r) for r in rows]

    async def set_withdrawal_status(self, withdrawal_id: int, *, status: str, cryptobot_transfer_id: str | None = None) -> None:
        async with aiosqlite.connect(self._path) as db:
            await db.execute("UPDATE withdrawals SET status=?, cryptobot_transfer_id=?, updated_at=? WHERE withdrawal_id=?", (status, cryptobot_transfer_id, _utcnow_iso(), withdrawal_id))
            await db.commit()

    async def export_withdrawals_csv_rows(self) -> list[list[str]]:
        async with aiosqlite.connect(self._path) as db:
            rows = await self._fetchall(db, "SELECT withdrawal_id, user_id, amount, net, fee, status, cryptobot_transfer_id, created_at FROM withdrawals ORDER BY withdrawal_id DESC")
        result = [["withdrawal_id", "user_id", "amount", "net", "fee", "status", "cryptobot_transfer_id", "created_at"]]
        for row in rows:
            result.append([str(x) if x is not None else "" for x in row])
        return result

    async def request_stats(self) -> dict[str, int]:
        async with aiosqlite.connect(self._path) as db:
            rows = await self._fetchall(db, "SELECT status, COUNT(*) FROM requests GROUP BY status")
        return {str(r[0]): int(r[1]) for r in rows}

    def _row_to_request(self, row: Iterable[Any]) -> Request:
        values = list(row)
        return Request(
            request_id=int(values[0]),
            user_id=int(values[1]),
            account_type=str(values[2]),
            phone=str(values[3]),
            status=str(values[4]),
            is_work=int(values[5]),
            is_vip=int(values[6]),
            admin_note=None if values[7] is None else str(values[7]),
            code_value=None if values[8] is None else str(values[8]),
            logs=str(values[9] or ""),
            created_at=str(values[10]),
        )

    def _row_to_withdrawal(self, row: Iterable[Any]) -> Withdrawal:
        values = list(row)
        return Withdrawal(
            withdrawal_id=int(values[0]),
            user_id=int(values[1]),
            amount=float(values[2]),
            net=float(values[3]),
            fee=float(values[4]),
            status=str(values[5]),
            cryptobot_transfer_id=None if values[6] is None else str(values[6]),
            created_at=str(values[7]),
        )
