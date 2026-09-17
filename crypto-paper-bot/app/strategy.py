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


def _wilder_smooth(values: list[float], period: int) -> list[float]:
    """Soma suavizada de Wilder: primeiro valor é a soma simples do período,
    os seguintes são prev - prev/period + atual. Usada para TR/+DM/-DM, onde
    só a RAZÃO entre séries importa (a escala de soma cancela no cálculo do DI)."""
    smoothed = [sum(values[:period])]
    for v in values[period:]:
        smoothed.append(smoothed[-1] - smoothed[-1] / period + v)
    return smoothed


def _wilder_average(values: list[float], period: int) -> list[float]:
    """Média suavizada de Wilder: primeiro valor é a média simples do período,
    os seguintes são (prev*(period-1) + atual) / period. Usada pra série final
    do ADX, que precisa ficar na escala 0-100."""
    if len(values) < period:
        return []
    avg = sum(values[:period]) / period
    result = [avg]
    for v in values[period:]:
        avg = (avg * (period - 1) + v) / period
        result.append(avg)
    return result


def adx(highs: list[float], lows: list[float], closes: list[float], period: int = 14) -> float | None:
    """
    Average Directional Index (Wilder). Mede a FORÇA da tendência (não a direção):
    valores baixos (< ~20) indicam mercado lateral/sem tendência definida,
    valores altos (> ~25) indicam tendência forte, seja de alta ou de baixa.
    """
    n = len(closes)
    if n < period * 2 + 1:
        return None

    trs, plus_dms, minus_dms = [], [], []
    for i in range(1, n):
        high, low, prev_close = highs[i], lows[i], closes[i - 1]
        prev_high, prev_low = highs[i - 1], lows[i - 1]

        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        up_move = high - prev_high
        down_move = prev_low - low
        plus_dm = up_move if (up_move > down_move and up_move > 0) else 0.0
        minus_dm = down_move if (down_move > up_move and down_move > 0) else 0.0

        trs.append(tr)
        plus_dms.append(plus_dm)
        minus_dms.append(minus_dm)

    smoothed_tr = _wilder_smooth(trs, period)
    smoothed_plus_dm = _wilder_smooth(plus_dms, period)
    smoothed_minus_dm = _wilder_smooth(minus_dms, period)

    dxs = []
    for tr, pdm, mdm in zip(smoothed_tr, smoothed_plus_dm, smoothed_minus_dm):
        if tr == 0:
            dxs.append(0.0)
            continue
        plus_di = 100 * pdm / tr
        minus_di = 100 * mdm / tr
        di_sum = plus_di + minus_di
        dx = 100 * abs(plus_di - minus_di) / di_sum if di_sum else 0.0
        dxs.append(dx)

    adx_values = _wilder_average(dxs, period)
    if not adx_values:
        return None
    return adx_values[-1]


def _rsi_series(closes: list[float], period: int) -> list[float]:
    if len(closes) < period + 1:
        return []
    gains, losses = [], []
    for i in range(1, len(closes)):
        change = closes[i] - closes[i - 1]
        gains.append(max(change, 0.0))
        losses.append(max(-change, 0.0))

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    rsi_values = []
    for gain, loss in zip(gains[period:], losses[period:]):
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
        rs = avg_gain / avg_loss if avg_loss != 0 else float("inf")
        rsi_values.append(100 - (100 / (1 + rs)))
    return rsi_values


def rsi_signal(closes: list[float], period: int, oversold: float, overbought: float) -> str | None:
    """
    Estratégia de reversão à média: compra quando o RSI sobe de volta acima da
    linha de sobrevenda (mercado estava fraco e virou), vende quando o RSI cai
    de volta abaixo da linha de sobrecompra (mercado estava forte e virou).
    Funciona melhor em mercado lateral (por isso combina com ADX baixo).
    """
    rsi_values = _rsi_series(closes, period)
    if len(rsi_values) < 2:
        return None
    prev, now = rsi_values[-2], rsi_values[-1]
    if prev <= oversold < now:
        return "buy"
    if prev >= overbought > now:
        return "sell"
    return None


def ema_series(values: list[float], period: int) -> list[float]:
    if len(values) < period:
        return []
    k = 2 / (period + 1)
    ema_values = [sum(values[:period]) / period]
    for v in values[period:]:
        ema_values.append(v * k + ema_values[-1] * (1 - k))
    return ema_values


def macd_crossover_signal(closes: list[float], fast: int, slow: int, signal: int) -> str | None:
    """
    Segue tendência, como o cruzamento de SMA, mas usa médias exponenciais
    (mais peso pra velas recentes) e a linha de sinal em vez de uma segunda SMA.
    Compra quando a linha MACD cruza a linha de sinal de baixo pra cima.
    """
    ema_fast = ema_series(closes, fast)
    ema_slow = ema_series(closes, slow)
    if not ema_fast or not ema_slow:
        return None
    offset = len(ema_fast) - len(ema_slow)
    macd_line = [f - s for f, s in zip(ema_fast[offset:], ema_slow)]
    signal_line = ema_series(macd_line, signal)
    if len(signal_line) < 2:
        return None

    macd_tail = macd_line[-len(signal_line):]
    macd_prev, macd_now = macd_tail[-2], macd_tail[-1]
    signal_prev, signal_now = signal_line[-2], signal_line[-1]

    if macd_prev <= signal_prev and macd_now > signal_now:
        return "buy"
    if macd_prev >= signal_prev and macd_now < signal_now:
        return "sell"
    return None


def bollinger_reversion_signal(closes: list[float], period: int, num_std: float) -> str | None:
    """
    Estratégia de reversão à média: compra quando o preço toca a banda inferior
    e volta pra dentro (repique de sobrevenda), vende quando toca a banda
    superior e volta pra dentro (repique de sobrecompra). Também funciona
    melhor em mercado lateral.
    """
    if len(closes) < period + 2:
        return None

    def bands(series: list[float]) -> tuple[float, float]:
        window = series[-period:]
        mean = sum(window) / period
        variance = sum((x - mean) ** 2 for x in window) / period
        std = variance ** 0.5
        return mean - num_std * std, mean + num_std * std

    lower_prev, upper_prev = bands(closes[:-1])
    lower_now, upper_now = bands(closes)
    close_prev, close_now = closes[-2], closes[-1]

    if close_prev <= lower_prev and close_now > lower_now:
        return "buy"
    if close_prev >= upper_prev and close_now < upper_now:
        return "sell"
    return None
