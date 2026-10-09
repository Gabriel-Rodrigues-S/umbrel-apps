import asyncio
import json

import numpy as np
import pytest

from app import analysis, db, service
from app.config import Settings
from app.stats.factors import WEIGHTS, verdict
from app.stats.portfolio import PortfolioError


@pytest.fixture(scope="module")
def conn(tmp_path_factory):
    d = tmp_path_factory.mktemp("an")
    c = db.connect(d / "radar.db")
    service.seed_watchlist(c)
    db.add_asset(c, "CURTO1", "B3")
    asyncio.run(service.refresh_all(c, Settings(data_dir=d, provider="synthetic", refresh_hours=6)))
    return c


@pytest.fixture(autouse=True)
def _limpa_cache():
    analysis.invalidate()


def asset(conn, symbol):
    return next(a for a in db.list_assets(conn) if a["symbol"] == symbol)


def test_analyze_ok_cache_e_invalidate(conn):
    a = asset(conn, "PETR4")
    r = analysis.analyze_asset(conn, a)
    assert r["status"] == "ok" and r["candles"] == 1500 and r["as_of"] == "2026-10-07"
    assert [f["key"] for f in r["factors"]] == list(WEIGHTS)
    assert r["verdict"] == verdict(r["score"])
    assert r["equity"][0]["strategy"] == 1.0
    assert "NaN" not in json.dumps(r)
    assert analysis.analyze_asset(conn, a) is r
    analysis.invalidate(a["id"])
    assert analysis.analyze_asset(conn, a) is not r


def test_insuficiente(conn):
    a = asset(conn, "CURTO1")
    r = analysis.analyze_asset(conn, a)
    assert r["status"] == "insuficiente" and r["candles"] == 100 and "score" not in r
    assert all(i["symbol"] != "CURTO1" for i in analysis.ranking(conn))
    s = analysis.asset_summary(conn, a)
    assert s["price"] is not None and s["score"] is None and s["status"] == "insuficiente"
    pf = analysis.portfolio(conn, "risk_parity")
    assert all(w["symbol"] != "CURTO1" for w in pf["weights"])


def test_summary_ok_e_vazio(conn):
    s = analysis.asset_summary(conn, asset(conn, "AAPL"))
    assert s["status"] == "ok" and s["verdict"] in ("comprar", "manter", "vender")
    assert s["change_pct"] is not None and s["last_error"] is None
    vazio = db.get_asset(conn, db.add_asset(conn, "VAZIO1", "US"))
    s = analysis.asset_summary(conn, vazio)
    assert s["price"] is None and s["status"] == "insuficiente"


def test_ranking(conn):
    r = analysis.ranking(conn)
    scores = [i["score"] for i in r]
    assert len(r) == 13 and scores == sorted(scores, reverse=True)
    assert {"momentum", "trend", "dist_sma200", "reversal", "volatility", "drawdown"} <= set(r[0])
    us = analysis.ranking(conn, "US")
    assert us and {i["market"] for i in us} == {"US"}


def test_portfolio(conn):
    p = analysis.portfolio(conn, "risk_parity")
    ws = [w["weight"] for w in p["weights"]]
    assert abs(sum(ws) - 1) < 1e-6 and ws == sorted(ws, reverse=True)
    assert set(p["correlation"]["labels"]) == {w["symbol"] for w in p["weights"]}
    assert p["weeks"] == 155 and "sem conversão cambial" in p["note"]
    json.dumps(p)
    with pytest.raises(PortfolioError):
        analysis.portfolio(conn, "xyz")


def test_portfolio_um_ativo_ok(tmp_path):
    c = db.connect(tmp_path / "um.db")
    db.add_asset(c, "PETR4", "B3")
    db.add_asset(c, "CURTO1", "B3")
    asyncio.run(service.refresh_all(c, Settings(data_dir=tmp_path, provider="synthetic", refresh_hours=6)))
    with pytest.raises(PortfolioError):
        analysis.portfolio(c, "risk_parity")


def test_candles_payload(conn):
    a = asset(conn, "PETR4")
    p = analysis.candles_payload(conn, a["id"], "1d")
    assert len(p["candles"]) == 1500 and len(p["indicators"]["sma200"]) == 1500 - 199
    assert p["candles"][-1]["time"] == "2026-10-07"
    assert set(p["indicators"]) == {"sma20", "sma50", "sma200", "bb_upper", "bb_lower",
                                    "rsi14", "macd", "macd_signal", "macd_hist"}
    wk = analysis.candles_payload(conn, a["id"], "1wk")
    mo = analysis.candles_payload(conn, a["id"], "1mo")
    assert len(mo["candles"]) < len(wk["candles"]) < 1500
    json.dumps(wk)
    with pytest.raises(ValueError):
        analysis.candles_payload(conn, a["id"], "2h")


def test_clean():
    assert analysis.clean({"a": float("nan"), "b": [np.float64(1.5), float("inf")]}) == {"a": None, "b": [1.5, None]}
    assert type(analysis.clean(np.int64(3))) is int
    assert analysis.clean(np.array([1.0, np.nan])) == [1.0, None]
