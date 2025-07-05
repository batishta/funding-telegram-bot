# run_bot.py (Фінальна версія з усіма виправленнями від 09.07)

import os
import logging
import time
import html
import pandas as pd
import pytz
from datetime import datetime
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters, ConversationHandler
from telegram.constants import ParseMode
from telegram.error import BadRequest
import ccxt

# --- НАЛАШТУВАННЯ ---
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)
TARGET_TIMEZONE = pytz.timezone('Europe/Kiev')

# --- КОНФІГУРАЦІЯ ---
AVAILABLE_EXCHANGES = {
    'Binance': 'binanceusdm', 'ByBit': 'bybit', 'MEXC': 'mexc', 'OKX': 'okx', 'Bitget': 'bitget',
    'KuCoin': 'kucoinfutures', 'Gate.io': 'gate', 'Huobi': 'huobi', 'BingX': 'bingx'
}
EXCHANGE_URL_TEMPLATES = {
    'Binance': 'https://www.binance.com/en/futures/{symbol}', 'ByBit': 'https://www.bybit.com/trade/usdt/{symbol}',
    'MEXC': 'https://futures.mexc.com/exchange/{symbol}_USDT', 'OKX': 'https://www.okx.com/trade-swap/{symbol_hyphen}',
    'Bitget': 'https://www.bitget.com/futures/usdt/{symbol}usdt', 'KuCoin': 'https://www.kucoin.com/futures/trade/{symbol}',
    'Gate.io': 'https://www.gate.io/futures_trade/USDT/{symbol}_USDT', 'Huobi': 'https://futures.huobi.com/en-us/linear_swap/exchange/swap_trade/?contract_code={symbol}-USDT',
    'BingX': 'https://swap.bingx.com/en-us/{symbol}-USDT'
}
DEFAULT_SETTINGS = {
    "threshold": 0.3, "exchanges": ['Binance', 'ByBit', 'OKX', 'Bitget', 'KuCoin', 'MEXC', 'Gate.io'], "update_interval": 60
}
TOP_N = 10
(SET_THRESHOLD_STATE,) = range(1)
HELP_URL = "https://www.google.com/search?q=aistudio+google+com"

# --- СЕРВІСНІ ФУНКЦІЇ ---
def get_all_funding_data_sequential(enabled_exchanges: list) -> pd.DataFrame:
    all_rates = []
    for name in enabled_exchanges:
        exchange_id = AVAILABLE_EXCHANGES.get(name)
        if not exchange_id: continue
        exchange = getattr(ccxt, exchange_id)({'timeout': 20000})
        try:
            funding_rates_data = exchange.fetch_funding_rates()
            for symbol, data in funding_rates_data.items():
                if 'USDT' in symbol and data.get('fundingRate') is not None:
                    all_rates.append({'symbol': symbol.split('/')[0], 'rate': data['fundingRate'] * 100, 'exchange': name, 'next_funding_time': pd.to_datetime(data.get('nextFundingTimestamp', data.get('fundingTimestamp')), unit='ms', utc=True)})
        except ccxt.NotSupported:
            try:
                markets = exchange.load_markets()
                swap_symbols = [m['symbol'] for m in markets.values() if m.get('swap') and m.get('quote', '').upper() == 'USDT']
                if not swap_symbols: continue
                tickers = exchange.fetch_tickers(swap_symbols)
                for symbol, ticker in tickers.items():
                    rate_info, time_info = None, None
                    if 'fundingRate' in ticker: rate_info = ticker['fundingRate']
                    elif isinstance(ticker.get('info'), dict) and 'fundingRate' in ticker['info']: rate_info = ticker['info']['fundingRate']
                    if 'fundingTimestamp' in ticker: time_info = ticker['fundingTimestamp']
                    elif isinstance(ticker.get('info'), dict) and 'nextFundingTime' in ticker['info']: time_info = ticker['info']['nextFundingTime']
                    if rate_info is not None:
                        all_rates.append({'symbol': symbol.split('/')[0], 'rate': float(rate_info) * 100, 'exchange': name, 'next_funding_time': pd.to_datetime(time_info, unit='ms', utc=True) if time_info else None})
            except Exception as e: logger.error(f"Альт. метод для {name}: {e}")
        except Exception as e: logger.error(f"Загальна помилка для {name}: {e}")
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
    if str(chat_id) not in _user_settings_cache: _user_settings_cache[str(chat_id)] = DEFAULT_SETTINGS.copy()
    return _user_settings_cache[str(chat_id)]
