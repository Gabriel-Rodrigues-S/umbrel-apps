"""Fatores, score e veredito. Todo valor em t usa apenas dados até t."""
import numpy as np
import pandas as pd
from numpy.lib.stride_tricks import sliding_window_view

from app.stats.indicators import sma

MIN_CANDLES = 300
BUY_THRESHOLD = 30.0
SELL_THRESHOLD = -30.0
WEIGHTS = {"momentum": 0.35, "trend": 0.35, "dist_sma200": 0.20, "reversal": 0.10}
SCALES = {"momentum": 0.30, "trend": 20.0, "dist_sma200": 0.15, "reversal": 2.0}
LABELS = {
    "momentum": "Momentum 12-1",
    "trend": "Tendência (126 d)",
    "dist_sma200": "Distância da média de 200",
    "reversal": "Reversão (5 d)",
}

TREND_WINDOW = 126
_SAT = 1e6  # estatística t "infinita" quando o ajuste é perfeito


def _trend_tstat(close: pd.Series) -> pd.Series:
    """Estatística t da inclinação da regressão de log(preço) na janela de 126 dias."""
    n = TREND_WINDOW
    y = np.log(close.to_numpy(dtype=float))
    out = np.full(len(y), np.nan)
    if len(y) < n:
        return pd.Series(out, index=close.index)
    w = sliding_window_view(y, n)
    xc = np.arange(n) - (n - 1) / 2
    sxx = (xc**2).sum()
    yc = w - w.mean(axis=1, keepdims=True)
    slope = yc @ xc / sxx
    ssr = ((yc - slope[:, None] * xc) ** 2).sum(axis=1)
    perfect = ssr < 1e-20  # tolerância numérica para "SSR == 0"
    se = np.sqrt(np.where(perfect, 1.0, ssr) / (n - 2)) / np.sqrt(sxx)
    t = np.where(
        perfect,
        np.where(np.abs(slope) < 1e-12, 0.0, np.sign(slope) * _SAT),
        slope / se,
    )
    out[n - 1:] = t
    return pd.Series(out, index=close.index)


def factor_frame(close: pd.Series) -> pd.DataFrame:
    momentum = close.shift(21) / close.shift(252) - 1
    r5 = close.pct_change(5, fill_method=None)
    mu = r5.rolling(252).mean()
    sd = r5.rolling(252).std()
    reversal = (-(r5 - mu) / sd.where(sd > 0)).where(sd != 0, 0.0)
    return pd.DataFrame(
        {
            "momentum": momentum,
            "trend": _trend_tstat(close),
            "dist_sma200": close / sma(close, 200) - 1,
            "reversal": reversal,
        }
    )[list(WEIGHTS)]


def normalize(raw: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame({c: np.tanh(raw[c] / SCALES[c]) for c in WEIGHTS})


def score_series(close: pd.Series) -> pd.Series:
    norm = normalize(factor_frame(close))
    total = sum(WEIGHTS[c] * norm[c] for c in WEIGHTS)  # NaN se algum fator for NaN
    return 100 * total


def verdict(score: float) -> str:
    if score >= BUY_THRESHOLD:
        return "comprar"
    if score <= SELL_THRESHOLD:
        return "vender"
    return "manter"


def ewma_vol(close: pd.Series, periods_per_year: int, lam: float = 0.94) -> float:
    """Volatilidade EWMA anualizada; variância inicial = amostral dos 20 primeiros retornos."""
    r = close.pct_change(fill_method=None).dropna().to_numpy(dtype=float)
    if len(r) < 20:
        return float("nan")
    var = r[:20].var(ddof=1)
    for x in r[20:]:
        var = lam * var + (1 - lam) * x * x
    return float(np.sqrt(var * periods_per_year))


def current_drawdown(close: pd.Series, window: int = 252) -> float:
    recent = close.iloc[-window:]
    return float(close.iloc[-1] / recent.max() - 1)
