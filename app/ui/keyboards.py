from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.db import Request


SERVICE_EMOJI: dict[str, str] = {
    "Galaxy": "🟩",
    "Hornet": "🟨",
    "Mamba": "🔵",
    "SunLight": "🟪",
    "Tabor": "🟤",
    "Teamo": "🟧",
    "Telegram": "🟢",
    "VK": "🟠",
    "WhatsApp": "🟡",
    "ДругВокруг": "🟦",
    "Золотое Яблоко": "⚫",
    "Max": "🔴",
}


def _rows(buttons: list[InlineKeyboardButton], width: int = 2) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for i in range(0, len(buttons), width):
        rows.append(buttons[i : i + width])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def user_main_menu() -> InlineKeyboardMarkup:
    return _rows(
        [
            InlineKeyboardButton(text="📲 Добавить номер", callback_data="u:add"),
            InlineKeyboardButton(text="🛰 Сервис", callback_data="u:svc"),
            InlineKeyboardButton(text="📋 Мои номера", callback_data="u:reqs"),
            InlineKeyboardButton(text="👤 Профиль", callback_data="u:pf"),
            InlineKeyboardButton(text="💸 Вывод", callback_data="u:wd"),
            InlineKeyboardButton(text="❓ Помощь", callback_data="u:hp"),
        ]
    )


def service_menu(items: list[dict[str, object]]) -> InlineKeyboardMarkup:
    buttons: list[InlineKeyboardButton] = []
    for item in items:
        name = str(item.get("name") or "")
        emoji = SERVICE_EMOJI.get(name, "⚪")
        buttons.append(InlineKeyboardButton(text=f"{emoji} {name}", callback_data=f"u:sv:{name}"))
    buttons.append(InlineKeyboardButton(text="⬅️ Назад", callback_data="u:home"))
    return _rows(buttons)


def back_home() -> InlineKeyboardMarkup:
    return _rows([InlineKeyboardButton(text="⬅️ Назад", callback_data="u:home")], width=1)


def my_requests_menu(items: list[Request]) -> InlineKeyboardMarkup:
    buttons = [InlineKeyboardButton(text=f"📦 #{r.request_id} • {r.account_type}", callback_data=f"u:r:{r.request_id}") for r in items]
    buttons.append(InlineKeyboardButton(text="⬅️ Назад", callback_data="u:home"))
    return _rows(buttons, width=1)


def deposit_menu(invoice_id: str, pay_url: str | None) -> InlineKeyboardMarkup:
    buttons: list[InlineKeyboardButton] = []
    if pay_url:
        buttons.append(InlineKeyboardButton(text="💳 Оплатить", url=pay_url))
    buttons.append(InlineKeyboardButton(text="🔎 Проверить", callback_data=f"u:dep:{invoice_id}"))
    buttons.append(InlineKeyboardButton(text="⬅️ Назад", callback_data="u:pf"))
    return _rows(buttons, width=1)


def admin_request_card(request_id: int, *, is_work: int, is_vip: int, has_code: bool) -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton(text="✅ Одобрить", callback_data=f"a:r:{request_id}:ok"),
        InlineKeyboardButton(text="🙅 Не одобрить", callback_data=f"a:r:{request_id}:take"),
        InlineKeyboardButton(text="📨 Запросить код", callback_data=f"a:r:{request_id}:ask"),
        InlineKeyboardButton(text="❌ Отклонить", callback_data=f"a:r:{request_id}:rej"),
        InlineKeyboardButton(text=("🧰 Ворк ✅" if is_work else "🧰 Ворк"), callback_data=f"a:r:{request_id}:wk"),
        InlineKeyboardButton(text=("💎 VIP ✅" if is_vip else "💎 VIP"), callback_data=f"a:r:{request_id}:vip"),
    ]
    if has_code:
        buttons.append(InlineKeyboardButton(text="👁 Показать код", callback_data=f"a:r:{request_id}:code"))
    buttons.append(InlineKeyboardButton(text="📝 Заметка", callback_data=f"a:r:{request_id}:note"))
    buttons.append(InlineKeyboardButton(text="📜 Лог", callback_data=f"a:r:{request_id}:log"))
    buttons.append(InlineKeyboardButton(text="⬅️ Назад", callback_data="a:reqs"))
    return _rows(buttons)


def admin_menu() -> InlineKeyboardMarkup:
    return _rows(
        [
            InlineKeyboardButton(text="🧾 Тип аккаунтов", callback_data="a:types"),
            InlineKeyboardButton(text="⚙️ Настройки бота", callback_data="a:set"),
            InlineKeyboardButton(text="👥 Пользователи", callback_data="a:users"),
            InlineKeyboardButton(text="💾 Бэкап БД", callback_data="a:backup"),
            InlineKeyboardButton(text="📣 Рассылка", callback_data="a:broadcast"),
            InlineKeyboardButton(text="➕ Добавить баланс", callback_data="a:topup"),
            InlineKeyboardButton(text="🏦 Пополнить казну", callback_data="a:treasury"),
            InlineKeyboardButton(text="📦 Заявки", callback_data="a:reqs"),
        ]
    )


def admin_settings_menu() -> InlineKeyboardMarkup:
    return _rows(
        [
            InlineKeyboardButton(text="💸 min_withdraw", callback_data="a:set:minw"),
            InlineKeyboardButton(text="🛠 Тех. перерыв", callback_data="a:set:maint"),
            InlineKeyboardButton(text="⬅️ Назад", callback_data="a:home"),
        ],
        width=1,
    )


def admin_types_menu(items: list[dict[str, object]]) -> InlineKeyboardMarkup:
    buttons = [InlineKeyboardButton(text=f"💰 {item['name']} — {float(item['price']):.2f}", callback_data=f"a:type:{item['name']}") for item in items]
    buttons.append(InlineKeyboardButton(text="⬅️ Назад", callback_data="a:home"))
    return _rows(buttons, width=1)


def admin_requests_menu(items: list[Request]) -> InlineKeyboardMarkup:
    buttons = [InlineKeyboardButton(text=f"📦 #{r.request_id} • {r.account_type} • {r.status}", callback_data=f"a:r:{r.request_id}") for r in items]
    buttons.append(InlineKeyboardButton(text="⬅️ Назад", callback_data="a:home"))
    return _rows(buttons, width=1)


def admin_cancel_menu(cancel_cb: str, back_cb: str = "a:home") -> InlineKeyboardMarkup:
    return _rows(
        [
            InlineKeyboardButton(text="❌ Отмена", callback_data=cancel_cb),
            InlineKeyboardButton(text="⬅️ Назад", callback_data=back_cb),
        ]
    )
