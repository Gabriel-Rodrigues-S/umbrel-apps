"""Orquestra o motor estatístico por ativo: análise, ranking, carteira e candles."""
import threading

import numpy as np
import pandas as pd

from app import db, service
from app.config import CURRENCY, PERIODS_PER_YEAR
from app.providers.base import Bar
from app.stats import factors as F
from app.stats.backtest import run_backtest
from app.stats.indicators import bollinger, macd, rsi, sma
from app.stats.portfolio import METHODS, PortfolioError, build_portfolio
from app.stats.swing import swing_report

PORTFOLIO_WEEKS = 156
NOTE = "Retornos em moeda local de cada ativo, sem conversão cambial."

_cache: dict[int, tuple[tuple, dict, dict]] = {}  # asset_id -> (assinatura, análise, pools dos setups)
_lock = threading.Lock()


def clean(obj):
    """Torna o objeto serializável em JSON: NaN/inf -> None e numpy -> tipos nativos."""
    if isinstance(obj, dict):
        return {k: clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [clean(v) for v in obj]
    if isinstance(obj, np.ndarray):
        return clean(obj.tolist())
    if isinstance(obj, (bool, np.bool_)):
        return bool(obj)
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, (float, np.floating)):
        return float(obj) if np.isfinite(obj) else None
    return obj


def invalidate(asset_id: int | None = None) -> None:
    with _lock:
        if asset_id is None:
            _cache.clear()
        else:
            _cache.pop(asset_id, None)


def _date(ts) -> str:
    return pd.Timestamp(ts).strftime("%Y-%m-%d")


def _compute(conn, asset: dict, df: pd.DataFrame) -> tuple[dict, dict]:
    """(análise pública, pools dos setups de swing). Ativo insuficiente: pools vazios."""
    base = {"asset_id": asset["id"], "symbol": asset["symbol"], "market": asset["market"],
            "currency": asset.get("currency") or CURRENCY[asset["market"]], "candles": len(df)}
    insufficient = {**base, "status": "insuficiente", "as_of": _date(df.index[-1]) if len(df) else None}
    if len(df) < F.MIN_CANDLES:
        return insufficient, {}
    close = df["close"]
    score = F.score_series(close)
    last_score = score.iloc[-1]
    if not np.isfinite(last_score):
        return insufficient, {}
    market = asset["market"]
    ppy = PERIODS_PER_YEAR[market]
    try:
        bt = run_backtest(close, score, service.load_rf_series(conn) if market == "B3" else None, ppy)
    except ValueError:
        return insufficient, {}
    frame = F.factor_frame(close)
    raw, norm = frame.iloc[-1], F.normalize(frame).iloc[-1]
    equity = service.resample_real_dates(bt.equity, "W-FRI", "last").dropna()
    swing = swing_report(df)
    pools = {x["key"]: x.pop("pool") for x in swing["setups"]}
    return clean({
        **base, "status": "ok", "as_of": _date(df.index[-1]),
        "score": last_score, "verdict": F.verdict(last_score),
        "factors": [{"key": k, "label": F.LABELS[k], "raw": raw[k], "normalized": norm[k],
                     "weight": F.WEIGHTS[k]} for k in F.WEIGHTS],
        "volatility": F.ewma_vol(close, ppy), "drawdown": F.current_drawdown(close),
        "backtest": {"start": bt.start, "end": bt.end, "strategy": bt.strategy, "buy_hold": bt.buy_hold,
                     "trades": bt.trades, "time_in_market": bt.time_in_market, "hit_rate": bt.hit_rate,
                     "excess": {"mean": bt.excess_mean, "ci_low": bt.ci_low, "ci_high": bt.ci_high},
                     "evidence": bt.evidence},
        "equity": [{"date": _date(d), "strategy": r.strategy, "buy_hold": r.buy_hold}
                   for d, r in equity.iterrows()],
        "swing": swing,
    }), clean(pools)


def _analyze_full(conn, asset: dict, df: pd.DataFrame) -> tuple[dict, dict]:
    # last_refresh entra na assinatura: o candle do dia pode ser reescrito sem mudar contagem/data
    sig = (asset["symbol"], asset["market"], len(df), _date(df.index[-1]) if len(df) else None,
           asset.get("last_refresh"))
    with _lock:
        hit = _cache.get(asset["id"])
    if hit and hit[0] == sig:
        return hit[1], hit[2]
    result, pools = _compute(conn, asset, df)  # CPU-bound: fora do lock
    with _lock:
        _cache[asset["id"]] = (sig, result, pools)
    return result, pools


def _analyze(conn, asset: dict, df: pd.DataFrame) -> dict:
    return _analyze_full(conn, asset, df)[0]


def analyze_asset(conn, asset: dict) -> dict:
    return _analyze(conn, asset, service.load_frame(conn, asset["id"]))


def swing_pool(conn, asset: dict) -> dict[str, list]:
    """Excessos por operação de cada setup ({chave: [[mês, excesso]]}), da mesma análise em cache."""
    return _analyze_full(conn, asset, service.load_frame(conn, asset["id"]))[1]


