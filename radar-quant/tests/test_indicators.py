import numpy as np
import pandas as pd

from app.stats.indicators import bollinger, ema, macd, rsi, sma


def test_sma_basico():
    r = sma(pd.Series([1, 2, 3, 4, 5], dtype=float), 3)
    assert np.allclose(r.values, [np.nan, np.nan, 2, 3, 4], equal_nan=True)


def test_ema_constante():
    s = pd.Series([7.0] * 50)
    assert np.allclose(ema(s, 10), 7.0)


def test_rsi_extremos():
    up = pd.Series(np.arange(1.0, 101.0))
    assert rsi(up).iloc[-1] == 100
    assert rsi(up[::-1].reset_index(drop=True)).iloc[-1] == 0
    assert rsi(pd.Series([5.0] * 100)).iloc[-1] == 50


def test_bollinger_constante():
    b = bollinger(pd.Series([3.0] * 60))
    ok = b.dropna()
    assert len(ok) > 0
    assert (ok["upper"] == ok["lower"]).all() and (ok["upper"] == ok["mid"]).all()


def test_macd_hist():
    s = pd.Series(100 + np.cumsum(np.random.default_rng(1).normal(size=200)))
    m = macd(s)
    assert list(m.columns) == ["macd", "signal", "hist"]
    assert np.allclose(m["hist"], m["macd"] - m["signal"])
    assert m.index.equals(s.index)
