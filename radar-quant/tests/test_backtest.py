import numpy as np
import pandas as pd
import pytest

from app.stats.backtest import (
    block_bootstrap_ci,
    perf_stats,
    positions_from_score,
    run_backtest,
)


def _idx(n):
    return pd.bdate_range("2024-01-01", periods=n)


def _close_from_rets(rets):
    return pd.Series(100 * np.cumprod(1 + np.asarray(rets)), index=_idx(len(rets)))


def test_positions_hysteresis():
    s = pd.Series([0, 35, 10, -10, -31, 0, 30], dtype=float)
    assert positions_from_score(s).tolist() == [0, 1, 1, 1, 0, 0, 1]


def test_positions_nan_keeps_previous():
    s = pd.Series([0, 35, np.nan, 10, -40, np.nan], dtype=float)
    assert positions_from_score(s).tolist() == [0, 1, 1, 1, 0, 0]


def test_no_lookahead_last_close_does_not_change_past():
    rng = np.random.default_rng(0)
    close = _close_from_rets(rng.normal(0, 0.01, 80))
    score = pd.Series(rng.uniform(-60, 60, 80), index=close.index)
    a = run_backtest(close, score, None, 252, n_boot=50)
    close2 = close.copy()
    close2.iloc[-1] *= 1.5
    b = run_backtest(close2, score, None, 252, n_boot=50)
    pd.testing.assert_frame_equal(a.equity.iloc[:-1], b.equity.iloc[:-1])


def test_signal_day_k_captures_return_of_k_plus_1():
    n, k = 60, 20
    rets = np.full(n, 0.01)
    close = _close_from_rets(rets)
    score = pd.Series(0.0, index=close.index)
    score.iloc[k:] = 35.0
    r = run_backtest(close, score, None, 252, cost=0.0, n_boot=50)
    eq = r.equity["strategy"]
    assert eq.iloc[k] == pytest.approx(eq.iloc[k - 1])
    assert eq.iloc[k + 1] == pytest.approx(eq.iloc[k] * 1.01)


def test_always_long_matches_buy_hold():
    rng = np.random.default_rng(1)
    close = _close_from_rets(rng.normal(0.0005, 0.01, 100))
    score = pd.Series(100.0, index=close.index)
    r = run_backtest(close, score, None, 252, cost=0.0, n_boot=50)
    np.testing.assert_allclose(r.equity["strategy"], r.equity["buy_hold"], atol=1e-9)
    assert r.trades == 1
    assert r.hit_rate is None
    assert r.equity.iloc[0].tolist() == [1.0, 1.0]


def test_always_flat_cash_and_rf():
    rng = np.random.default_rng(2)
    close = _close_from_rets(rng.normal(0, 0.01, 80))
    score = pd.Series(0.0, index=close.index)
    r = run_backtest(close, score, None, 252, n_boot=50)
    assert r.trades == 0 and r.time_in_market == 0 and r.hit_rate is None
    assert r.strategy["ann_return"] == 0
    rf = pd.Series(0.0004, index=close.index)
    r2 = run_backtest(close, score, rf, 252, n_boot=50)
    assert r2.strategy["ann_return"] == pytest.approx(1.0004**252 - 1)


def test_entry_cost_reduces_equity_by_cost():
    close = _close_from_rets(np.full(60, 0.002))
    score = pd.Series(0.0, index=close.index)
    score.iloc[10:] = 40.0
    r0 = run_backtest(close, score, None, 252, cost=0.0, n_boot=50)
    r1 = run_backtest(close, score, None, 252, cost=0.01, n_boot=50)
    ratio = r1.equity["strategy"] / r0.equity["strategy"]
    assert ratio.iloc[11] == pytest.approx(0.99, abs=1e-4)  # custo subtrai do retorno do dia
    assert ratio.iloc[10] == pytest.approx(1.0)


def test_hit_rate_two_closed_trades():
    n = 60
    rets = np.full(n, 0.0)
    rets[6:16] = 0.01
    rets[26:36] = -0.01
    close = _close_from_rets(rets)
    score = pd.Series(0.0, index=close.index)
    score.iloc[5:15] = 35.0
    score.iloc[15] = -35.0
    score.iloc[25:35] = 35.0
    score.iloc[35] = -35.0
    r = run_backtest(close, score, None, 252, cost=0.0, n_boot=50)
    assert r.trades == 2
    assert r.hit_rate == 0.5


def test_bootstrap_deterministic_and_seed_sensitive():
    x = np.random.default_rng(3).normal(0, 0.01, 500)
    a = block_bootstrap_ci(x, 252, seed=1)
    assert a == block_bootstrap_ci(x, 252, seed=1)
    assert a != block_bootstrap_ci(x, 252, seed=2)


def test_bootstrap_constant_series():
    mean, lo, hi = block_bootstrap_ci(np.full(300, 0.001), 252)
    assert mean == pytest.approx(0.252)
    assert lo == pytest.approx(0.252) and hi == pytest.approx(0.252)


def test_bootstrap_iid_ci_contains_zero():
    x = np.random.default_rng(4).normal(0, 0.01, 2000)
    _, lo, hi = block_bootstrap_ci(x, 252)
    assert lo < 0 < hi


def test_evidence_favoravel_and_contraria():
    close = _close_from_rets(np.full(80, -0.01))
    score = pd.Series(0.0, index=close.index)
    rf = pd.Series(0.0004, index=close.index)
    assert run_backtest(close, score, rf, 252, n_boot=100).evidence == "favoravel"
    close_up = _close_from_rets(np.full(80, 0.01))
    r = run_backtest(close_up, score, None, 252, n_boot=100)
    assert r.evidence == "contraria"
    assert r.ci_high < 0


def test_insufficient_history_raises():
    close = _close_from_rets(np.full(25, 0.001))
    score = pd.Series(0.0, index=close.index)
    with pytest.raises(ValueError, match="histórico insuficiente"):
        run_backtest(close, score, None, 252)
    score2 = pd.Series(np.nan, index=close.index)
    score2.iloc[-10:] = 0.0
    long_close = _close_from_rets(np.full(100, 0.001))
    score3 = pd.Series(np.nan, index=long_close.index)
    score3.iloc[-10:] = 0.0
    with pytest.raises(ValueError):
        run_backtest(long_close, score3, None, 252)


def test_constant_price_no_nan():
    close = pd.Series(10.0, index=_idx(60))
    score = pd.Series(0.0, index=close.index)
    r = run_backtest(close, score, None, 252, n_boot=50)
    for d in (r.strategy, r.buy_hold):
        assert all(np.isfinite(v) for v in d.values())
        assert d["sharpe"] == 0
    assert r.evidence == "sem_evidencia"
    assert (r.ci_low, r.ci_high) == (0.0, 0.0)
    assert np.isfinite(r.equity.to_numpy()).all()


def test_perf_stats_zero_std_and_drawdown():
    ret = pd.Series([0.1, -0.5, 0.1])
    s = perf_stats(ret, pd.Series(0.0, index=ret.index), 252)
    assert s["max_drawdown"] == pytest.approx(-0.5)
    assert perf_stats(pd.Series(0.0, index=range(5)), pd.Series(0.0, index=range(5)), 252)["sharpe"] == 0.0
