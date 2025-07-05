# run_bot.py (ПОВНА ФУНКЦІОНАЛЬНА ВЕРСІЯ)

import os
import logging
import time
import html
import pandas as pd
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters, ConversationHandler
from telegram.constants import ParseMode

# --- Імпорти з нашого проекту ---
from src.services.funding_service import get_all_funding_data_sequential, get_funding_for_ticker_sequential
from src.config import AVAILABLE_EXCHANGES, DEFAULT_SETTINGS, EXCHANGE_URL_TEMPLATES
from src.constants import SET_THRESHOLD_STATE
# Примітка: Ми більше не використовуємо файли formatters, keyboards, user_manager, бо вся логіка тепер тут.

# --- Налаштування ---
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# --- Робота з налаштуваннями користувача (в пам'яті) ---
_user_settings_cache = {}
def get_user_settings(chat_id: int) -> dict:
    chat_id_str = str(chat_id)
    if chat_id_str not in _user_settings_cache:
        _user_settings_cache[chat_id_str] = DEFAULT_SETTINGS.copy()
    return _user_settings_cache[chat_id_str]

def update_user_setting(chat_id: int, key: str, value):
    chat_id_str = str(chat_id)
    settings = get_user_settings(chat_id)
    settings[key] = value

# --- Клавіатури ---
def get_main_menu_keyboard():
    keyboard = [[InlineKeyboardButton("🔄 Оновити", callback_data="refresh"), InlineKeyboardButton("⚙️ Налаштування", callback_data="settings_menu")]]
    return InlineKeyboardMarkup(keyboard)