def update_user_setting(chat_id: int, key: str, value): get_user_settings(chat_id)[key] = value

# --- КЛАВІАТУРИ ---
def get_start_menu_keyboard(): return InlineKeyboardMarkup([[InlineKeyboardButton("💎 Тільки Фандінг", callback_data="show_funding_only")], [InlineKeyboardButton("📊 Фандінг + Спред", callback_data="show_funding_spread")]])
def get_main_menu_keyboard(): return InlineKeyboardMarkup([[InlineKeyboardButton("🔄 Оновити", callback_data="refresh"), InlineKeyboardButton("⚙️ Налаштування", callback_data="settings_menu")]])
def get_settings_menu_keyboard(settings: dict):
    interval = settings.get('update_interval', 60)
    interval_text = f"{interval} хв" if interval < 60 else f"{interval//60} год"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🌐 Біржі", callback_data="settings_exchanges")],
        [InlineKeyboardButton(f"📊 Фандінг: > {settings['threshold']}%", callback_data="settings_threshold")],
        [InlineKeyboardButton(f"⏳ Час оновлення: {interval_text}", callback_data="settings_interval")],
        [InlineKeyboardButton("📊 Фандінг + Спред", callback_data="show_funding_spread")],
        [InlineKeyboardButton("ℹ️ Довідка", url=HELP_URL)],
        [InlineKeyboardButton("↩️ Назад", callback_data="close_settings")] # ВИПРАВЛЕНО: Закрити -> Назад
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
def get_interval_selection_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("5 хв", callback_data="set_interval_5"), InlineKeyboardButton("15 хв", callback_data="set_interval_15"), InlineKeyboardButton("30 хв", callback_data="set_interval_30")],
        [InlineKeyboardButton("1 год", callback_data="set_interval_60"), InlineKeyboardButton("4 год", callback_data="set_interval_240"), InlineKeyboardButton("8 год", callback_data="set_interval_480")],
        [InlineKeyboardButton("↩️ Назад", callback_data="settings_menu")]
    ])
def get_back_to_settings_keyboard(): return InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Назад", callback_data="settings_menu")]])
def get_ticker_menu_keyboard(ticker: str): return InlineKeyboardMarkup([[InlineKeyboardButton("🔄 Оновити", callback_data=f"refresh_ticker_{ticker}"), InlineKeyboardButton("↩️ Назад", callback_data="refresh")]])

# --- ФОРМАТУВАЛЬНИКИ ---
def format_time_remaining(dt_object):
    if not isinstance(dt_object, pd.Timestamp): return "##:##"
    now_utc = datetime.now(dt_object.tz)
    delta = dt_object - now_utc
    if delta.total_seconds() < 0: return "00:00"
    hours, remainder = divmod(int(delta.total_seconds()), 3600)
    minutes, _ = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}"

def get_trade_link(exchange: str, symbol: str) -> str:
    template = EXCHANGE_URL_TEMPLATES.get(exchange)
    if not template: return ""
    return template.format(symbol=f"{symbol}USDT", symbol_hyphen=f"{symbol}-USDT")

def format_funding_update(df: pd.DataFrame, threshold: float) -> str:
    if df.empty: return "Не знайдено даних по фандінгу."
    df['abs_rate'] = df['rate'].abs()
    filtered_df = df[df['abs_rate'] >= threshold].sort_values('abs_rate', ascending=False).head(TOP_N)
    if filtered_df.empty: return f"🟢 Немає монет з фандингом вище <b>{threshold}%</b> або нижче <b>-{threshold}%</b>."
    header = f"<b>💎 Топ-{len(filtered_df)} сигналів (поріг > {threshold}%)</b>\n" # ВИПРАВЛЕНО: Прибрано зайвий відступ
    lines = ["<pre>"]
    for _, row in filtered_df.iterrows():
        emoji = "🟢" if row['rate'] < 0 else "🔴"
        symbol_str = f"{row['symbol']:<9}"
        rate_str = f"{row['rate']: >-8.4f}%"
        time_str = "##:## (##:##)"
        if pd.notna(row['next_funding_time']):
            local_time_str = row['next_funding_time'].astimezone(TARGET_TIMEZONE).strftime('%H:%M')
            time_rem_str = f"({format_time_remaining(row['next_funding_time'])})"
            time_str = f"{local_time_str} {time_rem_str:<8}"
        link = get_trade_link(row['exchange'], row['symbol'])
        exchange_str = f'<a href="{link}">{row["exchange"]}</a>'
        lines.append(f"{emoji} {symbol_str} | {rate_str} | {time_str} | {exchange_str}")
    lines.append("</pre>")
    return header + "\n".join(lines)