def asset_summary(conn, asset: dict) -> dict:
    df = service.load_frame(conn, asset["id"])
    entry = db.catalog_entry(conn, asset["symbol"], asset["market"])
    out = {"id": asset["id"], "symbol": asset["symbol"], "market": asset["market"],
           "currency": asset["currency"],
           "watch": bool(asset.get("watch", 1)),
           "name": entry["name"] if entry else None,
           "indices": entry["indices"] if entry else [], "price": None, "change_pct": None, "score": None,
           "verdict": None, "evidence": None, "status": "insuficiente",
           "last_error": asset.get("last_error"), "last_refresh": asset.get("last_refresh")}
    if df.empty:
        return clean(out)
    close = df["close"]
    out["price"] = close.iloc[-1]
    if len(close) > 1:
        out["change_pct"] = close.iloc[-1] / close.iloc[-2] - 1
    a = _analyze(conn, asset, df)
    if a["status"] == "ok":
        out.update(status="ok", score=a["score"], verdict=a["verdict"], evidence=a["backtest"]["evidence"])
    return clean(out)


def _ok_analyses(conn, market: str | None) -> list[tuple[dict, dict]]:
    pairs = [(a, analyze_asset(conn, a)) for a in db.list_assets(conn)
             if market is None or a["market"] == market]
    return [(a, r) for a, r in pairs if r["status"] == "ok"]


def ranking(conn, market: str | None = None) -> list[dict]:
    items = []
    for _, r in _ok_analyses(conn, market):
        item = {"id": r["asset_id"], "symbol": r["symbol"], "market": r["market"], "score": r["score"],
                "verdict": r["verdict"], "evidence": r["backtest"]["evidence"]}
        item.update({f["key"]: f["normalized"] for f in r["factors"]})
        item.update(volatility=r["volatility"], drawdown=r["drawdown"])
        items.append(item)
    return sorted(items, key=lambda i: i["score"], reverse=True)


def portfolio(conn, method: str, market: str | None = None) -> dict:
    if method not in METHODS:
        raise PortfolioError(f"método inválido: {method}")
    ok = _ok_analyses(conn, market)
    if len(ok) < 2:
        raise PortfolioError("são necessários pelo menos 2 ativos com análise válida")
    symbols = [a["symbol"] for a, _ in ok]
    cols, by_label = {}, {}
    for a, _ in ok:
        label = a["symbol"] if symbols.count(a["symbol"]) == 1 else f"{a['symbol']} ({a['market']})"
        weekly = service.load_frame(conn, a["id"])["close"].resample("W-FRI").last().dropna()
        cols[label] = weekly.iloc[-PORTFOLIO_WEEKS:].pct_change()
        by_label[label] = a
    res = build_portfolio(pd.concat(cols, axis=1, join="inner").iloc[1:], method)
    weights = [{"id": by_label[k]["id"], "symbol": by_label[k]["symbol"], "market": by_label[k]["market"],
                "weight": w} for k, w in sorted(res["weights"].items(), key=lambda kv: -kv[1])]
    return clean({"method": method, "market": market, "weights": weights,
                  "correlation": res["correlation"], "stats": res["stats"], "weeks": res["weeks"],
                  "note": NOTE})


def _points(s: pd.Series, fmt=_date) -> list[dict]:
    return [{"time": fmt(t), "value": v} for t, v in s.dropna().items()]


def _indicators(close: pd.Series, fmt=_date) -> dict:
    m, bb = macd(close), bollinger(close)
    series = {"sma20": sma(close, 20), "sma50": sma(close, 50), "sma200": sma(close, 200),
              "bb_upper": bb["upper"], "bb_lower": bb["lower"], "rsi14": rsi(close, 14),
              "macd": m["macd"], "macd_signal": m["signal"], "macd_hist": m["hist"]}
    return {k: _points(v, fmt) for k, v in series.items()}


def candles_payload(conn, asset_id: int, interval: str) -> dict:
    df = service.resample(service.load_frame(conn, asset_id), interval)
    candles = [{"time": _date(t), "open": r.open, "high": r.high, "low": r.low, "close": r.close,
                "volume": r.volume} for t, r in df.iterrows()]
    return clean({"interval": interval, "candles": candles, "indicators": _indicators(df["close"])})


def intraday_payload(bars: list[Bar], interval: str, delay_minutes: int | None) -> dict:
    """Mesmo formato do diário, com `time` em segundos epoch UTC."""
    close = pd.Series([b.close for b in bars], index=[b.time for b in bars], dtype=float)
    candles = [{"time": b.time, "open": b.open, "high": b.high, "low": b.low, "close": b.close,
                "volume": b.volume} for b in bars]
    return clean({"interval": interval, "intraday": True, "candles": candles,
                  "indicators": _indicators(close, int),
                  "last_bar_time": bars[-1].time if bars else None, "delay_minutes": delay_minutes})
