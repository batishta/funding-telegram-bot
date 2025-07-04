# src/services/formatters.py
import pandas as pd
import html
from ..config import EXCHANGE_URL_TEMPLATES

def get_trade_link(exchange: str, symbol: str) -> str:
    """Генерує посилання на сторінку торгівлі."""
    template = EXCHANGE_URL_TEMPLATES.get(exchange)
    if not template:
        return ""
    
    symbol_usdt = f"{symbol}USDT"
    symbol_hyphen = f"{symbol}-USDT"
    
    return template.format(symbol=symbol_usdt, symbol_hyphen=symbol_hyphen)

def format_funding_update(df: pd.DataFrame, threshold: float) -> str:
    """Форматує головне повідомлення з фандінгом."""
    if df.empty:
        return "Не знайдено даних по фандінгу для обраних бірж."

    filtered_df = df[abs(df['rate']) >= threshold].sort_values(by='rate', ascending=False)

    if filtered_df.empty:
        return f"🟢 Немає монет з фандінгом вище <b>{threshold}%</b> або нижче <b>-{threshold}%</b>."

    header = f"<b>💎 Фандінг вище {threshold}%</b>\n\n"
    lines = []
    
    for _, row in filtered_df.iterrows():
        emoji = "🟢" if row['rate'] > 0 else "🔴"
        symbol = html.escape(row['symbol'])
        rate = row['rate']
        time_str = row['next_funding_time'].strftime('%H:%M UTC') if pd.notna(row['next_funding_time']) else "N/A"
        exchange_name = html.escape(row['exchange'])
        link = get_trade_link(row['exchange'], row['symbol'])
        
        exchange_part = f'<a href="{link}">{exchange_name}</a>' if link else exchange_name

        lines.append(f"{emoji} <code>{symbol:<8}</code>— <b>{rate: >-7.4f}%</b> — {time_str} — {exchange_part}")

    return header + "\n".join(lines)

def format_ticker_info(df: pd.DataFrame, ticker: str) -> str:
    """Форматує повідомлення для конкретного тикера."""
    if df.empty:
        return f"Не знайдено даних для <b>{html.escape(ticker)}</b> на обраних біржах."
    
    header = f"<b>🪙 Фандінг для {html.escape(ticker.upper())}</b>\n\n"
    lines = []

    for _, row in df.iterrows():
        emoji = "🟢" if row['rate'] > 0 else "🔴"
        rate = row['rate']
        time_str = row['next_funding_time'].strftime('%H:%M UTC') if pd.notna(row['next_funding_time']) else "N/A"
        exchange_name = html.escape(row['exchange'])
        link = get_trade_link(row['exchange'], row['symbol'])
        
        exchange_part = f'<a href="{link}">{exchange_name}</a>' if link else exchange_name
        
        lines.append(f"{emoji} <b>{rate: >-7.4f}%</b> — {time_str} — {exchange_part}")
        
    return header + "\n".join(lines)