def format_ticker_info(df: pd.DataFrame, ticker: str) -> str:
    if df.empty: return f"Не знайдено даних для <b>{html.escape(ticker)}</b>."
    header = f"<b>🪙 Фандінг для {html.escape(ticker.upper())}</b>\n"
    lines = ["<pre>"]
    for _, row in df.iterrows():
        emoji = "🟢" if row['rate'] < 0 else "🔴"
        time_str = "##:## (##:##)"
        if pd.notna(row['next_funding_time']):
            local_time_str = row['next_funding_time'].astimezone(TARGET_TIMEZONE).strftime('%H:%M')
            time_rem_str = f"({format_time_remaining(row['next_funding_time'])})"
            time_str = f"{local_time_str} {time_rem_str:<8}"
        link = get_trade_link(row['exchange'], row['symbol'])
        exchange_str = f'<a href="{link}">{row["exchange"]}</a>'
        lines.append(f"{emoji} <b>{row['rate']: >-7.4f}%</b> | {time_str} | {exchange_str}")
    lines.append("</pre>")
    return header + "\n".join(lines)

# --- ОБРОБНИКИ ТЕЛЕГРАМ ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message: return
    await update.message.reply_text("👋 Вітаю! Оберіть режим роботи:", reply_markup=get_start_menu_keyboard())

async def show_funding_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    chat_id = query.message.chat.id
    settings = get_user_settings(chat_id)
    await query.edit_message_text("Починаю пошук фандінгу...")
    try:
        df = get_all_funding_data_sequential(settings['exchanges'])
        message_text = format_funding_update(df, settings['threshold'])
        await query.edit_message_text(text=message_text, parse_mode=ParseMode.HTML, reply_markup=get_main_menu_keyboard(), disable_web_page_preview=True)
    except Exception as e:
        logger.error(f"Помилка в show_funding_report: {e}", exc_info=True)
        await query.edit_message_text("😔 Виникла помилка.")

