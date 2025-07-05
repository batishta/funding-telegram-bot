# run_bot.py (Версія з виправленнями від 06.07)

import os
import logging
import time
import html
import pandas as pd
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters, ConversationHandler
from telegram.constants import ParseMode
import ccxt

# --- НАЛАШТУВАННЯ ---
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)

# --- КОНФІГУРАЦІЯ (раніше була в src/config.py) ---
AVAILABLE_EXCHANGES = {
    'Binance': 'binanceusdm', 'ByBit': 'bybit', 'MEXC': 'mexc', 'OKX': 'okx',
    'Bitget': 'bitget', 'KuCoin': 'kucoinfutures', 'Gate.io': 'gate'
}
EXCHANGE_URL_TEMPLATES = {
    'Binance': 'https://www.binance.com/en/futures/{symbol}',
    'ByBit': 'https://www.bybit.com/trade/usdt/{symbol}',
    'MEXC': 'https://futures.mexc.com/exchange/{symbol}_USDT',
    'OKX': 'https://www.okx.com/trade-swap/{symbol_hyphen}',
    'Bitget': 'https://www.bitget.com/futures/usdt/{symbol}usdt',
    'KuCoin': 'https://www.kucoin.com/futures/trade/{symbol}',
    'Gate.io': 'https://www.gate.io/futures_trade/USDT/{symbol}_USDT',
}
DEFAULT_SETTINGS = {
    "enabled": True, "threshold": 0.3, "interval": 60,
    "exchanges": ['Binance', 'ByBit', 'OKX', 'Bitget', 'KuCoin', 'MEXC', 'Gate.io']
}
TOP_N = 20 # Збільшимо кількість позицій
SET_THRESHOLD_STATE = 0

# --- СЕРВІСНІ ФУНКЦІЇ ---
def get_all_funding_data_sequential(enabled_exchanges: list) -> pd.DataFrame:
    logger.info(f"Запуск сканування для: {enabled_exchanges}")
    all_rates = []
    for name in enabled_exchanges:
        exchange_id = AVAILABLE_EXCHANGES.get(name)
        if not exchange_id: continue
        try:
            logger.info(f"--- Обробка: {name} ---")
            exchange = getattr(ccxt, exchange_id)({'timeout': 20000})
            funding_rates_data = exchange.fetch_funding_rates()
            for symbol, data in funding_rates_data.items():
                if 'USDT' in symbol and data.get('fundingRate') is not None:
                    all_rates.append({
                        'symbol': symbol.split('/')[0], 'rate': data['fundingRate'] * 100,
                        'exchange': name, 'next_funding_time': pd.to_datetime(data.get('nextFundingTimestamp'), unit='ms', utc=True)
                    })
        except ccxt.NotSupported:
            logger.warning(f"-> {name}: Альтернативний метод...")
            try:
                exchange = getattr(ccxt, exchange_id)({'timeout': 20000})
                markets = exchange.load_markets()
                swap_symbols = [m['symbol'] for m in markets.values() if m.get('swap') and m.get('quote', '').upper() == 'USDT']
                if not swap_symbols: continue
                tickers = exchange.fetch_tickers(swap_symbols)
                for symbol, ticker in tickers.items():
                    rate_info = None
                    if 'fundingRate' in ticker: rate_info = ticker['fundingRate']
                    elif isinstance(ticker.get('info'), dict) and 'fundingRate' in ticker['info']: rate_info = ticker['info']['fundingRate']
                    if rate_info is not None:
                        all_rates.append({
                            'symbol': symbol.split('/')[0], 'rate': float(rate_info) * 100,
                            'exchange': name, 'next_funding_time': pd.to_datetime(ticker.get('fundingTimestamp'), unit='ms', utc=True)
                        })
            except Exception as e: logger.error(f"   ! Помилка альт. методу для {name}: {e}")
        except Exception as e: logger.error(f"   ! Загальна помилка для {name}: {e}")
    if not all_rates: return pd.DataFrame()
    return pd.DataFrame(all_rates).drop_duplicates(subset=['symbol', 'exchange'], keep='first')

