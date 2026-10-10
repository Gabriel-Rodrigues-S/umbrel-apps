"""Curto prazo (swing, 1 a 10 pregões): setups só-compra, simulação e evidência por bootstrap.

Sem antecipação: o sinal do fechamento de t usa só dados até t; a compra é na abertura de t+1.
"""
from dataclasses import dataclass

import numpy as np
import pandas as pd

from app.stats.indicators import rsi, sma

SETUPS = {
    "reversao": {"label": "Reversão rápida",
                 "description": "Compra quando o RSI de 2 dias cai abaixo de 10 com o preço acima da média de 200 dias; "
                                "sai quando o fechamento passa da média de 5 dias."},
    "queda": {"label": "Queda extrema",
              "description": "Compra quando o fechamento fica abaixo da média de 20 dias menos 2 desvios, com o preço "
                             "acima da média de 200 dias; sai quando o fechamento volta à média de 20 dias."},
    "rompimento": {"label": "Rompimento",
                   "description": "Compra quando o fechamento supera a máxima dos 20 pregões anteriores com volume acima "
                                  "de 1,5 vez a média de 20 dias; sai quando o fechamento perde a mínima dos 10 pregões anteriores."},
}
MAX_HOLD = 10
COST = 0.001  # por ponta
MIN_TRADES = 20
POOL_MIN_TRADES = 100
MAX_MARKERS = 200
_EPS = 1e-9  # tolerância relativa: ruído de ponto flutuante não pode criar sinal em preço constante


@dataclass
class Trade:
    entry_date: pd.Timestamp
    entry_price: float
    exit_date: pd.Timestamp
    exit_price: float
    days: int
    net: float
    excess: float


def _num(x, nd: int = 6):
    """Número finito arredondado, ou None (garante JSON sem NaN/inf)."""
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return round(x, nd) + 0.0 if np.isfinite(x) else None  # + 0.0 normaliza -0.0


def signals(df: pd.DataFrame, key: str) -> tuple[pd.Series, pd.Series]:
    """(entrada, saída) booleanas no fechamento de cada candle; usa só dados até t. NaN -> False."""
    if key not in SETUPS:
        raise ValueError(f"setup desconhecido: {key}")
    c = df["close"]
    if key == "reversao":
        entry = (rsi(c, 2) < 10) & (c > sma(c, 200))
        exit_ = c > sma(c, 5)
    elif key == "queda":
        m20 = sma(c, 20)
        lower = m20 - 2 * c.rolling(20).std(ddof=0)
        entry = (c < lower - _EPS * c.abs()) & (c > sma(c, 200))
        exit_ = c >= m20 - _EPS * c.abs()
    else:
        v = df["volume"]
        prior_high = df["high"].shift(1).rolling(20).max()
        entry = (c > prior_high * (1 + _EPS)) & (v > 1.5 * v.shift(1).rolling(20).mean())
        exit_ = c < df["low"].shift(1).rolling(10).min() * (1 - _EPS)
    return entry.fillna(False).astype(bool), exit_.fillna(False).astype(bool)


def _mu(close: pd.Series) -> float:
    """Média do log-retorno diário do histórico inteiro (base do retorno esperado de segurar)."""
    r = np.log(close / close.shift(1)).to_numpy(dtype=float)
    r = r[np.isfinite(r)]
    return float(r.mean()) if len(r) else 0.0


def simulate(df, key, cost=COST, max_hold=MAX_HOLD) -> tuple[list[Trade], dict | None]:
    """Operações fechadas e posição aberta (ou None). Uma operação por vez."""
    ent, ex = signals(df, key)
    ent, ex = ent.to_numpy(), ex.to_numpy()
    op, cl = df["open"].to_numpy(dtype=float), df["close"].to_numpy(dtype=float)
    idx, n = df.index, len(df)
    mu = _mu(df["close"])
    trades: list[Trade] = []
    t = 0
    while t < n - 1:  # sinal no último candle não tem abertura seguinte
        if not ent[t]:
            t += 1
            continue
        e = t + 1  # compra na abertura de t+1
        entry_price = op[e]
        if not (np.isfinite(entry_price) and entry_price > 0):  # dado inválido: descarta a operação
            t += 1
            continue
        done = False
        for j in range(e, n):
            days = j - e + 1
            if days >= max_hold:  # limite: sai no fechamento do 10º pregão
                x_i, x_price = j, cl[j]
            elif ex[j] and j + 1 < n:  # saída na abertura seguinte ao sinal
                x_i, x_price = j + 1, op[j + 1]
            else:
                continue
            t, done = j + 1, True
            if not (np.isfinite(x_price) and x_price > 0):
                break
            net = x_price / entry_price - 1 - 2 * cost
            trades.append(Trade(idx[e], float(entry_price), idx[x_i], float(x_price), days, float(net),
                                float(net - (np.exp(mu * days) - 1))))
            break
        if not done:
            return trades, {"entry_date": idx[e].isoformat(), "entry_price": float(entry_price),
                            "days": n - e, "ret": float(cl[-1] / entry_price - 1),
                            "exit_pending": bool(ex[-1])}  # saída já sinalizada: venda na próxima abertura
    return trades, None


def _boot_ci(x: np.ndarray, n_boot: int, seed: int) -> tuple[float, float]:
    """IC de 95% da média por bootstrap i.i.d."""
    rng = np.random.default_rng(seed)
    means = x[rng.integers(0, len(x), size=(n_boot, len(x)))].mean(axis=1)
    lo, hi = np.percentile(means, [2.5, 97.5])
    return float(lo), float(hi)


