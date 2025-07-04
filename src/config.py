# src/config.py

# Список всіх доступних бірж та їх ID в ccxt
AVAILABLE_EXCHANGES = {
    'Binance': 'binanceusdm',
    'ByBit': 'bybit',
    'MEXC': 'mexc',
    'OKX': 'okx',
    'Bitget': 'bitget',
    'KuCoin': 'kucoinfutures',
    'Gate.io': 'gate',
    'Huobi': 'huobi',
    'BingX': 'bingx',
    'CoinEx': 'coinex',
    'Bitmart': 'bitmart',
}

# Шаблони URL для переходу на сторінку торгівлі
# {symbol} буде замінено на тикер, напр. BTCUSDT
EXCHANGE_URL_TEMPLATES = {
    'Binance': 'https://www.binance.com/en/futures/{symbol}',
    'ByBit': 'https://www.bybit.com/trade/usdt/{symbol}',
    'MEXC': 'https://futures.mexc.com/exchange/{symbol}_USDT',
    'OKX': 'https://www.okx.com/trade-swap/{symbol_hyphen}', # OKX використовує формат BTC-USDT
    'Bitget': 'https://www.bitget.com/futures/usdt/{symbol}usdt',
    'KuCoin': 'https://www.kucoin.com/futures/trade/{symbol}',
    'Gate.io': 'https://www.gate.io/futures_trade/USDT/{symbol}_USDT',
    'Huobi': 'https://futures.huobi.com/en-us/linear_swap/exchange/swap_trade/?contract_code={symbol}-USDT',
    'BingX': 'https://swap.bingx.com/en-us/{symbol}-USDT',
    'CoinEx': 'https://www.coinex.com/futures/{symbol}-usdt-swap',
    'Bitmart': 'https://futures.bitmart.com/en-US/trade/{symbol}',
}

# Налаштування за замовчуванням для нових користувачів
DEFAULT_SETTINGS = {
    "enabled": True,  # Бот ON/OFF
    "threshold": 0.3, # Поріг фандінгу в %
    "interval": 60,   # Інтервал оновлення в хвилинах
    "exchanges": ['Binance', 'ByBit', 'OKX', 'MEXC', 'Bitget', 'KuCoin'] # Основний список бірж
}