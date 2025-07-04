# src/keyboards.py
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from .config import AVAILABLE_EXCHANGES

def get_main_menu_keyboard() -> InlineKeyboardMarkup:
    """Головне меню під повідомленням."""
    keyboard = [
        [
            InlineKeyboardButton("🔄 Оновити", callback_data="refresh"),
            InlineKeyboardButton("⚙️ Налаштування", callback_data="settings_menu"),
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_settings_menu_keyboard(settings: dict) -> InlineKeyboardMarkup:
    """Меню налаштувань."""
    bot_status = "🟢 Бот ON" if settings['enabled'] else "🔴 Бот OFF"
    keyboard = [
        [InlineKeyboardButton("🌐 Біржі", callback_data="settings_exchanges")],
        [InlineKeyboardButton(f"📊 Фандінг: > {settings['threshold']}%", callback_data="settings_threshold")],
        [InlineKeyboardButton(f"⏳ Час оновлення: {settings['interval']} хв", callback_data="settings_interval")],
        [InlineKeyboardButton(bot_status, callback_data="toggle_bot_status")],
        [InlineKeyboardButton("❌ Закрити", callback_data="close_settings")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_exchange_selection_keyboard(selected_exchanges: list) -> InlineKeyboardMarkup:
    """Меню вибору бірж."""
    buttons = []
    row = []
    for name in AVAILABLE_EXCHANGES.keys():
        text = f"✅ {name}" if name in selected_exchanges else f"☑️ {name}"
        row.append(InlineKeyboardButton(text, callback_data=f"toggle_exchange_{name}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    
    buttons.append([InlineKeyboardButton("↩️ Назад", callback_data="settings_menu")])
    return InlineKeyboardMarkup(buttons)

# ... Тут можна додати інші клавіатури, наприклад, для вибору інтервалу
def get_interval_selection_keyboard() -> InlineKeyboardMarkup:
    keyboard = [
        [
            InlineKeyboardButton("5 хв", callback_data="set_interval_5"),
            InlineKeyboardButton("15 хв", callback_data="set_interval_15"),
            InlineKeyboardButton("30 хв", callback_data="set_interval_30"),
        ],
        [
            InlineKeyboardButton("1 год", callback_data="set_interval_60"),
            InlineKeyboardButton("4 год", callback_data="set_interval_240"),
            InlineKeyboardButton("8 год", callback_data="set_interval_480"),
        ],
        [InlineKeyboardButton("↩️ Назад", callback_data="settings_menu")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_back_to_settings_keyboard() -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton("↩️ Назад", callback_data="settings_menu")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_close_button() -> InlineKeyboardMarkup:
     keyboard = [
        [InlineKeyboardButton("❌ Закрити", callback_data="delete_message")]
    ]
     return InlineKeyboardMarkup(keyboard)