def _label(lo: float, hi: float) -> str:
    return "favoravel" if lo > 0 else "contraria" if hi < 0 else "sem_evidencia"


def trade_stats(trades: list[Trade], n_boot: int = 2000, seed: int = 42) -> dict:
    n = len(trades)
    out = {"trades": n, "win_rate": None, "mean_net": None, "median_net": None, "avg_days": None,
           "mean_excess": None, "ci_low": None, "ci_high": None, "evidence": "amostra_insuficiente"}
    if n == 0:
        return out
    net = np.array([t.net for t in trades])
    exc = np.array([t.excess for t in trades])
    out.update(win_rate=_num((net > 0).mean()), mean_net=_num(net.mean()), median_net=_num(np.median(net)),
               avg_days=_num(np.mean([t.days for t in trades])), mean_excess=_num(exc.mean()))
    if n >= MIN_TRADES:
        lo, hi = _boot_ci(exc, n_boot, seed)
        out["ci_low"], out["ci_high"], out["evidence"] = _num(lo), _num(hi), _label(lo, hi)  # rótulo com IC bruto
    return out


def _cut(marks: list[dict]) -> list[dict]:
    """Últimas MAX_MARKERS marcações, sem começar por uma saída órfã."""
    marks = marks[-MAX_MARKERS:]
    return marks[1:] if marks and marks[0]["type"] == "exit" else marks


def setup_report(df, key) -> dict:
    if key not in SETUPS:
        raise ValueError(f"setup desconhecido: {key}")
    trades, pos = simulate(df, key)
    ent, _ = signals(df, key)
    if pos is not None:
        pos = {"entry_date": pos["entry_date"], "entry_price": _num(pos["entry_price"]),
               "days": pos["days"], "ret": _num(pos["ret"]), "exit_pending": pos["exit_pending"]}
        state = "posicao"
    else:
        # saída pelo limite no último candle: a simulação ignora a entrada desse mesmo fechamento
        capped = bool(trades) and trades[-1].exit_date == df.index[-1] and trades[-1].days >= MAX_HOLD
        state = "sinal" if len(ent) and bool(ent.iloc[-1]) and not capped else "nenhum"
    marks = []
    for t in trades:
        marks.append({"time": t.entry_date.isoformat(), "type": "entry", "price": _num(t.entry_price)})
        marks.append({"time": t.exit_date.isoformat(), "type": "exit", "price": _num(t.exit_price)})
    if pos is not None:
        marks.append({"time": pos["entry_date"], "type": "entry", "price": pos["entry_price"]})
    return {"key": key, "label": SETUPS[key]["label"], "description": SETUPS[key]["description"],
            "state": state, "position": pos, "stats": trade_stats(trades),
            "markers": _cut(marks),
            "pool": [[t.entry_date.year * 100 + t.entry_date.month, _num(t.excess)] for t in trades]}


def context(df) -> dict:
    c, h, lo, v = df["close"], df["high"], df["low"], df["volume"]
    pc = c.shift(1)
    tr = pd.concat([h - lo, (h - pc).abs(), (lo - pc).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()  # ATR de Wilder
    r = np.log(c / pc).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    vol = np.sqrt((r ** 2).ewm(alpha=0.06, adjust=False).mean())  # EWMA, lambda = 0,94
    avg_v = v.shift(1).rolling(20).mean()
    last = lambda s: s.iloc[-1] if len(s) else np.nan  # noqa: E731
    rel = last(v) / last(avg_v) if last(avg_v) > 0 else None
    hi20, lo20 = h.rolling(20).max(), lo.rolling(20).min()
    return {"atr_pct": _num(last(atr) / last(c)), "range_5d": _num(last(vol) * np.sqrt(5)),
            "rel_volume": _num(rel), "dist_high20": _num(last(c) / last(hi20) - 1),
            "dist_low20": _num(last(c) / last(lo20) - 1)}


def swing_report(df) -> dict:
    return {"setups": [setup_report(df, k) for k in SETUPS], "context": context(df)}


def pooled_evidence(pool: list[tuple[int, float]], n_boot: int = 1000, seed: int = 42) -> dict:
    """Evidência do índice por bootstrap de meses de entrada; `win_rate` = fração com excesso > 0."""
    pool = [(m, e) for m, e in pool if e is not None and np.isfinite(e)]
    n = len(pool)
    out = {"trades": n, "win_rate": None, "mean_excess": None, "ci_low": None, "ci_high": None,
           "evidence": "amostra_insuficiente"}
    if n == 0:
        return out
    months = np.array([int(m) for m, _ in pool])
    exc = np.array([float(e) for _, e in pool])
    out.update(win_rate=_num((exc > 0).mean()), mean_excess=_num(exc.mean()))
    if n < POOL_MIN_TRADES:
        return out
    uniq, inv = np.unique(months, return_inverse=True)
    sums = np.bincount(inv, weights=exc)
    counts = np.bincount(inv).astype(float)
    pick = np.random.default_rng(seed).integers(0, len(uniq), size=(n_boot, len(uniq)))
    means = sums[pick].sum(axis=1) / counts[pick].sum(axis=1)
    lo, hi = np.percentile(means, [2.5, 97.5])
    out["ci_low"], out["ci_high"], out["evidence"] = _num(lo), _num(hi), _label(lo, hi)
    return out
