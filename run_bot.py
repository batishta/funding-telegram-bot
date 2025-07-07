# run_bot.py (Версія 3.0 - фінальний редизайн)

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
BOT_VERSION = "v3.0"

# --- КОНФІГУРАЦІЯ ---
# ... (без змін)
AVAILABLE_EXCHANGES = {'Binance': 'binanceusdm', 'ByBit': 'bybit', 'MEXC': 'mexc', 'OKX': 'okx', 'Bitget': 'bitget', 'KuCoin': 'kucoinfutures', 'Gate.io': 'gate', 'Huobi': 'huobi', 'BingX': 'bingx'}
EXCHANGE_URL_TEMPLATES = {
    'Binance': 'https://www.binance.com/en/futures/{symbol}', 'ByBit': 'https://www.bybit.com/trade/usdt/{symbol}',
    'MEXC': 'https://futures.mexc.com/exchange/{symbol_base}_USDT', 'OKX': 'https://www.okx.com/trade-swap/{symbol_hyphen}',
    'Bitget': 'https://www.bitget.com/futures/usdt/{symbol}', 'KuCoin': 'https://www.kucoin.com/futures/trade/{symbol}',
    'Gate.io': 'https://www.gate.io/futures_trade/USDT/{symbol_base}_USDT', 'Huobi': 'https://futures.huobi.com/en-us/linear_swap/exchange/swap_trade/?contract_code={symbol}-USDT',
    'BingX': 'https://swap.bingx.com/en-us/{symbol}-USDT'
}
DEFAULT_SETTINGS = {"threshold": 0.3, "exchanges": ['Binance', 'ByBit', 'OKX', 'Bitget', 'KuCoin', 'MEXC', 'Gate.io'], "blacklist": []}
TOP_N = 10
(SET_THRESHOLD_STATE, ADD_TO_BLACKLIST_STATE, REMOVE_FROM_BLACKLIST_STATE) = range(3)
HELP_URL = "https://www.google.com/search?q=aistudio+google+com"


# --- СЕРВІСНІ ФУНКЦІЇ ---
def get_all_funding_data_sequential(enabled_exchanges: list) -> pd.DataFrame:
    all_rates = []
    # ... (код цієї функції не змінюється)
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
        # ВИПРАВЛЕНО: Форматування з відступами
        symbol_str = f"<pre> {row['symbol']:<11} </pre>" # Вирівнювання по лівому краю, 11 символів
        rate_str = f"<pre> {row['rate']: >-9.4f}% </pre>" # Вирівнювання по правому краю, 9 символів
        link = get_trade_link(row['exchange'], row['symbol'])
        exchange_str = f'<a href="{link}">{row["exchange"]}</a>'
        lines.append(f"{emoji} {symbol_str} | {rate_str} | {exchange_str}")
    
    footer = f"\n\n<i>{BOT_VERSION}</i>"
    return f"{header}\n\n" + "\n".join(lines) + footer

def format_ticker_info(df: pd.DataFrame, ticker: str) -> str:
    if df.empty: return f"Не знайдено даних для <b>{html.escape(ticker)}</b>."
    # ВИПРАВЛЕНО: Новий вигляд
    header = f"🪙 <code>{html.escape(ticker.upper())}</code>"
    df.sort_values(by='rate', ascending=False, inplace=True)
    lines = []
    for _, row in df.iterrows():
        emoji = "🟢" if row['rate'] < 0 else "🔴"
        # ВИПРАВЛЕНО: LONG/SHORT з посиланням
        link = get_trade_link(row['exchange'], row['symbol'])
        direction_str = f"<a href='{link}'>{'LONG' if row['rate'] < 0 else 'SHORT'}</a>"
        rate_str = f"<pre> {row['rate']: >-9.4f}% </pre>"
        exchange_str = f"{row['exchange']}"
        lines.append(f"{emoji}  {direction_str} | {rate_str} | {exchange_str}")
    return f"{header}\n\n" + "\n".join(lines) + "\n\n"

# --- ОБРОБНИКИ ТЕЛЕГРАМ ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message: return
    # ВИПРАВЛЕНО: Уникаємо дублювання повідомлень
    if context.user_data.get('main_menu_id') is not None:
        try:
            await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=context.user_data.get('main_menu_id'))
        except: pass
    
    message = await update.message.reply_text("👋 Вітаю! Оберіть режим роботи:", reply_markup=get_start_menu_keyboard())
    context.user_data['main_menu_id'] = message.message_id
# ... (всі інші обробники залишаються без змін, ви можете взяти їх з версії 2.5) ...
async def show_funding_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ...
async def show_funding_spread(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ...
# і так далі...

# --- ГОЛОВНА ФУНКЦІЯ ЗАПУСКУ ---
def main() -> None:
    # ... (без змін)