import numpy as np
import pandas as pd

from app.stats.factors import (current_drawdown, ewma_vol, factor_frame,
                               score_series, verdict)


def _trend(drift, n=600, seed=7):
    rng = np.random.default_rng(seed)
    t = np.arange(n)
    return pd.Series(100 * np.exp(drift * t + rng.normal(0, 0.005, n)))


def test_tendencia_de_alta_e_baixa():
    up = score_series(_trend(0.001)).iloc[-1]
    dn = score_series(_trend(-0.001)).iloc[-1]
    assert up >= 30 and verdict(up) == "comprar"
    assert dn <= -30 and verdict(dn) == "vender"


def test_passeio_aleatorio():
    rng = np.random.default_rng(1)
    s = pd.Series(100 * np.exp(np.cumsum(rng.normal(0, 0.01, 600))))
    sc = score_series(s).iloc[-1]
    assert np.isfinite(sc) and abs(sc) < 60


def test_sem_antecipacao():
    c = _trend(0.0005, seed=11)
    full = score_series(c).iloc[:450].values
    cut = score_series(c.iloc[:450]).values
    assert np.allclose(full, cut, equal_nan=True)


def test_nan_ate_256():
    sc = score_series(_trend(0.001))
    assert sc.iloc[:256].isna().all()
    assert sc.iloc[257:].notna().all()


def test_preco_constante():
    c = pd.Series([50.0] * 600)
    assert score_series(c).iloc[-1] == 0
    assert ewma_vol(c, 252) == 0
    assert current_drawdown(c) == 0


def test_momentum_manual():
    c = pd.Series(np.arange(1.0, 601.0))
    assert np.isclose(factor_frame(c)["momentum"].iloc[300], 280 / 49 - 1)


def test_verdict():
    assert verdict(30) == "comprar"
    assert verdict(-30) == "vender"
    assert verdict(29.9) == "manter"


def test_drawdown():
    c = pd.Series(list(np.linspace(100, 150, 200)) + list(np.linspace(150, 120, 50)))
    assert np.isclose(current_drawdown(c), -0.2)


def test_ewma_vol_positiva():
    rng = np.random.default_rng(5)
    c = pd.Series(100 * np.exp(np.cumsum(rng.normal(0, 0.01, 400))))
    v = ewma_vol(c, 252)
    assert 0.08 < v < 0.35
