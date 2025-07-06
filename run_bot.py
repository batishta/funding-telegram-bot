# run_bot.py (Версія 2.1)

import os
import logging
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

# --- КОНФІГУРАЦІЯ ---
AVAILABLE_EXCHANGES = {'Binance': 'binanceusdm', 'ByBit': 'bybit', 'MEXC': 'mexc', 'OKX': 'okx', 'Bitget': 'bitget', 'KuCoin': 'kucoinfutures', 'Gate.io': 'gate', 'Huobi': 'huobi', 'BingX': 'bingx'}
EXCHANGE_URL_TEMPLATES = {'Binance': 'https://www.binance.com/en/futures/{symbol}', 'ByBit': 'https://www.bybit.com/trade/usdt/{symbol}', 'MEXC': 'https://futures.mexc.com/exchange/{symbol}_USDT', 'OKX': 'https://www.okx.com/trade-swap/{symbol_hyphen}', 'Bitget': 'https://www.bitget.com/futures/usdt/{symbol}usdt', 'KuCoin': 'https://www.kucoin.com/futures/trade/{symbol}', 'Gate.io': 'https://www.gate.io/futures_trade/USDT/{symbol}_USDT', 'Huobi': 'https://futures.huobi.com/en-us/linear_swap/exchange/swap_trade/?contract_code={symbol}-USDT', 'BingX': 'https://swap.bingx.com/en-us/{symbol}-USDT'}
DEFAULT_SETTINGS = {"threshold": 0.3, "exchanges": ['Binance', 'ByBit', 'OKX', 'Bitget', 'KuCoin', 'MEXC', 'Gate.io'], "blacklist": []}
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
                    # 'fundingInterval' - ключ, який деякі біржі використовують для періоду
                    period_ms = data.get('fundingInterval', 8 * 3600 * 1000) # За замовчуванням 8 годин
                    period_hours = round(period_ms / (3600 * 1000))
                    all_rates.append({'symbol': symbol.split('/')[0], 'rate': data['fundingRate'] * 100, 'exchange': name, 'period': f"{period_hours}ч"})
        except ccxt.NotSupported:
            try:
                markets = exchange.load_markets()
                swap_symbols = [m['symbol'] for m in markets.values() if m.get('swap') and m.get('quote', '').upper() == 'USDT']
                if not swap_symbols: continue
                tickers = exchange.fetch_tickers(swap_symbols)
                for symbol, ticker in tickers.items():
                    rate_info, period_info = None, "8ч" # За замовчуванням
                    if 'fundingRate' in ticker: rate_info = ticker['fundingRate']
                    elif isinstance(ticker.get('info'), dict) and 'fundingRate' in ticker['info']: rate_info = ticker['info']['fundingRate']
                    if rate_info is not None:
                        all_rates.append({'symbol': symbol.split('/')[0], 'rate': float(rate_info) * 100, 'exchange': name, 'period': period_info})
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
        [InlineKeyboardButton("🌐 Біржі", callback_data="settings_exchanges")],
        [InlineKeyboardButton(f"📊 Фандінг: > {settings['threshold']}%", callback_data="settings_threshold")],
        [InlineKeyboardButton("🚫 Чорний список", callback_data="blacklist_menu")],
        [InlineKeyboardButton("ℹ️ Довідка", url=HELP_URL)],
        [InlineKeyboardButton("↩️ Назад", callback_data="close_settings")]
    ])
def get_blacklist_menu_keyboard(blacklist: list):
    text = "🚫 Ваш чорний список:\n"
    if blacklist:
        text += "<code>" + ", ".join(blacklist) + "</code>"
    else:
        text += "<i>Порожній</i>"
    
    keyboard = [
        [InlineKeyboardButton("➕ Додати монету", callback_data="add_to_blacklist"), InlineKeyboardButton("➖ Видалити монету", callback_data="remove_from_blacklist")],
        [InlineKeyboardButton("↩️ Назад до налаштувань", callback_data="settings_menu")]
    ]
    return text, InlineKeyboardMarkup(keyboard)

# ... (інші клавіатури без змін)
def get_exchange_selection_keyboard(selected_exchanges: list):
    buttons = []; row = []
    for name in AVAILABLE_EXCHANGES.keys():
        text = f"✅ {name}" if name in selected_exchanges else f"☑️ {name}"
        row.append(InlineKeyboardButton(text, callback_data=f"toggle_exchange_{name}"))
        if len(row) == 2: buttons.append(row); row = []
    if row: buttons.append(row)
    buttons.append([InlineKeyboardButton("↩️ Назад", callback_data="settings_menu")])
    return InlineKeyboardMarkup(buttons)
