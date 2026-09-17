def sma(values: list[float], period: int) -> float | None:
    if len(values) < period:
        return None
    return sum(values[-period:]) / period


def sma_crossover_signal(closes: list[float], fast_period: int, slow_period: int) -> str | None:
    """
    Retorna 'buy', 'sell' ou None comparando a última vela com a anterior:
    'buy'  quando a SMA rápida cruza a lenta de baixo para cima
    'sell' quando a SMA rápida cruza a lenta de cima para baixo
    """
    if len(closes) < slow_period + 1:
        return None

    fast_prev = sma(closes[:-1], fast_period)
    slow_prev = sma(closes[:-1], slow_period)
    fast_now = sma(closes, fast_period)
    slow_now = sma(closes, slow_period)

    if None in (fast_prev, slow_prev, fast_now, slow_now):
        return None

    if fast_prev <= slow_prev and fast_now > slow_now:
        return "buy"
    if fast_prev >= slow_prev and fast_now < slow_now:
        return "sell"
    return None