def get_settings_menu_keyboard(settings: dict):
    bot_status_text = "🟢 Бот ON" if settings.get('enabled', True) else "🔴 Бот OFF"
    keyboard = [
        [InlineKeyboardButton("🌐 Біржі", callback_data="settings_exchanges")],
        [InlineKeyboardButton(f"📊 Фандінг: > {settings['threshold']}%", callback_data="settings_threshold")],
        [InlineKeyboardButton(bot_status_text, callback_data="toggle_bot_status")],
        [InlineKeyboardButton("❌ Закрити", callback_data="close_settings")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_exchange_selection_keyboard(selected_exchanges: list):
    buttons = []
    row = []
    for name in AVAILABLE_EXCHANGES.keys():
        text = f"✅ {name}" if name in selected_exchanges else f"☑️ {name}"
        row.append(InlineKeyboardButton(text, callback_data=f"toggle_exchange_{name}"))
        if len(row) == 2: buttons.append(row); row = []
    if row: buttons.append(row)
    buttons.append([InlineKeyboardButton("↩️ Назад", callback_data="settings_menu")])
    return InlineKeyboardMarkup(buttons)

def get_back_to_settings_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Назад", callback_data="settings_menu")]])

# --- Форматувальники ---
def format_funding_update(df: pd.DataFrame, threshold: float) -> str:
    if df.empty: return "Не знайдено даних по фандінгу для обраних бірж."
    filtered_df = df[abs(df['rate']) >= threshold].sort_values(by='rate', ascending=False)
    if filtered_df.empty: return f"🟢 Немає монет з фандінгом вище <b>{threshold}%</b> або нижче <b>-{threshold}%</b>."
    header = f"<b>💎 Фандінг вище {threshold}%</b>\n\n"
    lines = [f"{'🟢' if row['rate'] > 0 else '🔴'} <code>{row['symbol']:<8}</code>— <b>{row['rate']: >-7.4f}%</b> — {row['exchange']}" for _, row in filtered_df.iterrows()]
    return header + "\n".join(lines)

def format_ticker_info(df: pd.DataFrame, ticker: str) -> str:
    if df.empty: return f"Не знайдено даних для <b>{html.escape(ticker)}</b>."
    header = f"<b>🪙 Фандінг для {html.escape(ticker.upper())}</b>\n\n"
    lines = [f"{'🟢' if row['rate'] > 0 else '🔴'} <b>{row['rate']: >-7.4f}%</b> — {row['exchange']}" for _, row in df.iterrows()]
    return header + "\n".join(lines)

# --- Обробники ---
async def start_or_refresh(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = getattr(update, 'callback_query', None)
    if query: await query.answer()
    
    chat_id = update.effective_chat.id
    logger.info(f"Отримано запит /start або refresh для чату {chat_id}")
    
    settings = get_user_settings(chat_id)
    if not settings.get('enabled', True) and not query:
        await context.bot.send_message(chat_id, "Бот вимкнений. Увімкніть його в налаштуваннях.")
        return

    message_to_edit = await context.bot.send_message(chat_id, "Починаю пошук... Це може зайняти до хвилини.")
    
    try:
        df = get_all_funding_data_sequential(settings['exchanges'])
        message_text = format_funding_update(df, settings['threshold'])
        await message_to_edit.edit_text(text=message_text, parse_mode=ParseMode.HTML, reply_markup=get_main_menu_keyboard(), disable_web_page_preview=True)
    except Exception as e:
        logger.error(f"Помилка в start_or_refresh: {e}", exc_info=True)
        await message_to_edit.edit_text("😔 Виникла помилка під час обробки.")

async def settings_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    settings = get_user_settings(query.effective_chat.id)
    await query.edit_message_text("⚙️ <b>Налаштування</b>", parse_mode=ParseMode.HTML, reply_markup=get_settings_menu_keyboard(settings))

async def close_settings_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.message.delete()
    await start_or_refresh(query, context)

async def exchange_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    settings = get_user_settings(query.effective_chat.id)
    await query.edit_message_text("🌐 <b>Вибір бірж</b>", parse_mode=ParseMode.HTML, reply_markup=get_exchange_selection_keyboard(settings['exchanges']))

async def toggle_exchange_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    exchange_name = query.data.split('_')[-1]
    settings = get_user_settings(query.effective_chat.id)
    if exchange_name in settings['exchanges']: settings['exchanges'].remove(exchange_name)
    else: settings['exchanges'].append(exchange_name)
    update_user_setting(query.effective_chat.id, 'exchanges', settings['exchanges'])
    await query.edit_message_reply_markup(reply_markup=get_exchange_selection_keyboard(settings['exchanges']))
    await query.answer(f"Біржа {exchange_name} оновлена")

async def toggle_bot_status_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    settings = get_user_settings(query.effective_chat.id)
    new_status = not settings.get('enabled', True)
    update_user_setting(query.effective_chat.id, 'enabled', new_status)
    await query.answer(f"Бот тепер {'УВІМКНЕНИЙ' if new_status else 'ВИМКНЕНИЙ'}")
    await query.edit_message_reply_markup(reply_markup=get_settings_menu_keyboard(get_user_settings(query.effective_chat.id)))

async def set_threshold_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    settings = get_user_settings(query.effective_chat.id)
    text = f"Поточний поріг: <b>{settings['threshold']}%</b>.\n\nНадішліть нове значення (напр., <code>0.5</code>)."
    await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=get_back_to_settings_keyboard())
    return SET_THRESHOLD_STATE

async def set_threshold_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    try:
        new_threshold = float(update.message.text.strip())
        if 0 < new_threshold < 100:
            update_user_setting(chat_id, 'threshold', new_threshold)
            await update.message.reply_text(f"✅ Новий поріг: <b>{new_threshold}%</b>", parse_mode=ParseMode.HTML)
        else: await update.message.reply_text("Введіть число від 0 до 100.")
    except (ValueError, TypeError): await update.message.reply_text("Некоректне значення. Введіть число.")
    await context.bot.delete_message(chat_id, update.message.message_id - 1)
    await update.message.delete()
    settings = get_user_settings(chat_id)
    await context.bot.send_message(chat_id, "⚙️ <b>Налаштування</b>", parse_mode=ParseMode.HTML, reply_markup=get_settings_menu_keyboard(settings))
    return ConversationHandler.END

async def ticker_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: return
    ticker = update.message.text.strip().upper()
    settings = get_user_settings(update.effective_chat.id)
    message = await update.message.reply_text(f"Шукаю <b>{html.escape(ticker)}</b>...", parse_mode=ParseMode.HTML)
    df = get_funding_for_ticker_sequential(ticker, settings['exchanges'])
    message_text = format_ticker_info(df, ticker)
    await message.edit_text(message_text, parse_mode=ParseMode.HTML, disable_web_page_preview=True)

# --- Головна функція запуску ---
def main() -> None:
    load_dotenv()
    TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
    if not TOKEN: logger.critical("!!! НЕ ЗНАЙДЕНО TELEGRAM_BOT_TOKEN !!!"); return

    application = Application.builder().token(TOKEN).build()
    
    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(set_threshold_callback, pattern="^settings_threshold$")],
        states={SET_THRESHOLD_STATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_threshold_conversation)]},
        fallbacks=[CallbackQueryHandler(settings_menu_callback, pattern="^settings_menu$")]
    )

    application.add_handler(CommandHandler("start", start_or_refresh))
    application.add_handler(CallbackQueryHandler(start_or_refresh, pattern="^refresh$"))
    application.add_handler(CallbackQueryHandler(settings_menu_callback, pattern="^settings_menu$"))
    application.add_handler(CallbackQueryHandler(close_settings_callback, pattern="^close_settings$"))
    application.add_handler(CallbackQueryHandler(exchange_menu_callback, pattern="^settings_exchanges$"))
    application.add_handler(CallbackQueryHandler(toggle_exchange_callback, pattern="^toggle_exchange_"))
    application.add_handler(CallbackQueryHandler(toggle_bot_status_callback, pattern="^toggle_bot_status$"))
    application.add_handler(conv_handler)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, ticker_message_handler))
    
    logger.info("Бот запускається в повнофункціональному режимі...")
    application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()