def get_back_to_settings_keyboard(): return InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Назад", callback_data="settings_menu")]])
def get_ticker_menu_keyboard(ticker: str): return InlineKeyboardMarkup([[InlineKeyboardButton("🔄 Оновити", callback_data=f"refresh_ticker_{ticker}"), InlineKeyboardButton("↩️ Назад", callback_data="refresh")]])


# --- ФОРМАТУВАЛЬНИКИ ---
def get_trade_link(exchange: str, symbol: str) -> str:
    template = EXCHANGE_URL_TEMPLATES.get(exchange)
    if not template: return ""
    return template.format(symbol=f"{symbol}USDT", symbol_hyphen=f"{symbol}-USDT")

def format_funding_update(df: pd.DataFrame, threshold: float, blacklist: list) -> str:
    if df.empty: return "Не знайдено даних по фандінгу."
    # Фільтруємо чорний список
    df = df[~df['symbol'].isin(blacklist)]
    df['abs_rate'] = df['rate'].abs()
    # Знаходимо найкращу пропозицію для кожної монети
    best_offers = df.loc[df.groupby('symbol')['abs_rate'].idxmax()]
    filtered_df = best_offers[best_offers['abs_rate'] >= threshold].copy()
    filtered_df.sort_values('abs_rate', ascending=False, inplace=True)
    filtered_df = filtered_df.head(TOP_N)
    
    if filtered_df.empty: return f"🟢 Немає монет з фандингом вище <b>{threshold}%</b> або нижче <b>-{threshold}%</b> (поза чорним списком)."
    
    header = f"<b>💎 Топ-{len(filtered_df)} сигналів (поріг > {threshold}%)</b>"
    # Заголовки колонок
    titles = "<code>Монета    | Ставка     | Період | Біржа</code>"
    lines = []
    for _, row in filtered_df.iterrows():
        emoji = "🟢" if row['rate'] < 0 else "🔴"
        symbol_str = f"<code>{row['symbol']:<9}</code>"
        rate_str = f"<b>{row['rate']: >-8.4f}%</b>"
        period_str = f"<code>{row['period']:<6}</code>"
        link = get_trade_link(row['exchange'], row['symbol'])
        exchange_str = f'<a href="{link}">{row["exchange"]}</a>'
        lines.append(f"{emoji} {symbol_str} | {rate_str} | {period_str} | {exchange_str}")
    
    return f"{header}\n{titles}\n" + "\n".join(lines) + "\n" # Відступ знизу

def format_ticker_info(df: pd.DataFrame, ticker: str) -> str:
    if df.empty: return f"Не знайдено даних для <b>{html.escape(ticker)}</b>."
    header = f"<b>🪙 Фандінг для {html.escape(ticker.upper())}</b>"
    # Сортуємо за модулем ставки
    df['abs_rate'] = df['rate'].abs()
    df.sort_values('abs_rate', ascending=False, inplace=True)

    titles = "<code>Ставка     | Період | Біржа</code>"
    lines = []
    for _, row in df.iterrows():
        emoji = "🟢" if row['rate'] < 0 else "🔴"
        rate_str = f"<b>{row['rate']: >-8.4f}%</b>"
        period_str = f"<code>{row['period']:<6}</code>"
        link = get_trade_link(row['exchange'], row['symbol'])
        exchange_str = f'<a href="{link}">{row["exchange"]}</a>'
        lines.append(f"{emoji} {rate_str} | {period_str} | {exchange_str}")
    return f"{header}\n{titles}\n" + "\n".join(lines) + "\n"

# --- ОБРОБНИКИ ТЕЛЕГРАМ ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ... (код без змін)
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

# ... (інші обробники: spread, refresh, settings, close settings - без змін)
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

