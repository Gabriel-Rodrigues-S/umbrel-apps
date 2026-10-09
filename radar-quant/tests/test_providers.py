"""Testes dos provedores de dados (sem acesso à internet)."""
import asyncio
import json
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest

from app.config import Settings
from app.providers.base import ProviderError, UnknownSymbol
from app.providers.bcb import fetch_cdi
from app.providers.binance import BinanceProvider
from app.providers.registry import fetch_rf_rates, get_provider
from app.providers.synthetic import SyntheticProvider
from app.providers.yahoo import YahooProvider

FIX = Path(__file__).parent / "fixtures"


def load(name):
    return json.loads((FIX / name).read_text())


def run(coro):
    return asyncio.run(coro)


# ---------- Yahoo ----------
def yahoo(handler):
    return YahooProvider(httpx.MockTransport(handler))


def test_yahoo_ajusta_e_descarta_nulos():
    urls = []

    def h(req):
        urls.append(str(req.url))
        return httpx.Response(200, json=load("yahoo_petr4.json"))

    candles = run(yahoo(h).fetch_daily("PETR4", "B3"))
    assert "PETR4.SA" in urls[0]
    assert len(candles) == 4
    c = candles[0]
    f = 34.0 / 36.5
    assert c.close == 34.0 and c.open == pytest.approx(36.0 * f)
    assert c.high == pytest.approx(36.9 * f) and c.low == pytest.approx(35.8 * f)
    assert c.date == "2024-01-10"  # 1704889800 = 12:30 UTC, -3h
    assert candles[2].volume == 0  # volume nulo vira 0


def test_yahoo_us_sem_sufixo():
    urls = []

    def h(req):
        urls.append(str(req.url))
        return httpx.Response(200, json=load("yahoo_petr4.json"))

    run(yahoo(h).fetch_daily("AAPL", "US"))
    assert "/AAPL?" in urls[0] and ".SA" not in urls[0]


def test_yahoo_404():
    with pytest.raises(UnknownSymbol):
        run(yahoo(lambda r: httpx.Response(404, json={})).fetch_daily("X", "US"))


def test_yahoo_not_found_no_corpo():
    body = {"chart": {"result": None, "error": {"code": "Not Found"}}}
    with pytest.raises(UnknownSymbol):
        run(yahoo(lambda r: httpx.Response(200, json=body)).fetch_daily("X", "US"))


def test_yahoo_http_500():
    with pytest.raises(ProviderError) as e:
        run(yahoo(lambda r: httpx.Response(500)).fetch_daily("X", "US"))
    assert not isinstance(e.value, UnknownSymbol)


def test_yahoo_nao_json():
    with pytest.raises(ProviderError):
        run(yahoo(lambda r: httpx.Response(200, text="<html>")).fetch_daily("X", "US"))


def test_yahoo_todas_nulas():
    d = load("yahoo_petr4.json")
    q = d["chart"]["result"][0]["indicators"]["quote"][0]
    q["close"] = [None] * 5
    with pytest.raises(ProviderError):
        run(yahoo(lambda r: httpx.Response(200, json=d)).fetch_daily("X", "US"))


def test_yahoo_datas_duplicadas_fica_a_ultima():
    d = load("yahoo_petr4.json")
    d["chart"]["result"][0]["timestamp"][1] = d["chart"]["result"][0]["timestamp"][0] + 60
    candles = run(yahoo(lambda r: httpx.Response(200, json=d)).fetch_daily("X", "US"))
    assert len(candles) == 3
    assert candles[0].close == 34.3


# ---------- Binance ----------
def binance(handler):
    return BinanceProvider(httpx.MockTransport(handler))


def test_binance_par_e_descarta_hoje():
    rows = load("binance_btc.json")
    today_ms = int(datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).timestamp() * 1000)
    rows.append([today_ms, "1", "2", "0.5", "1.5", "10", today_ms + 86_399_999, "0", 0, "0", "0", "0"])
    seen = []

    def h(req):
        seen.append(req)
        return httpx.Response(200, json=rows)

    candles = run(binance(h).fetch_daily("BTC", "CRYPTO"))
    assert seen[0].url.params["symbol"] == "BTCUSDT"
    assert len(candles) == 3
    assert candles[0].date == "2024-01-01" and candles[0].close == 42800.0
    assert candles[0].volume == 1200.5


def test_binance_fallback_em_451():
    hosts = []

    def h(req):
        hosts.append(req.url.host)
        if req.url.host == "api.binance.com":
            return httpx.Response(451)
        return httpx.Response(200, json=load("binance_btc.json"))

    candles = run(binance(h).fetch_daily("BTC", "CRYPTO"))
    assert hosts == ["api.binance.com", "data-api.binance.vision"]
    assert len(candles) == 3


def test_binance_simbolo_invalido():
    with pytest.raises(UnknownSymbol):
        run(binance(lambda r: httpx.Response(400, json={"code": -1121, "msg": "Invalid symbol."}))
            .fetch_daily("ZZZ", "CRYPTO"))


def test_binance_lista_vazia():
    with pytest.raises(ProviderError):
        run(binance(lambda r: httpx.Response(200, json=[])).fetch_daily("BTC", "CRYPTO"))


# ---------- BCB ----------
def test_bcb_converte():
    out = run(fetch_cdi(httpx.MockTransport(lambda r: httpx.Response(200, json=load("bcb_cdi.json")))))
    assert out[0][0] == "2024-01-02"
    assert out[0][1] == pytest.approx(0.00043739)
    assert len(out) == 3


def test_bcb_erro():
    with pytest.raises(ProviderError):
        run(fetch_cdi(httpx.MockTransport(lambda r: httpx.Response(500))))


# ---------- Sintético ----------
def test_sintetico_deterministico_e_consistente():
    p = SyntheticProvider()
    a = run(p.fetch_daily("PETR4", "B3"))
    b = run(p.fetch_daily("PETR4", "B3"))
    assert a == b and len(a) == 1500
    assert a[-1].date <= "2026-10-07"
    for c in a:
        assert c.low <= min(c.open, c.close) and c.high >= max(c.open, c.close)
        assert c.volume > 0 and c.close > 0


def test_sintetico_simbolos_especiais():
    p = SyntheticProvider()
    with pytest.raises(UnknownSymbol):
        run(p.fetch_daily("INVALIDO", "B3"))
    assert len(run(p.fetch_daily("CURTO1", "B3"))) == 100
    with pytest.raises(ProviderError, match="fonte indisponível"):
        run(p.fetch_daily("FALHA1", "B3"))


# ---------- Registry ----------
def test_registry():
    syn = Settings(data_dir=Path("/tmp"), provider="synthetic", refresh_hours=6)
    live = replace(syn, provider="live")
    for m in ("B3", "US", "CRYPTO"):
        assert isinstance(get_provider(m, syn), SyntheticProvider)
    assert isinstance(get_provider("B3", live), YahooProvider)
    assert isinstance(get_provider("US", live), YahooProvider)
    assert isinstance(get_provider("CRYPTO", live), BinanceProvider)
    with pytest.raises(ValueError):
        get_provider("XX", live)
    assert run(fetch_rf_rates(syn)) == []
