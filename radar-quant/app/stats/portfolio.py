"""Carteira: covariância Ledoit-Wolf, paridade de risco, mínima variância e estatísticas."""
import numpy as np
import pandas as pd

PERIODS = 52  # retornos semanais


class PortfolioError(ValueError):
    pass


METHODS = ("risk_parity", "min_variance")


def ledoit_wolf(returns: np.ndarray) -> np.ndarray:
    """Covariância encolhida para a identidade escalada (Ledoit & Wolf, 2004)."""
    x = np.asarray(returns, dtype=float)
    t, n = x.shape
    x = x - x.mean(axis=0)
    s = x.T @ x / t
    m = np.trace(s) / n
    d2 = np.sum((s - m * np.eye(n)) ** 2)
    if d2 <= 0:
        return s
    # b2: variância amostral estimada de S em torno de si mesma
    b2 = (np.sum(np.sum(x**2, axis=1) ** 2) - t * np.sum(s**2)) / t**2
    delta = min(1.0, max(0.0, b2 / d2))
    return delta * m * np.eye(n) + (1 - delta) * s


def risk_parity(cov: np.ndarray) -> np.ndarray:
    """Pesos long-only com contribuições de risco iguais (iteração multiplicativa)."""
    n = len(cov)
    w = np.full(n, 1.0 / n)
    for _ in range(5000):
        rc = np.maximum(w * (cov @ w), 1e-18)
        share = rc / rc.sum()
        if np.abs(share - 1.0 / n).max() < 1e-8:
            break
        w = w * np.sqrt((1.0 / n) / share)
        w /= w.sum()
    return w


def _project_simplex(v: np.ndarray) -> np.ndarray:
    """Projeção euclidiana no simplex {w >= 0, soma 1}."""
    u = np.sort(v)[::-1]
    css = np.cumsum(u) - 1
    k = np.arange(1, len(v) + 1)
    rho = np.nonzero(u - css / k > 0)[0][-1]
    return np.maximum(v - css[rho] / (rho + 1), 0.0)


def min_variance(cov: np.ndarray) -> np.ndarray:
    """Mínima variância long-only por gradiente projetado no simplex."""
    n = len(cov)
    step = 1.0 / max(np.linalg.eigvalsh(cov).max(), 1e-18)
    w = np.full(n, 1.0 / n)
    for _ in range(5000):
        w = _project_simplex(w - step * (cov @ w))
    return w


def apply_cap(w: np.ndarray, cap: float) -> np.ndarray:
    """Limita cada peso a `cap`; o excesso vai, proporcionalmente, aos não limitados."""
    w = np.asarray(w, dtype=float).copy()
    cap = max(cap, 1.0 / len(w))  # teto abaixo de 1/N seria inviável
    capped = np.zeros(len(w), dtype=bool)
    for _ in range(len(w) + 1):
        over = (w > cap + 1e-12) & ~capped
        if not over.any():
            break
        excess = (w[over] - cap).sum()
        w[over] = cap
        capped |= over
        free = ~capped
        base = w[free].sum()
        if base > 0:
            w[free] += excess * w[free] / base
        else:
            w[free] += excess / free.sum()
    return w


def build_portfolio(returns: pd.DataFrame, method: str, cap: float = 0.35) -> dict:
    if method not in METHODS:
        raise PortfolioError(f"método inválido: {method}")
    if returns.shape[1] < 2:
        raise PortfolioError("são necessários pelo menos 2 ativos")
    df = returns.replace([np.inf, -np.inf], np.nan).dropna()
    if len(df) < 52:
        raise PortfolioError("são necessárias pelo menos 52 semanas em comum")

    x = df.to_numpy(dtype=float)
    n = x.shape[1]
    cov = ledoit_wolf(x)
    cov = cov + 1e-12 * max(np.trace(cov) / n, 1e-12) * np.eye(n)  # evita singularidade
    w = risk_parity(cov) if method == "risk_parity" else min_variance(cov)
    if n >= 3:
        w = apply_cap(w, cap)

    # correlação amostral; variância zero -> 0 fora da diagonal
    sc = np.cov(x, rowvar=False)
    sd = np.sqrt(np.diag(sc))
    ok = sd > 1e-12  # variância zero (ou ruído numérico) -> correlação 0
    den = np.outer(sd, sd)
    corr = np.divide(sc, den, out=np.zeros_like(sc), where=np.outer(ok, ok))
    corr = np.clip(corr, -1, 1)
    np.fill_diagonal(corr, 1.0)

    # estatísticas: pesos fixos, rebalanceado toda semana, rf = 0
    r = x @ w
    equity = np.concatenate([[1.0], np.cumprod(1 + r)])
    final = equity[-1]
    ann_return = final ** (PERIODS / len(r)) - 1 if final > 0 else -1.0
    ann_vol = float(np.std(r, ddof=1) * np.sqrt(PERIODS))
    sharpe = ann_return / ann_vol if ann_vol > 1e-12 else 0.0
    max_dd = float(np.min(equity / np.maximum.accumulate(equity) - 1))

    return {
        "weights": {str(c): float(v) for c, v in zip(df.columns, w)},
        "correlation": {"labels": [str(c) for c in df.columns], "matrix": corr.tolist()},
        "stats": {
            "ann_return": float(ann_return),
            "ann_vol": ann_vol,
            "sharpe": float(sharpe),
            "max_drawdown": max_dd,
        },
        "weeks": int(len(df)),
    }
