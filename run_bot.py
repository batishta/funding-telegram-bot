# run_bot.py (Версія 2.9.1 - Фікс форматування)

import os
import logging
import html
import asyncio
import pandas as pd
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
BOT_VERSION = "v2.9.1"

# --- КОНФІГУРАЦІЯ ---
AVAILABLE_EXCHANGES = {'Binance': 'binanceusdm', 'ByBit': 'bybit', 'MEXC': 'mexc', 'OKX': 'okx', 'Bitget': 'bitget', 'KuCoin': 'kucoinfutures', 'Gate.io': 'gate', 'Huobi': 'huobi', 'BingX': 'bingx'}
EXCHANGE_URL_TEMPLATES = {
    'Binance': 'https://www.binance.com/en/futures/{symbol}', 'ByBit': 'https://www.bybit.com/trade/usdt/{symbol}',
    'MEXC': 'https://futures.mexc.com/exchange/{symbol_base}_USDT', 'OKX': 'https://www.okx.com/trade-swap/{symbol_hyphen}',
    'Bitget': 'https://www.bitget.com/futures/usdt/{symbol}', 'KuCoin': 'https://www.kucoin.com/futures/trade/{symbol}',
    'Gate.io': 'https://www.gate.io/futures_trade/USDT/{symbol_base}_USDT', 'Huobi': 'https://futures.huobi.com/en-us/linear_swap/exchange/swap_trade/?contract_code={symbol}-USDT',
    'BingX': 'https://swap.bingx.com/en-us/{symbol}-USDT'
}
DEFAULT_SETTINGS = {"threshold": 0.2, "exchanges": ['Binance', 'ByBit', 'OKX', 'Bitget', 'KuCoin', 'MEXC', 'Gate.io'], "blacklist": []}
TOP_N = 10
(SET_THRESHOLD_STATE, ADD_TO_BLACKLIST_STATE, REMOVE_FROM_BLACKLIST_STATE) = range(3)
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
                    all_rates.append({'symbol': symbol.split('/')[0], 'rate': data['fundingRate'] * 100, 'exchange': name})
        except ccxt.NotSupported:
            try:
                markets = exchange.load_markets()
                swap_symbols = [m['symbol'] for m in markets.values() if m.get('swap') and m.get('quote', '').upper() == 'USDT']
                if not swap_symbols: continue
                tickers = exchange.fetch_tickers(swap_symbols)
                for symbol, ticker in tickers.items():
                    rate_info = None
                    if 'fundingRate' in ticker: rate_info = ticker['fundingRate']
                    elif isinstance(ticker.get('info'), dict) and 'fundingRate' in ticker['info']: rate_info = ticker['info']['fundingRate']
                    if rate_info is not None:
                        all_rates.append({'symbol': symbol.split('/')[0], 'rate': float(rate_info) * 100, 'exchange': name})
            except Exception as e: logger.error(f"Альт. метод для {name}: {e}")
        except Exception as e: logger.error(f"Загальна помилка для {name}: {e}")
    if not all_rates: return pd.DataFrame()
    return pd.DataFrame(all_rates).drop_duplicates(subset=['symbol', 'exchange'], keep='first')

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
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🌐 Біржі", callback_data="settings_exchanges"), InlineKeyboardButton(f"📊 Фандінг: > {settings['threshold']}%", callback_data="settings_threshold")],
        [InlineKeyboardButton("🚫 Чорний список", callback_data="blacklist_menu"), InlineKeyboardButton("📊 Фандінг + Спред", callback_data="show_funding_spread")],
        [InlineKeyboardButton("ℹ️ Довідка", url=HELP_URL), InlineKeyboardButton("↩️ Назад", callback_data="close_settings")]
    ])
def get_blacklist_menu_keyboard(blacklist: list):
    text = "🚫 Ваш чорний список:\n"
    if blacklist: text += "<code>" + ", ".join(blacklist) + "</code>"
    else: text += "<i>Порожній</i>"
    keyboard = [[InlineKeyboardButton("➕ Додати", callback_data="add_to_blacklist"), InlineKeyboardButton("➖ Видалити", callback_data="remove_from_blacklist")], [InlineKeyboardButton("↩️ Назад до налаштувань", callback_data="settings_menu")]]
    return text, InlineKeyboardMarkup(keyboard)
