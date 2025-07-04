# src/services/funding_service.py
# ЗАЛИШТЕ ЦЕЙ ФАЙЛ ТАКИМ, ЯК ВІН БУВ У ПОПЕРЕДНЬОМУ ПОВІДОМЛЕННІ
# (з функцією get_all_funding_data_SEQUENTIAL)
import ccxt
import pandas as pd
import logging
from typing import List, Dict, Any
from ..config import AVAILABLE_EXCHANGES

logger = logging.getLogger(__name__)

def get_all_funding_data_sequential(enabled_exchanges: List[str]) -> pd.DataFrame:
    """
    ДУЖЕ ПРОСТА І ПОВІЛЬНА функція.
    Запитує дані з бірж ОДНА ЗА ОДНОЮ, послідовно.
    """
    logger.info(f"!!! ЗАПУСК В РЕЖИМІ ДІАГНОСТИКИ (ПОСЛІДОВНИЙ) !!!")
    all_rates_list = []
    
    for name in enabled_exchanges:
        logger.info(f"--- Починаю обробку біржі: {name} ---")
        exchange_id = AVAILABLE_EXCHANGES.get(name)
        if not exchange_id:
            logger.warning(f"Пропускаю {name}: не знайдено ID в конфігурації.")
            continue
            
        try:
            exchange_class = getattr(ccxt, exchange_id)
            exchange = exchange_class({'timeout': 30000}) # Таймаут 30 сек
            
            logger.info(f"    -> Завантажую дані з {name}...")
            funding_rates_data = exchange.fetch_funding_rates()
            logger.info(f"    <- Дані з {name} отримано. Обробляю...")
            
            for symbol, data in funding_rates_data.items():
                if 'USDT' in symbol and data.get('fundingRate') is not None:
                    all_rates_list.append({
                        'symbol': symbol.replace('/USDT:USDT', '').replace(':USDT', ''),
                        'rate': data['fundingRate'] * 100,
                        'next_funding_time': pd.to_datetime(data.get('nextFundingTimestamp'), unit='ms', utc=True) if data.get('nextFundingTimestamp') else None,
                        'exchange': name
                    })
            logger.info(f"--- Обробка {name} завершена. Отримано {len(all_rates_list)} ставок. ---")

        except Exception as e:
            logger.error(f"!!! ПОМИЛКА під час обробки {name}: {e} !!!", exc_info=True)
            continue
            
    if not all_rates_list:
        logger.warning("Не вдалося отримати дані з жодної біржі.")
        return pd.DataFrame()
        
    df = pd.DataFrame(all_rates_list)
    df.drop_duplicates(subset=['symbol', 'exchange'], inplace=True, keep='first')
    return df