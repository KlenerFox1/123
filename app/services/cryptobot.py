from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx


class CryptoBotError(RuntimeError):
    pass


@dataclass(frozen=True)
class CryptoInvoice:
    invoice_id: str
    status: str
    pay_url: str | None
    amount: float


@dataclass(frozen=True)
class CryptoTransfer:
    transfer_id: str
    status: str


class CryptoBotAPI:
    def __init__(self, api_key: str, *, timeout_sec: float = 20.0) -> None:
        if not api_key:
            raise RuntimeError("CRYPTOBOT_API_KEY пустой")
        self._client = httpx.AsyncClient(
            base_url="https://pay.crypt.bot/api",
            timeout=timeout_sec,
            headers={"Crypto-Pay-API-Token": api_key},
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _call(self, method: str, payload: dict[str, Any] | None = None) -> Any:
        response = await self._client.post(method, json=payload or {})
        data = response.json()
        if response.status_code != 200:
            raise CryptoBotError(f"HTTP {response.status_code}: {data}")
        if not isinstance(data, dict) or data.get("ok") is not True:
            raise CryptoBotError(f"API error: {data}")
        return data.get("result")

    async def create_invoice(self, *, amount: float, asset: str = "USDT", description: str = "Deposit") -> CryptoInvoice:
        result = await self._call("/createInvoice", {"amount": str(amount), "asset": asset, "description": description})
        if not isinstance(result, dict):
            raise CryptoBotError("Некорректный ответ createInvoice")
        return CryptoInvoice(
            invoice_id=str(result.get("invoice_id")),
            status=str(result.get("status", "unknown")),
            pay_url=str(result.get("pay_url")) if result.get("pay_url") else None,
            amount=float(result.get("amount") or amount),
        )

    async def get_invoices(self, *, invoice_ids: list[str]) -> list[CryptoInvoice]:
        if not invoice_ids:
            return []
        result = await self._call("/getInvoices", {"invoice_ids": invoice_ids})
        if not isinstance(result, dict):
            raise CryptoBotError("Некорректный ответ getInvoices")
        items = result.get("items") or []
        response: list[CryptoInvoice] = []
        if isinstance(items, list):
            for item in items:
                if not isinstance(item, dict):
                    continue
                response.append(
                    CryptoInvoice(
                        invoice_id=str(item.get("invoice_id")),
                        status=str(item.get("status", "unknown")),
                        pay_url=str(item.get("pay_url")) if item.get("pay_url") else None,
                        amount=float(item.get("amount") or 0),
                    )
                )
        return response

    async def transfer(self, *, user_id: int, amount: float, asset: str = "USDT", comment: str = "Withdrawal", spend_id: str | None = None) -> CryptoTransfer:
        import uuid
        if spend_id is None:
            spend_id = str(uuid.uuid4())
        result = await self._call("/transfer", {"user_id": user_id, "asset": asset, "amount": str(amount), "comment": comment, "spend_id": spend_id})
        if not isinstance(result, dict):
            raise CryptoBotError("Некорректный ответ transfer")
        return CryptoTransfer(
            transfer_id=str(result.get("transfer_id") or result.get("id") or ""),
            status=str(result.get("status", "unknown")),
        )

    async def get_balance(self) -> list[dict[str, Any]]:
        result = await self._call("/getBalance", {})
        if not isinstance(result, list):
            raise CryptoBotError("Некорректный ответ getBalance")
        return [item for item in result if isinstance(item, dict)]

    async def get_asset_balance(self, asset: str = "USDT") -> float:
        items = await self.get_balance()
        for item in items:
            if str(item.get("currency_code") or item.get("asset") or "") != asset:
                continue
            try:
                return float(item.get("available") or item.get("available_balance") or item.get("balance") or 0)
            except Exception:
                return 0.0
        return 0.0
