import asyncio
import json
from datetime import datetime, timezone

import numpy as np
import pytest

from app import analysis, db, service
from app.config import Settings
from app.providers.base import Bar
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
    assert r["equity"][-1]["date"] == "2026-10-07"  # semana parcial: última data real, não a sexta
    # candle do dia reescrito num refresh: mesma contagem e data, mas a análise é refeita
    assert analysis.analyze_asset(conn, {**a, "last_refresh": "2026-10-08T00:00:00+00:00"}) is not r
    r = analysis.analyze_asset(conn, a)
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
    assert wk["candles"][-1]["time"] == mo["candles"][-1]["time"] == "2026-10-07"
    assert wk["indicators"]["rsi14"][-1]["time"] == "2026-10-07"
    json.dumps(wk)
    with pytest.raises(ValueError):
        analysis.candles_payload(conn, a["id"], "2h")


def test_clean():
    assert analysis.clean({"a": float("nan"), "b": [np.float64(1.5), float("inf")]}) == {"a": None, "b": [1.5, None]}
    assert type(analysis.clean(np.int64(3))) is int
    assert analysis.clean(np.array([1.0, np.nan])) == [1.0, None]


# ---------- 1.1: curto prazo, resumo, intervalos e intraday ----------

def test_analyze_tem_swing_sem_pool(conn):
    r = analysis.analyze_asset(conn, asset(conn, "PETR4"))
    sw = r["swing"]
    assert [s["key"] for s in sw["setups"]] == ["reversao", "queda", "rompimento"]
    assert all("pool" not in s for s in sw["setups"]) and "atr_pct" in sw["context"]
    assert {"state", "stats", "markers", "description", "position"} <= set(sw["setups"][0])
    s = json.dumps(r)
    assert "NaN" not in s and "Infinity" not in s


def test_swing_pool_do_mesmo_cache(conn, monkeypatch):
    a = asset(conn, "PETR4")
    analysis.analyze_asset(conn, a)
    monkeypatch.setattr(analysis, "_compute", lambda *x: pytest.fail("recalculou"))
    pool = analysis.swing_pool(conn, a)
    assert set(pool) == {"reversao", "queda", "rompimento"}
    assert all(isinstance(v, list) for v in pool.values())
    json.dumps(pool)


def test_swing_pool_calcula_se_nao_ha_cache(conn):
    assert set(analysis.swing_pool(conn, asset(conn, "VALE3"))) == {"reversao", "queda", "rompimento"}


def test_insuficiente_sem_swing(conn):
    a = asset(conn, "CURTO1")
    assert "swing" not in analysis.analyze_asset(conn, a)
    assert analysis.swing_pool(conn, a) == {}


def test_summary_catalogo(conn):
    db.replace_catalog_market(conn, "US", [("AAPL", "Apple Inc.", "Ação")])
    db.set_index_members(conn, "SP500", "US", ["AAPL"])
    db.set_index_members(conn, "NDX", "US", ["AAPL"])
    s = analysis.asset_summary(conn, asset(conn, "AAPL"))
    assert s["watch"] is True and s["name"] == "Apple Inc." and s["indices"] == ["SP500", "NDX"]
    s = analysis.asset_summary(conn, asset(conn, "MSFT"))
    assert s["name"] is None and s["indices"] == [] and s["watch"] is True
    off = db.get_asset(conn, db.add_asset(conn, "ZZZ", "US", watch=False))
    assert analysis.asset_summary(conn, off)["watch"] is False


@pytest.mark.parametrize("interval", ["3mo", "6mo", "1y"])
def test_candles_payload_novos_intervalos(conn, interval):
    a = asset(conn, "PETR4")
    p = analysis.candles_payload(conn, a["id"], interval)
    assert p["interval"] == interval and p["candles"][-1]["time"] == "2026-10-07"
    assert len(p["candles"]) < len(analysis.candles_payload(conn, a["id"], "1mo")["candles"])
    json.dumps(p)


def _barras(n, step=60, t0=1_700_000_000):
    return [Bar(t0 + step * i, 10 + i, 11 + i, 9 + i, 10.5 + i, 100.0) for i in range(n)]