def get_back_to_settings_keyboard(): return InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Назад", callback_data="settings_menu")]])
def get_ticker_menu_keyboard(ticker: str): return InlineKeyboardMarkup([[InlineKeyboardButton("🔄 Оновити", callback_data=f"refresh_ticker_{ticker}"), InlineKeyboardButton("↩️ Назад", callback_data="refresh")]])
def get_exchange_selection_keyboard(selected_exchanges: list):
    buttons = []; row = []
    for name in AVAILABLE_EXCHANGES.keys():
        text = f"✅ {name}" if name in selected_exchanges else f"☑️ {name}"
        row.append(InlineKeyboardButton(text, callback_data=f"toggle_exchange_{name}"))
        if len(row) == 3: buttons.append(row); row = []
    if row: buttons.append(row)
    buttons.append([InlineKeyboardButton("↩️ Назад", callback_data="settings_menu")])
    return InlineKeyboardMarkup(buttons)

# --- ФОРМАТУВАЛЬНИКИ ---
def get_trade_link(exchange: str, symbol: str) -> str:
    template = EXCHANGE_URL_TEMPLATES.get(exchange)
    if not template: return ""
    return template.format(symbol=f"{symbol}USDT", symbol_base=symbol, symbol_hyphen=f"{symbol}-USDT")

def format_funding_update(df: pd.DataFrame, threshold: float, blacklist: list) -> str:
    if df.empty: return "Не знайдено даних по фандінгу."
    df = df[~df['symbol'].isin(blacklist)]
    df['abs_rate'] = df['rate'].abs()
    best_offers = df.loc[df.groupby('symbol')['abs_rate'].idxmax()]
    filtered_df = best_offers[best_offers['abs_rate'] >= threshold].copy()
    filtered_df.sort_values('abs_rate', ascending=False, inplace=True)
    filtered_df = filtered_df.head(TOP_N)
    
    if filtered_df.empty: return f"🟢 Немає монет з фандингом вище <b>{threshold}%</b> або нижче <b>-{threshold}%</b>."
    header = f"<b>💎 Топ-{len(filtered_df)} сигналів (поріг > {threshold}%)</b>"
    
    lines = []
    for _, row in filtered_df.iterrows():
        emoji = "🟢" if row['rate'] < 0 else "🔴"
        symbol = row['symbol']
        display_symbol = (symbol[:7] + '..') if len(symbol) > 8 else symbol
        
        # ВИПРАВЛЕНО: Правильне форматування з одним тегом <code>
        symbol_part = f"{display_symbol:<9}" # 9 символів для тикера
        rate_part = f" {row['rate']: >-8.4f}% " # 8 символів для ставки
        
        link = get_trade_link(row['exchange'], row['symbol'])
        exchange_str = f'<a href="{link}">{row["exchange"]}</a>'
        
        # Копіюємо тикер при натисканні на нього
        lines.append(f"{emoji} <code>{symbol_part}</code>|<code>{rate_part}</code>| {exchange_str}")
    
    footer = f"\n\n<i>{BOT_VERSION}</i>"
    return f"{header}\n\n" + "\n".join(lines) + footer

def format_ticker_info(df: pd.DataFrame, ticker: str) -> str:
    if df.empty: return f"Не знайдено даних для <b>{html.escape(ticker)}</b>."
    header = f"<b>🪙 Фандінг для {html.escape(ticker.upper())}</b>"
    df.sort_values(by='rate', ascending=False, inplace=True)
    
    lines = []
    for _, row in df.iterrows():
        emoji = "🟢" if row['rate'] < 0 else "🔴"
        rate_part = f"{row['rate']: >-8.4f}%"
        link = get_trade_link(row['exchange'], row['symbol'])
        exchange_str = f'<a href="{link}">{row["exchange"]}</a>'
        
        lines.append(f"{emoji} <code> {rate_part} </code> | {exchange_str}")
        
    return f"{header}\n\n" + "\n".join(lines) + "\n\n"

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
        message_text = format_funding_update(df, settings['threshold'], settings.get('blacklist', []))
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
    text = f"Зараз встановлено значення <b>{settings['threshold']}%</b>.\nНадішліть нове значення (наприклад: 0.5)."
    sent_message = await query.message.reply_text(text, parse_mode=ParseMode.HTML)
    context.user_data['prompt_message_id'] = sent_message.message_id
    context.user_data['settings_message_id'] = query.message.message_id
    return SET_THRESHOLD_STATE