async def show_funding_spread(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer("Ця функція знаходиться в розробці.", show_alert=True)

async def refresh_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_funding_report(update, context)

async def settings_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    settings = get_user_settings(query.message.chat.id)
    await query.edit_message_text("⚙️ <b>Налаштування</b>", parse_mode=ParseMode.HTML, reply_markup=get_settings_menu_keyboard(settings))

async def close_settings_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_funding_report(update, context)

async def set_threshold_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    settings = get_user_settings(query.message.chat.id)
    text = f"Зараз встановлено значення <b>{settings['threshold']}%</b>. Тобто бот надсилає сигнали з фандингом, більшим за +{settings['threshold']}% або меншим за -{settings['threshold']}%.\nНадішліть нове значення. Дробові значення вказуйте через крапку або кому."
    # Зберігаємо ID повідомлення з меню, щоб потім його видалити
    context.user_data['settings_message_id'] = query.message.message_id
    await query.message.reply_text(text, parse_mode=ParseMode.HTML)
    return SET_THRESHOLD_STATE

async def set_threshold_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: return ConversationHandler.END
    chat_id = update.effective_chat.id
    user_input = update.message.text.strip().replace(',', '.')
    try:
        new_threshold = abs(float(user_input))
        update_user_setting(chat_id, 'threshold', new_threshold)
        
        # ВИПРАВЛЕНО: Видаляємо старі повідомлення
        settings_message_id = context.user_data.pop('settings_message_id', None)
        if settings_message_id:
            try: await context.bot.delete_message(chat_id, settings_message_id)
            except BadRequest: pass
        if update.message.reply_to_message:
             try: await context.bot.delete_message(chat_id, update.message.reply_to_message.message_id)
             except BadRequest: pass
        await update.message.delete()
        
        settings = get_user_settings(chat_id)
        await context.bot.send_message(chat_id, f"✅ Чудово! Встановлено нове порогове значення фандингу: <b>+/- {new_threshold}%</b>", parse_mode=ParseMode.HTML)
        await context.bot.send_message(chat_id, "⚙️ <b>Налаштування</b>", parse_mode=ParseMode.HTML, reply_markup=get_settings_menu_keyboard(settings))
    except (ValueError, TypeError):
        await update.message.reply_text("Некоректне значення. Спробуйте ще раз (напр., 0.5).")
        return SET_THRESHOLD_STATE
    return ConversationHandler.END

async def ticker_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: return
    try: float(update.message.text.strip().replace(',', '.')); return
    except ValueError: pass
    ticker = update.message.text.strip().upper()
    settings = get_user_settings(update.effective_chat.id)
    message = await update.message.reply_text(f"Шукаю <b>{html.escape(ticker)}</b>...", parse_mode=ParseMode.HTML)
    df = get_funding_for_ticker_sequential(ticker, settings['exchanges'])
    message_text = format_ticker_info(df, ticker)
    await message.edit_text(message_text, parse_mode=ParseMode.HTML, reply_markup=get_ticker_menu_keyboard(ticker), disable_web_page_preview=True)

async def refresh_ticker_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; ticker = query.data.split('_')[-1]
    await query.answer(f"Оновлюю {ticker}...")
    settings = get_user_settings(query.message.chat.id)
    df = get_funding_for_ticker_sequential(ticker, settings['exchanges'])
    message_text = format_ticker_info(df, ticker)
    try: await query.edit_message_text(text=message_text, parse_mode=ParseMode.HTML, reply_markup=get_ticker_menu_keyboard(ticker), disable_web_page_preview=True)
    except Exception as e: logger.error(f"ПОМИЛКА в refresh_ticker_callback: {e}", exc_info=True)

async def exchange_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    settings = get_user_settings(query.message.chat.id)
    await query.edit_message_text("🌐 <b>Вибір бірж</b>", parse_mode=ParseMode.HTML, reply_markup=get_exchange_selection_keyboard(settings['exchanges']))
async def toggle_exchange_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; exchange_name = query.data.split('_')[-1]
    settings = get_user_settings(query.message.chat.id)
    if exchange_name in settings['exchanges']: settings['exchanges'].remove(exchange_name)
    else: settings['exchanges'].append(exchange_name)
    update_user_setting(query.message.chat.id, 'exchanges', settings['exchanges'])
    await query.edit_message_reply_markup(reply_markup=get_exchange_selection_keyboard(settings['exchanges']))
    await query.answer(f"Біржа {exchange_name} оновлена")
async def set_interval_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    await query.edit_message_text("⏳ <b>Час оновлення</b>\n\nОберіть інтервал. Авто-оновлення буде реалізовано пізніше.", parse_mode=ParseMode.HTML, reply_markup=get_interval_selection_keyboard())
async def set_interval_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; interval = int(query.data.split('_')[-1])
    update_user_setting(query.message.chat.id, 'update_interval', interval)
    await query.answer(f"Інтервал встановлено.")
    await settings_menu_callback(update, context)

# --- ГОЛОВНА ФУНКЦІЯ ЗАПУСКУ ---
def main() -> None:
    load_dotenv(); TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
    if not TOKEN: logger.critical("!!! НЕ ЗНАЙДЕНО TOKEN !!!"); return
    application = Application.builder().token(TOKEN).build()
    
    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(set_threshold_callback, pattern="^settings_threshold$")],
        states={SET_THRESHOLD_STATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_threshold_conversation)]},
        fallbacks=[CallbackQueryHandler(settings_menu_callback, pattern="^settings_menu$"), CallbackQueryHandler(close_settings_callback, pattern="^close_settings$")],
        per_message=False
    )
    
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CallbackQueryHandler(show_funding_report, pattern="^show_funding_only$"))
    application.add_handler(CallbackQueryHandler(show_funding_spread, pattern="^show_funding_spread$"))
    application.add_handler(CallbackQueryHandler(refresh_callback, pattern="^refresh$"))
    application.add_handler(CallbackQueryHandler(settings_menu_callback, pattern="^settings_menu$"))
    application.add_handler(CallbackQueryHandler(close_settings_callback, pattern="^close_settings$"))
    application.add_handler(CallbackQueryHandler(exchange_menu_callback, pattern="^settings_exchanges$"))
    application.add_handler(CallbackQueryHandler(toggle_exchange_callback, pattern="^toggle_exchange_"))
    application.add_handler(CallbackQueryHandler(set_interval_menu_callback, pattern="^settings_interval$"))
    application.add_handler(CallbackQueryHandler(set_interval_callback, pattern="^set_interval_"))
    application.add_handler(CallbackQueryHandler(refresh_ticker_callback, pattern="^refresh_ticker_"))
    application.add_handler(conv_handler)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, ticker_message_handler))
    
    logger.info("Бот запускається (версія з фінальними правками)...")
    application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()