def test_intraday_payload():
    bars = _barras(60)
    p = analysis.intraday_payload(bars, "1m", 15)
    assert p["intraday"] is True and p["interval"] == "1m" and p["delay_minutes"] == 15
    assert len(p["candles"]) == 60 and all(type(c["time"]) is int for c in p["candles"])
    assert p["last_bar_time"] == bars[-1].time == p["candles"][-1]["time"]
    assert set(p["indicators"]) == {"sma20", "sma50", "sma200", "bb_upper", "bb_lower",
                                    "rsi14", "macd", "macd_signal", "macd_hist"}
    assert len(p["indicators"]["sma20"]) == 41 and type(p["indicators"]["sma20"][0]["time"]) is int
    assert p["indicators"]["sma200"] == []
    assert p["candles"][0] == {"time": bars[0].time, "open": 10, "high": 11, "low": 9, "close": 10.5,
                               "volume": 100.0}
    json.dumps(p, allow_nan=False)


def test_intraday_payload_vazio():
    p = analysis.intraday_payload([], "5m", None)
    assert p["candles"] == [] and p["last_bar_time"] is None and p["delay_minutes"] is None
    assert all(v == [] for v in p["indicators"].values())


def test_session_open(conn, monkeypatch):
    t = lambda d, h, m=0: datetime(2026, 10, d, h, m, tzinfo=timezone.utc)  # noqa: E731
    for market in ("B3", "US"):
        assert analysis.session_open(market, "2026-10-07", t(7, 15)) is True
        assert analysis.session_open(market, "2026-10-07", t(7, 20, 59)) is True
        assert analysis.session_open(market, "2026-10-07", t(7, 21)) is False  # pregão já fechado
        assert analysis.session_open(market, "2026-10-07", t(7, 21, 30)) is False
        assert analysis.session_open(market, "2026-10-07", t(8, 15)) is False  # candle de ontem
    assert analysis.session_open("CRYPTO", "2026-10-07", t(7, 15)) is False  # a Binance descarta o dia corrente
    assert analysis.session_open("B3", None, t(7, 15)) is False
    a, btc = asset(conn, "PETR4"), asset(conn, "BTC")
    r = analysis.analyze_asset(conn, a)
    assert r["session_open"] is False and analysis.asset_summary(conn, a)["session_open"] is False
    monkeypatch.setattr(analysis, "_now", lambda: t(7, 15))  # dia do último candle sintético
    assert analysis.analyze_asset(conn, a) is r and r["session_open"] is True and r["as_of"] == "2026-10-07"
    assert analysis.asset_summary(conn, a)["session_open"] is True
    assert analysis.analyze_asset(conn, btc)["session_open"] is False
    assert analysis.asset_summary(conn, btc)["session_open"] is False
    curto = analysis.asset_summary(conn, asset(conn, "CURTO1"))
    assert curto["status"] == "insuficiente" and curto["session_open"] is True
    monkeypatch.setattr(analysis, "_now", lambda: t(7, 21, 30))  # mesmo dia, depois do fechamento
    assert analysis.analyze_asset(conn, a)["session_open"] is False
    assert analysis.asset_summary(conn, a)["session_open"] is False
    monkeypatch.setattr(analysis, "_now", lambda: t(8, 15))
    assert analysis.analyze_asset(conn, a)["session_open"] is False


def test_nome_exibido_e_o_alias_no_resumo_e_na_carteira(conn):
    """1.1.1: `asset_summary` e os pesos da carteira trazem o nome exibido (alias quando existe)."""
    db.replace_catalog_market(conn, "B3", [("BBAS3", "BCO BRASIL S.A.", "Ação")])
    b = asset(conn, "BBAS3")
    assert analysis.asset_summary(conn, b)["name"] == "BCO Brasil S.A."  # legível, mesmo sem alias
    db.set_alias(conn, "BBAS3", "B3", "Banco do Brasil S.A.")
    assert analysis.asset_summary(conn, b)["name"] == "Banco do Brasil S.A."
    ws = {w["symbol"]: w for w in analysis.portfolio(conn, "risk_parity")["weights"]}
    assert ws["BBAS3"]["name"] == "Banco do Brasil S.A." and ws["BTC"]["name"] is None  # fora do catálogo
    assert set(ws["BBAS3"]) == {"id", "symbol", "market", "weight", "name"}