def get_funding_for_ticker_sequential(ticker: str, enabled_exchanges: list) -> pd.DataFrame:
    ticker_clean = ticker.upper().replace("USDT", "").replace("/", "")
    full_data = get_all_funding_data_sequential(enabled_exchanges)
    if full_data.empty: return pd.DataFrame()
    return full_data[full_data['symbol'] == ticker_clean].sort_values(by='rate', ascending=False)

# --- РОБОТА З НАЛАШТУВАННЯМИ ---
_user_settings_cache = {}
def get_user_settings(chat_id: int) -> dict:
    if str(chat_id) not in _user_settings_cache:
        _user_settings_cache[str(chat_id)] = DEFAULT_SETTINGS.copy()
    return _user_settings_cache[str(chat_id)]
def update_user_setting(chat_id: int, key: str, value):
    get_user_settings(chat_id)[key] = value

# --- КЛАВІАТУРИ ---
def get_main_menu_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔄 Оновити", callback_data="refresh"), InlineKeyboardButton("⚙️ Налаштування", callback_data="settings_menu")]])
def get_settings_menu_keyboard(settings: dict):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🌐 Біржі", callback_data="settings_exchanges")],
        [InlineKeyboardButton(f"📊 Фандінг: > {settings['threshold']}%", callback_data="settings_threshold")],
        [InlineKeyboardButton("❌ Закрити", callback_data="close_settings")]
    ])
def get_exchange_selection_keyboard(selected_exchanges: list):
    buttons = []; row = []
    for name in AVAILABLE_EXCHANGES.keys():
        text = f"✅ {name}" if name in selected_exchanges else f"☑️ {name}"
        row.append(InlineKeyboardButton(text, callback_data=f"toggle_exchange_{name}"))
        if len(row) == 2: buttons.append(row); row = []
    if row: buttons.append(row)
    buttons.append([InlineKeyboardButton("↩️ Назад", callback_data="settings_menu")])
    return InlineKeyboardMarkup(buttons)
def get_back_to_settings_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Назад", callback_data="settings_menu")]])

# --- ФОРМАТУВАЛЬНИКИ ---
def get_trade_link(exchange: str, symbol: str) -> str:
    template = EXCHANGE_URL_TEMPLATES.get(exchange)
    if not template: return ""
    symbol_usdt = f"{symbol}USDT"
    symbol_hyphen = f"{symbol}-USDT"
    return template.format(symbol=symbol_usdt, symbol_hyphen=symbol_hyphen)

def format_funding_update(df: pd.DataFrame, threshold: float) -> str:
    if df.empty: return "Не знайдено даних по фандінгу."
    df['abs_rate'] = df['rate'].abs()
    filtered_df = df[df['abs_rate'] >= threshold].sort_values('abs_rate', ascending=False).head(TOP_N)
    if filtered_df.empty: return f"🟢 Немає монет з фандінгом вище <b>{threshold}%</b> або нижче <b>-{threshold}%</b>."
    
    header = f"<b>💎 Топ-{len(filtered_df)} сигналів по фандінгу (поріг > {threshold}%)</b>\n"
    lines = []
    for _, row in filtered_df.iterrows():
        emoji = "🟢" if row['rate'] < 0 else "🔴" # ВИПРАВЛЕНО: Негативний фандінг -> можливість для лонгу (зелений)
        symbol_str = f"<code>{row['symbol']:<8}</code>"
        rate_str = f"<b>{row['rate']: >-7.4f}%</b>"
        time_str = row['next_funding_time'].strftime('%H:%M UTC') if pd.notna(row['next_funding_time']) else "##:## UTC"
        link = get_trade_link(row['exchange'], row['symbol'])
        exchange_str = f'<a href="{link}">{row["exchange"]}</a>' if link else row["exchange"]
        lines.append(f"{emoji} {symbol_str} | {rate_str} | {time_str} | {exchange_str}")
    return header + "\n".join(lines)

