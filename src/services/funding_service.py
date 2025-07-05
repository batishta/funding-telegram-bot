# src/services/funding_service.py

import ccxt
import pandas as pd
import logging

logger = logging.getLogger(__name__)

def get_all_funding_data_sequential(enabled_exchanges: list) -> pd.DataFrame:
    """
    Послідовно отримує дані з усіх увімкнених бірж,
    використовуючи альтернативний метод для непідтримуваних.
    """
    logger.info(f"Запуск послідовного сканування для: {enabled_exchanges}")
    all_rates_list = []
    
    for name in enabled_exchanges:
        from src.config import AVAILABLE_EXCHANGES # Імпортуємо тут, щоб уникнути циклічних залежностей
        exchange_id = AVAILABLE_EXCHANGES.get(name)
        if not exchange_id:
            logger.warning(f"Пропускаю {name}: не знайдено ID в конфігурації.")
            continue

        try:
            logger.info(f"--- Обробка {name} ---")
            exchange = getattr(ccxt, exchange_id)({'timeout': 20000}) # Таймаут 20 сек
            
            # 1. Пробуємо стандартний, швидкий метод
            funding_rates_data = exchange.fetch_funding_rates()
            logger.info(f"   -> {name} підтримує fetch_funding_rates(). Обробка...")
            for symbol, data in funding_rates_data.items():
                if 'USDT' in symbol and data.get('fundingRate') is not None:
                    all_rates_list.append({
                        'symbol': symbol.split('/')[0],
                        'rate': data['fundingRate'] * 100,
                        'exchange': name
                    })

        except ccxt.NotSupported:
            # 2. Якщо стандартний метод не працює, використовуємо альтернативний
            logger.warning(f"   -> {name} не підтримує fetch_funding_rates(). Використовую альтернативний метод...")
            try:
                markets = exchange.load_markets()
                # Фільтруємо тільки безстрокові USDT свопи
                swap_symbols = [m['symbol'] for m in markets.values() if m.get('swap') and m.get('quote', '').upper() == 'USDT']
                if not swap_symbols: continue

                tickers = exchange.fetch_tickers(swap_symbols)
                for symbol, ticker in tickers.items():
                    rate_info = None
                    if 'fundingRate' in ticker:
                        rate_info = ticker['fundingRate']
                    # Деякі біржі ховають дані в полі 'info'
                    elif isinstance(ticker.get('info'), dict) and 'fundingRate' in ticker['info']:
                        rate_info = ticker['info']['fundingRate']

                    if rate_info is not None:
                        all_rates_list.append({
                            'symbol': symbol.split('/')[0],
                            'rate': float(rate_info) * 100,
                            'exchange': name
                        })
            except Exception as e:
                logger.error(f"   ! Помилка альтернативного методу для {name}: {e}")

        except Exception as e:
            logger.error(f"   ! Загальна помилка при обробці {name}: {e}")

    if not all_rates_list:
        return pd.DataFrame()
        
    df = pd.DataFrame(all_rates_list)
    df.drop_duplicates(subset=['symbol', 'exchange'], inplace=True, keep='first')
    return df

def get_funding_for_ticker_sequential(ticker: str, enabled_exchanges: list) -> pd.DataFrame:
    """Отримує дані для конкретного тикера, використовуючи основну функцію."""
    ticker_clean = ticker.upper().replace("USDT", "").replace("/", "")
    logger.info(f"Шукаю дані по тикеру {ticker_clean} на: {enabled_exchanges}")
    
    full_data = get_all_funding_data_sequential(enabled_exchanges)
    
    if full_data.empty:
        return pd.DataFrame()
        
    ticker_data = full_data[full_data['symbol'] == ticker_clean]
    return ticker_data.sort_values(by='rate', ascending=False)