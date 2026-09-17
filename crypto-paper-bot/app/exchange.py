import ccxt

_exchange = None


def get_exchange():
    global _exchange
    if _exchange is None:
        _exchange = ccxt.binance({"enableRateLimit": True})
    return _exchange


def fetch_ohlcv(symbol: str, timeframe: str, limit: int = 100):
    """Retorna lista de candles [timestamp, open, high, low, close, volume]."""
    return get_exchange().fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)


def fetch_last_price(symbol: str) -> float:
    ticker = get_exchange().fetch_ticker(symbol)
    return float(ticker["last"])


def fetch_ticker_stats(symbol: str) -> dict:
    """Estatísticas de 24h: preço atual, variação absoluta e percentual."""
    ticker = get_exchange().fetch_ticker(symbol)
    return {
        "last": ticker.get("last"),
        "change": ticker.get("change"),
        "percentage": ticker.get("percentage"),
    }


def list_symbols() -> list[str]:
    markets = get_exchange().load_markets()
    return sorted(
        s for s, m in markets.items() if m.get("spot") and m.get("quote") == "USDT"
    )
