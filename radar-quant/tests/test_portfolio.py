import math

import numpy as np
import pandas as pd
import pytest

from app.stats.portfolio import (
    METHODS,
    PortfolioError,
    apply_cap,
    build_portfolio,
    ledoit_wolf,
    min_variance,
    risk_parity,
)


def _rand_cov(n=5, seed=1):
    a = np.random.default_rng(seed).normal(size=(n, n))
    return a @ a.T + n * np.eye(n)


def _returns(n=4, t=160, seed=7):
    rng = np.random.default_rng(seed)
    data = rng.normal(0.002, 0.02, size=(t, n)) + rng.normal(0, 0.01, size=(t, 1))
    idx = pd.date_range("2022-01-07", periods=t, freq="W-FRI")
    return pd.DataFrame(data, index=idx, columns=[f"A{i}" for i in range(n)])


def test_ledoit_wolf_simetrica_pd_e_traco():
    x = np.random.default_rng(0).normal(size=(120, 5))
    cov = ledoit_wolf(x)
    assert np.allclose(cov, cov.T)
    assert np.linalg.eigvalsh(cov).min() > 0
    sample = np.cov(x, rowvar=False, bias=True)
    assert np.trace(cov) == pytest.approx(np.trace(sample), rel=1e-6)


def test_ledoit_wolf_colunas_identicas():
    base = np.random.default_rng(1).normal(size=(80, 1))
    x = np.hstack([base, base, base])
    assert np.linalg.eigvalsh(np.cov(x, rowvar=False, bias=True)).min() == pytest.approx(0, abs=1e-12)
    assert np.linalg.eigvalsh(ledoit_wolf(x)).min() > 1e-8


def test_risk_parity_diagonal():
    w = risk_parity(np.diag([0.04, 0.01]))
    assert w == pytest.approx([1 / 3, 2 / 3], abs=1e-6)


def test_risk_parity_contribuicoes_iguais():
    cov = _rand_cov()
    w = risk_parity(cov)
    rc = w * (cov @ w)
    assert (w >= 0).all() and w.sum() == pytest.approx(1)
    assert np.abs(rc / rc.sum() - 1 / 5).max() < 1e-4


def test_min_variance_diagonal():
    w = min_variance(np.diag([0.04, 0.01]))
    assert w == pytest.approx([0.2, 0.8], abs=1e-6)


def test_min_variance_long_only():
    # cov01 > menor variância: a solução irrestrita seria [-0.2, 1.2]
    cov = np.array([[0.16, 0.10], [0.10, 0.09]])
    w = min_variance(cov)
    assert w == pytest.approx([0.0, 1.0], abs=1e-6)
    assert (w >= 0).all() and w.sum() == pytest.approx(1)


def test_apply_cap():
    w = apply_cap(np.array([0.7, 0.2, 0.1]), 0.35)
    assert w.max() <= 0.35 + 1e-12 and w.sum() == pytest.approx(1)
    ok = np.array([0.3, 0.3, 0.4 - 0.05, 0.05])
    assert apply_cap(ok, 0.35) == pytest.approx(ok)


@pytest.mark.parametrize("method", METHODS)
def test_build_portfolio_quatro_ativos(method):
    r = _returns()
    out = build_portfolio(r, method)
    w = out["weights"]
    assert set(w) == set(r.columns)
    assert sum(w.values()) == pytest.approx(1)
    assert max(w.values()) <= 0.35 + 1e-9
    m = np.array(out["correlation"]["matrix"])
    assert m.shape == (4, 4) and np.allclose(np.diag(m), 1)
    assert out["correlation"]["labels"] == list(r.columns)
    assert all(math.isfinite(v) for v in out["stats"].values())
    assert out["weeks"] == 160


def test_build_portfolio_dois_ativos_sem_teto():
    out = build_portfolio(_returns(n=2), "risk_parity")
    assert max(out["weights"].values()) > 0.35
    assert sum(out["weights"].values()) == pytest.approx(1)


def test_build_portfolio_erros():
    with pytest.raises(PortfolioError):
        build_portfolio(_returns(n=1), "risk_parity")
    with pytest.raises(PortfolioError):
        build_portfolio(_returns(t=30), "risk_parity")
    with pytest.raises(PortfolioError):
        build_portfolio(_returns(), "x")


@pytest.mark.parametrize("method", METHODS)
def test_coluna_constante_sem_nan(method):
    r = _returns()
    r["A0"] = 0.001
    out = build_portfolio(r, method)
    flat = list(out["weights"].values()) + list(out["stats"].values())
    flat += [v for row in out["correlation"]["matrix"] for v in row]
    assert all(math.isfinite(v) for v in flat)
    assert out["correlation"]["matrix"][0][1] == 0
