"""Backtest long/caixa com histerese e bootstrap em blocos para o IC do excesso."""
from dataclasses import dataclass

import numpy as np
import pandas as pd


def positions_from_score(score: pd.Series, buy: float = 30.0, sell: float = -30.0) -> pd.Series:
    """Posição 0/1 com histerese; começa em 0 e NaN mantém o valor anterior."""
    pos, out = 0.0, []
    for v in score.to_numpy(dtype=float):
        if v >= buy:
            pos = 1.0
        elif v <= sell:
            pos = 0.0
        out.append(pos)
    return pd.Series(out, index=score.index, dtype=float)


def block_bootstrap_ci(x: np.ndarray, periods_per_year: int, n_boot: int = 1000,
                       block: int = 21, seed: int = 42) -> tuple[float, float, float]:
    """(média anualizada, IC inf, IC sup) por bootstrap com blocos circulares."""
    x = np.asarray(x, dtype=float)
    n = len(x)
    if n == 0:
        return 0.0, 0.0, 0.0
    rng = np.random.default_rng(seed)
    block = max(1, min(block, n))
    n_blocks = -(-n // block)
    starts = rng.integers(0, n, size=(n_boot, n_blocks))
    idx = ((starts[:, :, None] + np.arange(block)) % n).reshape(n_boot, -1)[:, :n]
    means = x[idx].mean(axis=1) * periods_per_year
    lo, hi = np.percentile(means, [2.5, 97.5])
    return float(x.mean() * periods_per_year), float(lo), float(hi)


def _finite(v: float) -> float:
    return float(v) if np.isfinite(v) else 0.0


def perf_stats(returns: pd.Series, rf: pd.Series, periods_per_year: int) -> dict:
    """Retorno anualizado (geométrico), volatilidade, Sharpe e drawdown máximo."""
    r = returns.to_numpy(dtype=float)
    n = len(r)
    if n == 0:
        return {"ann_return": 0.0, "ann_vol": 0.0, "sharpe": 0.0, "max_drawdown": 0.0}
    equity = np.cumprod(1 + r)
    ann_return = equity[-1] ** (periods_per_year / n) - 1
    std = r.std(ddof=1) if n > 1 else 0.0
    if std <= 1e-12 * max(1.0, abs(r.mean())):  # ruído de ponto flutuante = sem variação
        std = 0.0
    sharpe = 0.0
    if std > 0:
        excess = r - rf.reindex(returns.index).fillna(0.0).to_numpy(dtype=float)
        sharpe = excess.mean() / std * np.sqrt(periods_per_year)
    peak = np.maximum.accumulate(np.concatenate([[1.0], equity]))[1:]
    return {
        "ann_return": _finite(ann_return),
        "ann_vol": _finite(std * np.sqrt(periods_per_year)),
        "sharpe": _finite(sharpe),
        "max_drawdown": _finite((equity / peak - 1).min()),
    }


@dataclass
class BacktestResult:
    start: str
    end: str
    strategy: dict
    buy_hold: dict
    trades: int
    time_in_market: float
    hit_rate: float | None
    excess_mean: float
    ci_low: float
    ci_high: float
    evidence: str  # "favoravel" | "contraria" | "sem_evidencia"
    equity: pd.DataFrame  # colunas strategy, buy_hold; começa em 1.0


def _closed_trades_hit_rate(held: np.ndarray, strat: np.ndarray, cost: float) -> float | None:
    """Fração das operações fechadas (entrada e saída) com retorno composto líquido > 0."""
    results, acc, inside = [], 1.0, False
    for h, s in zip(held, strat):
        if h == 1:
            acc *= 1 + s  # retorno do dia já inclui o custo de entrada
            inside = True
        elif inside:
            results.append(acc * (1 - cost) - 1)  # saída: desconta o custo de venda
            acc, inside = 1.0, False
    return float(np.mean([r > 0 for r in results])) if results else None


def run_backtest(close: pd.Series, score: pd.Series, rf_daily: pd.Series | None,
                 periods_per_year: int, cost: float = 0.001, n_boot: int = 1000,
                 block: int = 21, seed: int = 42) -> BacktestResult:
    score = score.reindex(close.index)
    first = score.first_valid_index()
    if first is None:
        raise ValueError("histórico insuficiente para backtest")
    close = close.loc[first:]
    score = score.loc[first:]
    if len(close) - 1 < 30:
        raise ValueError("histórico insuficiente para backtest")

    # Sinal do dia t vale para t+1: posição efetiva = pos deslocada em 1 dia.
    pos = positions_from_score(score)
    held_full = pos.shift(1).fillna(0.0)
    ret = close.pct_change(fill_method=None).fillna(0.0)
    rf = (pd.Series(0.0, index=close.index) if rf_daily is None
          else rf_daily.reindex(close.index).fillna(0.0))
    turnover = held_full.diff().abs().fillna(0.0)
    strat_full = held_full * ret + (1 - held_full) * rf - cost * turnover

    # O primeiro dia é só a base (equity 1.0); os retornos começam no dia seguinte.
    strat, bh, held, rf_s = strat_full.iloc[1:], ret.iloc[1:], held_full.iloc[1:], rf.iloc[1:]
    equity = pd.DataFrame({"strategy": (1 + strat_full.iloc[1:]).cumprod(),
                           "buy_hold": (1 + ret.iloc[1:]).cumprod()})
    equity = pd.concat([pd.DataFrame({"strategy": [1.0], "buy_hold": [1.0]}, index=close.index[:1]), equity])

    entries = int(((held.diff().fillna(held.iloc[0])) == 1).sum())
    excess = (strat - bh).to_numpy()
    if np.allclose(excess, 0.0, atol=1e-15):
        mean_x, lo, hi = 0.0, 0.0, 0.0
    else:
        mean_x, lo, hi = block_bootstrap_ci(excess, periods_per_year, n_boot, block, seed)
    evidence = "favoravel" if lo > 0 else "contraria" if hi < 0 else "sem_evidencia"

    return BacktestResult(
        start=pd.Timestamp(close.index[0]).strftime("%Y-%m-%d"),
        end=pd.Timestamp(close.index[-1]).strftime("%Y-%m-%d"),
        strategy=perf_stats(strat, rf_s, periods_per_year),
        buy_hold=perf_stats(bh, rf_s, periods_per_year),
        trades=entries,
        time_in_market=float(held.mean()),
        hit_rate=_closed_trades_hit_rate(held.to_numpy(), strat.to_numpy(), cost),
        excess_mean=_finite(mean_x), ci_low=_finite(lo), ci_high=_finite(hi),
        evidence=evidence, equity=equity,
    )