# ... (обробники діалогу зміни порогу та бірж - без змін)
async def set_threshold_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    settings = get_user_settings(query.message.chat.id)
    text = f"Зараз встановлено значення <b>{settings['threshold']}%</b>. Тобто бот надсилає сигнали з фандингом, більшим за +{settings['threshold']}% або меншим за -{settings['threshold']}%.\nНадішліть нове значення. Дробові значення вказуйте через крапку або кому."
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
        settings = get_user_settings(chat_id)
        await context.bot.send_message(chat_id, f"✅ Чудово! Встановлено нове порогове значення фандингу: <b>+/- {new_threshold}%</b>", parse_mode=ParseMode.HTML)
        await context.bot.send_message(chat_id, "⚙️ <b>Налаштування</b>", parse_mode=ParseMode.HTML, reply_markup=get_settings_menu_keyboard(settings))
    except (ValueError, TypeError):
        await update.message.reply_text("Некоректне значення. Спробуйте ще раз (напр., 0.5).")
        return SET_THRESHOLD_STATE
    return ConversationHandler.END
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

# --- НОВІ ОБРОБНИКИ ДЛЯ ЧОРНОГО СПИСКУ ---
async def blacklist_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    settings = get_user_settings(query.message.chat.id)
    text, keyboard = get_blacklist_menu_keyboard(settings.get('blacklist', []))
    await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=keyboard)

async def add_to_blacklist_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    await query.edit_message_text("Надішліть назви монет (тікери), які потрібно додати до чорного списку. Можна кілька, через пробіл або кому (напр., `BTC, ETH`).", reply_markup=get_back_to_settings_keyboard())
    return ADD_TO_BLACKLIST_STATE

async def add_to_blacklist_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: return ConversationHandler.END
    chat_id = update.effective_chat.id
    settings = get_user_settings(chat_id)
    blacklist = settings.get('blacklist', [])
    # Додаємо нові монети, прибираючи дублікати
    new_tickers = {t.strip().upper() for t in update.message.text.replace(",", " ").split()}
    blacklist.extend(list(new_tickers - set(blacklist)))
    update_user_setting(chat_id, 'blacklist', blacklist)
    
    await update.message.delete()
    await context.bot.delete_message(chat_id, update.message.reply_to_message.message_id)
    
    text, keyboard = get_blacklist_menu_keyboard(blacklist)
    await context.bot.send_message(chat_id, text, parse_mode=ParseMode.HTML, reply_markup=keyboard)
    return ConversationHandler.END

async def remove_from_blacklist_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    await query.edit_message_text("Надішліть назви монет (тікери), які потрібно видалити з чорного списку (через пробіл або кому).", reply_markup=get_back_to_settings_keyboard())
    return REMOVE_FROM_BLACKLIST_STATE

async def remove_from_blacklist_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: return ConversationHandler.END
    chat_id = update.effective_chat.id
    settings = get_user_settings(chat_id)
    blacklist = settings.get('blacklist', [])
    tickers_to_remove = {t.strip().upper() for t in update.message.text.replace(",", " ").split()}
    
    # Видаляємо монети
    blacklist = [t for t in blacklist if t not in tickers_to_remove]
    update_user_setting(chat_id, 'blacklist', blacklist)

    await update.message.delete()
    await context.bot.delete_message(chat_id, update.message.reply_to_message.message_id)
    
    text, keyboard = get_blacklist_menu_keyboard(blacklist)
    await context.bot.send_message(chat_id, text, parse_mode=ParseMode.HTML, reply_markup=keyboard)
    return ConversationHandler.END


# ... (обробник пошуку по тикеру без змін)
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


# --- ГОЛОВНА ФУНКЦІЯ ЗАПУСКУ ---
def main() -> None:
    load_dotenv(); TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
    if not TOKEN: logger.critical("!!! НЕ ЗНАЙДЕНО TOKEN !!!"); return
    application = Application.builder().token(TOKEN).build()
    
    # Створюємо два окремі діалоги
    threshold_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(set_threshold_callback, pattern="^settings_threshold$")],
        states={SET_THRESHOLD_STATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_threshold_conversation)]},
        fallbacks=[CallbackQueryHandler(settings_menu_callback, pattern="^settings_menu$")],
        per_message=False
    )
    blacklist_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(add_to_blacklist_callback, pattern="^add_to_blacklist$"),
                      CallbackQueryHandler(remove_from_blacklist_callback, pattern="^remove_from_blacklist$")],
        states={
            ADD_TO_BLACKLIST_STATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_to_blacklist_conversation)],
            REMOVE_FROM_BLACKLIST_STATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, remove_from_blacklist_conversation)]
        },
        fallbacks=[CallbackQueryHandler(settings_menu_callback, pattern="^settings_menu$")],
        per_message=False
    )
    
    # Реєструємо всі обробники
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
    
    logger.info("Бот запускається (версія 2.1)...")
    application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()