async def set_threshold_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: return ConversationHandler.END
    chat_id = update.effective_chat.id
    user_input = update.message.text.strip().replace(',', '.')
    try:
        new_threshold = abs(float(user_input))
        update_user_setting(chat_id, 'threshold', new_threshold)
        prompt_message_id = context.user_data.pop('prompt_message_id', None)
        if prompt_message_id:
            try: await context.bot.delete_message(chat_id, prompt_message_id)
            except BadRequest: pass
        settings_message_id = context.user_data.pop('settings_message_id', None)
        if settings_message_id:
            try: await context.bot.delete_message(chat_id, settings_message_id)
            except BadRequest: pass
        await update.message.delete()
        success_msg = await context.bot.send_message(chat_id, f"✅ Встановлено новий поріг: <b>+/- {new_threshold}%</b>", parse_mode=ParseMode.HTML)
        await asyncio.sleep(3); await success_msg.delete()
        settings = get_user_settings(chat_id)
        await context.bot.send_message(chat_id, "⚙️ <b>Налаштування</b>", parse_mode=ParseMode.HTML, reply_markup=get_settings_menu_keyboard(settings))
    except (ValueError, TypeError):
        await update.message.reply_text("Некоректне значення. Спробуйте ще раз (наприклад: 0.5).")
        return SET_THRESHOLD_STATE
    return ConversationHandler.END
async def ticker_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: return
    try: float(update.message.text.strip().replace(',', '.')); return
    except ValueError: pass
    ticker = update.message.text.strip().upper()
    settings = get_user_settings(update.effective_chat.id)
    message = await update.message.reply_text(f"Шукаю <b>{html.escape(ticker)}</b>...", parse_mode=ParseMode.HTML)
    df = get_all_funding_data_sequential(settings['exchanges'])
    df_ticker = df[df['symbol'] == ticker]
    message_text = format_ticker_info(df_ticker, ticker)
    await message.edit_text(message_text, parse_mode=ParseMode.HTML, reply_markup=get_ticker_menu_keyboard(ticker), disable_web_page_preview=True)
async def refresh_ticker_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; ticker = query.data.split('_')[-1]
    await query.answer(f"Оновлюю {ticker}...")
    settings = get_user_settings(query.message.chat.id)
    df = get_all_funding_data_sequential(settings['exchanges'])
    df_ticker = df[df['symbol'] == ticker]
    message_text = format_ticker_info(df_ticker, ticker)
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
async def blacklist_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    settings = get_user_settings(query.message.chat.id)
    text, keyboard = get_blacklist_menu_keyboard(settings.get('blacklist', []))
    await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=keyboard)
async def add_to_blacklist_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    sent_message = await query.message.reply_text("Надішліть назви монет для додавання в чорний список.")
    context.user_data['prompt_message_id'] = sent_message.message_id
    context.user_data['settings_message_id'] = query.message.message_id
    return ADD_TO_BLACKLIST_STATE
async def add_to_blacklist_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: return ConversationHandler.END
    chat_id = update.effective_chat.id; settings = get_user_settings(chat_id)
    blacklist = settings.get('blacklist', [])
    new_tickers = {t.strip().upper() for t in update.message.text.replace(",", " ").split()}
    added_count = len(new_tickers - set(blacklist))
    blacklist.extend(list(new_tickers - set(blacklist)))
    update_user_setting(chat_id, 'blacklist', blacklist)
    prompt_message_id = context.user_data.pop('prompt_message_id', None)
    if prompt_message_id:
        try: await context.bot.delete_message(chat_id, prompt_message_id)
        except: pass
    settings_message_id = context.user_data.pop('settings_message_id', None)
    if settings_message_id:
        try: await context.bot.delete_message(chat_id, settings_message_id)
        except: pass
    await update.message.delete()
    success_msg = await context.bot.send_message(chat_id, f"✅ Додано {added_count} монет у чорний список.")
    await asyncio.sleep(3); await success_msg.delete()
    text, keyboard = get_blacklist_menu_keyboard(blacklist)
    await context.bot.send_message(chat_id, text, parse_mode=ParseMode.HTML, reply_markup=keyboard)
    return ConversationHandler.END