def format_ticker_info(df: pd.DataFrame, ticker: str) -> str:
    if df.empty: return f"Не знайдено даних для <b>{html.escape(ticker)}</b>."
    header = f"<b>🪙 Фандінг для {html.escape(ticker.upper())}</b>\n\n"
    lines = []
    for _, row in df.iterrows():
        emoji = "🟢" if row['rate'] < 0 else "🔴" # ВИПРАВЛЕНО: та сама логіка
        rate_str = f"<b>{row['rate']: >-7.4f}%</b>"
        time_str = row['next_funding_time'].strftime('%H:%M UTC') if pd.notna(row['next_funding_time']) else "##:## UTC"
        link = get_trade_link(row['exchange'], row['symbol'])
        exchange_str = f'<a href="{link}">{row["exchange"]}</a>' if link else row["exchange"]
        lines.append(f"{emoji} {rate_str} | {time_str} | {exchange_str}")
    return header + "\n".join(lines)

# --- ОБРОБНИКИ ТЕЛЕГРАМ ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_funding_report(update, context)

async def refresh_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("Оновлюю...")
    try:
        await query.message.delete()
    except Exception as e:
        logger.warning(f"Не вдалося видалити старе повідомлення: {e}")
    await send_funding_report(query, context)

async def send_funding_report(update_obj: Update | InlineKeyboardButton, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update_obj.effective_chat.id
    logger.info(f"Запит на звіт для чату {chat_id}")
    settings = get_user_settings(chat_id)
    
    message = await context.bot.send_message(chat_id, "Починаю пошук... Це може зайняти до хвилини.")
    try:
        df = get_all_funding_data_sequential(settings['exchanges'])
        message_text = format_funding_update(df, settings['threshold'])
        await message.edit_text(text=message_text, parse_mode=ParseMode.HTML, reply_markup=get_main_menu_keyboard(), disable_web_page_preview=True)
    except Exception as e:
        logger.error(f"Помилка в send_funding_report: {e}", exc_info=True)
        await message.edit_text("😔 Виникла помилка під час обробки.")

async def settings_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    settings = get_user_settings(query.effective_chat.id)
    await query.edit_message_text("⚙️ <b>Налаштування</b>", parse_mode=ParseMode.HTML, reply_markup=get_settings_menu_keyboard(settings))

async def close_settings_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    await query.message.delete()
    await send_funding_report(query, context)

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

async def set_threshold_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    settings = get_user_settings(query.effective_chat.id)
    await query.edit_message_text(f"Поточний поріг: <b>{settings['threshold']}%</b>.\n\nНадішліть нове значення (напр., <code>0.5</code>).", parse_mode=ParseMode.HTML, reply_markup=get_back_to_settings_keyboard())
    return SET_THRESHOLD_STATE

async def set_threshold_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: return ConversationHandler.END
    chat_id = update.effective_chat.id
    try:
        new_threshold = abs(float(update.message.text.strip()))
        if 0 < new_threshold < 100:
            update_user_setting(chat_id, 'threshold', new_threshold)
            await update.message.reply_text(f"✅ Новий поріг: <b>{new_threshold}%</b>", parse_mode=ParseMode.HTML)
    except (ValueError, TypeError): await update.message.reply_text("Некоректне значення.")
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

# --- ГОЛОВНА ФУНКЦІЯ ЗАПУСКУ ---
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

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CallbackQueryHandler(refresh_callback, pattern="^refresh$"))
    application.add_handler(CallbackQueryHandler(settings_menu_callback, pattern="^settings_menu$")) # ВИПРАВЛЕНО: Додано обробник
    application.add_handler(CallbackQueryHandler(close_settings_callback, pattern="^close_settings$"))
    application.add_handler(CallbackQueryHandler(exchange_menu_callback, pattern="^settings_exchanges$"))
    application.add_handler(CallbackQueryHandler(toggle_exchange_callback, pattern="^toggle_exchange_"))
    application.add_handler(conv_handler)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, ticker_message_handler))
    
    logger.info("Бот запускається в повнофункціональному режимі...")
    application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()