async def remove_from_blacklist_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    sent_message = await query.message.reply_text("Надішліть назви монет для видалення з чорного списку.")
    context.user_data['prompt_message_id'] = sent_message.message_id
    context.user_data['settings_message_id'] = query.message.message_id
    return REMOVE_FROM_BLACKLIST_STATE
async def remove_from_blacklist_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: return ConversationHandler.END
    chat_id = update.effective_chat.id; settings = get_user_settings(chat_id)
    blacklist = settings.get('blacklist', [])
    tickers_to_remove = {t.strip().upper() for t in update.message.text.replace(",", " ").split()}
    removed_count = len(set(blacklist) & tickers_to_remove)
    blacklist = [t for t in blacklist if t not in tickers_to_remove]
    update_user_setting(chat_id, 'blacklist', blacklist)
    prompt_message_id = context.user_data.pop('prompt_message_id', None)
    if prompt_message_id:
        try: await context.bot.delete_message(chat_id, prompt_message_id)
        except: pass
    settings_message_id = context.user_data.pop('settings_message_id', None)
    if settings_message_id:
        try: await context.bot.delete_message(chat_id, settings_message_id)
        except: pass
    await update.message.delete()
    success_msg = await context.bot.send_message(chat_id, f"✅ Видалено {removed_count} монет з чорного списку.")
    await asyncio.sleep(3); await success_msg.delete()
    text, keyboard = get_blacklist_menu_keyboard(blacklist)
    await context.bot.send_message(chat_id, text, parse_mode=ParseMode.HTML, reply_markup=keyboard)
    return ConversationHandler.END

# --- ГОЛОВНА ФУНКЦІЯ ЗАПУСКУ ---
def main() -> None:
    load_dotenv(); TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
    if not TOKEN: logger.critical("!!! НЕ ЗНАЙДЕНО TOKEN !!!"); return
    application = Application.builder().token(TOKEN).build()
    
    threshold_conv = ConversationHandler(entry_points=[CallbackQueryHandler(set_threshold_callback, pattern="^settings_threshold$")], states={SET_THRESHOLD_STATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_threshold_conversation)]}, fallbacks=[CallbackQueryHandler(settings_menu_callback, pattern="^settings_menu$")], per_message=False)
    blacklist_conv = ConversationHandler(entry_points=[CallbackQueryHandler(add_to_blacklist_callback, pattern="^add_to_blacklist$"), CallbackQueryHandler(remove_from_blacklist_callback, pattern="^remove_from_blacklist$")], states={ADD_TO_BLACKLIST_STATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_to_blacklist_conversation)], REMOVE_FROM_BLACKLIST_STATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, remove_from_blacklist_conversation)]}, fallbacks=[CallbackQueryHandler(blacklist_menu_callback, pattern="^blacklist_menu$")], per_message=False)
    
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CallbackQueryHandler(show_funding_report, pattern="^show_funding_only$"))
    application.add_handler(CallbackQueryHandler(show_funding_spread, pattern="^show_funding_spread$"))
    application.add_handler(CallbackQueryHandler(refresh_callback, pattern="^refresh$"))
    application.add_handler(CallbackQueryHandler(settings_menu_callback, pattern="^settings_menu$"))
    application.add_handler(CallbackQueryHandler(close_settings_callback, pattern="^close_settings$"))
    application.add_handler(CallbackQueryHandler(exchange_menu_callback, pattern="^settings_exchanges$"))
    application.add_handler(CallbackQueryHandler(toggle_exchange_callback, pattern="^toggle_exchange_"))
    application.add_handler(CallbackQueryHandler(blacklist_menu_callback, pattern="^blacklist_menu$"))
    application.add_handler(CallbackQueryHandler(refresh_ticker_callback, pattern="^refresh_ticker_"))
    application.add_handler(threshold_conv)
    application.add_handler(blacklist_conv)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, ticker_message_handler))
    
    logger.info(f"Бот запускається (версія {BOT_VERSION})...")
    application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()