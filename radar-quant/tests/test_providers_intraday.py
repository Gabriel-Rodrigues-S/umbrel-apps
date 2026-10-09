"""Testes do intraday nos provedores (sem acesso à internet)."""
import asyncio
import json
from pathlib import Path

import httpx
import pytest

from app.providers.base import ProviderError, UnknownSymbol
from app.providers.binance import BinanceProvider
from app.providers.synthetic import SyntheticProvider
from app.providers.yahoo import YahooProvider

FIX = Path(__file__).parent / "fixtures"


def load(name):
    return json.loads((FIX / name).read_text())


def run(coro):
    return asyncio.run(coro)


def yahoo(handler):
    return YahooProvider(httpx.MockTransport(handler), retry_delay=0)


def binance(handler):
    return BinanceProvider(httpx.MockTransport(handler))


# ---------- Yahoo ----------
@pytest.mark.parametrize("interval,yi,rng", [("1m", "1m", "7d"), ("5m", "5m", "60d"),
                                              ("30m", "30m", "60d"), ("1h", "60m", "730d")])
def test_yahoo_parametros_por_intervalo(interval, yi, rng):
    reqs = []

    def h(req):
        reqs.append(req)
        return httpx.Response(200, json=load("intraday_yahoo.json"))

    run(yahoo(h).fetch_intraday("PETR4", "B3", interval))
    p = reqs[0].url.params
    assert p["interval"] == yi and p["range"] == rng and "events" not in p
    assert "PETR4.SA" in str(reqs[0].url)
    assert reqs[0].headers["User-Agent"].startswith("Mozilla/5.0 (compatible; RadarQuantBot")


def test_yahoo_barras_atraso_e_sem_ajuste():
    bars, delay = run(yahoo(lambda r: httpx.Response(200, json=load("intraday_yahoo.json")))
                      .fetch_intraday("PETR4", "B3", "1m"))
    assert delay == 15
    assert [b.time for b in bars] == [1791378000, 1791378060, 1791378180, 1791378240, 1791378300]
    assert isinstance(bars[0].time, int)
    assert (bars[0].open, bars[0].high, bars[0].low, bars[0].close) == (10.0, 10.2, 9.9, 10.1)
    assert bars[3].volume == 0.0 and bars[2].volume == 900.0


def test_yahoo_sem_campo_de_atraso():
    _, delay = run(yahoo(lambda r: httpx.Response(200, json=load("intraday_yahoo_sem_atraso.json")))
                   .fetch_intraday("PETR4", "B3", "5m"))
    assert delay is None


@pytest.mark.parametrize("bad", [-1, "15", True, None])
def test_yahoo_atraso_invalido_vira_none(bad):
    body = load("intraday_yahoo.json")
    body["chart"]["result"][0]["meta"]["exchangeDataDelayedBy"] = bad
    _, delay = run(yahoo(lambda r: httpx.Response(200, json=body)).fetch_intraday("PETR4", "B3", "1m"))
    assert delay is None


@pytest.mark.parametrize("market,sym,expected", [("US", "BRK.B", "BRK-B"), ("B3", "PETR4", "PETR4.SA"),
                                                   ("US", "AAPL", "AAPL")])
def test_yahoo_ticker_diario_e_intraday(market, sym, expected):
    reqs = []

    def h(req):
        reqs.append(req.url.raw_path.split(b"?")[0].decode())
        if req.url.params["interval"] == "1d":
            return httpx.Response(200, json=load("yahoo_petr4.json"))
        return httpx.Response(200, json=load("intraday_yahoo.json"))

    p = yahoo(h)
    run(p.fetch_daily(sym, market))
    run(p.fetch_intraday(sym, market, "1m"))
    assert reqs == [f"/v8/finance/chart/{expected}"] * 2


def test_yahoo_intraday_404():
    with pytest.raises(UnknownSymbol):
        run(yahoo(lambda r: httpx.Response(404)).fetch_intraday("XXXX", "US", "1m"))


def test_yahoo_intraday_429_depois_200():
    n = []

    def h(req):
        n.append(1)
        return httpx.Response(429) if len(n) == 1 else httpx.Response(200, json=load("intraday_yahoo.json"))

    bars, _ = run(yahoo(h).fetch_intraday("PETR4", "B3", "1m"))
    assert len(n) == 2 and len(bars) == 5


def test_yahoo_intraday_tudo_nulo():
    body = load("intraday_yahoo.json")
    q = body["chart"]["result"][0]["indicators"]["quote"][0]
    q["close"] = [None] * 6
    with pytest.raises(ProviderError, match="sem dados intraday"):
        run(yahoo(lambda r: httpx.Response(200, json=body)).fetch_intraday("PETR4", "B3", "1m"))


def test_yahoo_intervalo_nao_suportado():
    reqs = []
    with pytest.raises(ProviderError, match="intervalo não suportado"):
        run(yahoo(lambda r: reqs.append(r)).fetch_intraday("PETR4", "B3", "3m"))
    assert not reqs


# ---------- Binance ----------
def krow(t, o="1", h="2", l="0.5", c="1.5", v="10"):
    return [t, o, h, l, c, v, t + 59_999, "0", 0, "0", "0", "0"]


def test_binance_query_tempo_e_barra_corrente():
    reqs = []
    rows = [krow(1791400000000), krow(1791400060000), krow(1791400120000)]

    def h(req):
        reqs.append(req)
        return httpx.Response(200, json=rows)

    bars, delay = run(binance(h).fetch_intraday("BTC", "CRYPTO", "3m"))
    p = reqs[0].url.params
    assert (p["symbol"], p["interval"], p["limit"]) == ("BTCUSDT", "3m", "1000")
    assert len(reqs) == 1 and delay == 0
    assert [b.time for b in bars] == [1791400000, 1791400060, 1791400120]
    assert bars[-1].close == 1.5 and bars[0].volume == 10.0


def test_binance_intraday_fallback_de_host():
    hosts = []

    def h(req):
        hosts.append(req.url.host)
        return httpx.Response(451) if len(hosts) == 1 else httpx.Response(200, json=[krow(1791400000000)])

    bars, _ = run(binance(h).fetch_intraday("BTC", "CRYPTO", "1m"))
    assert hosts == ["api.binance.com", "data-api.binance.vision"] and len(bars) == 1


def test_binance_intraday_descarta_malformadas_e_nao_finitas():
    rows = [krow(1791400000000), [1791400060000, "x", "2", "1", "1", "1"], krow(1791400120000, c="nan"),
            krow(1791400180000, o="0"), [1791400240000], krow(1791400300000)]
    bars, _ = run(binance(lambda r: httpx.Response(200, json=rows)).fetch_intraday("BTC", "CRYPTO", "1m"))
    assert [b.time for b in bars] == [1791400000, 1791400300]


def test_binance_intraday_vazio():
    with pytest.raises(ProviderError):
        run(binance(lambda r: httpx.Response(200, json=[])).fetch_intraday("BTC", "CRYPTO", "1m"))


def test_binance_intraday_simbolo_invalido_e_intervalo():
    resp = httpx.Response(400, json={"code": -1121, "msg": "Invalid symbol."})
    with pytest.raises(UnknownSymbol):
        run(binance(lambda r: resp).fetch_intraday("ZZZ", "CRYPTO", "1m"))
    with pytest.raises(ProviderError, match="intervalo não suportado"):
        run(binance(lambda r: resp).fetch_intraday("BTC", "CRYPTO", "10m"))


# ---------- Sintético ----------
COUNTS = {"1m": 1500, "3m": 1000, "5m": 1500, "30m": 700, "1h": 900}
STEP = {"1m": 60, "3m": 180, "5m": 300, "30m": 1800, "1h": 3600}


@pytest.mark.parametrize("interval", list(COUNTS))
def test_sintetico_intraday_contagem_espacamento_e_consistencia(interval):
    p = SyntheticProvider()
    bars, delay = run(p.fetch_intraday("AAA", "US", interval))
    assert delay is None and len(bars) == COUNTS[interval]
    assert bars[-1].time == 1791403200
    assert all(b2.time - b1.time == STEP[interval] for b1, b2 in zip(bars, bars[1:]))
    assert all(b.high >= max(b.open, b.close) and b.low <= min(b.open, b.close) and b.low > 0 for b in bars)
    assert bars == run(p.fetch_intraday("AAA", "US", interval))[0]


def test_sintetico_intraday_varia_por_simbolo_e_intervalo():
    p = SyntheticProvider()
    a = run(p.fetch_intraday("AAA", "US", "1m"))[0]
    assert a != run(p.fetch_intraday("BBB", "US", "1m"))[0]
    assert [b.close for b in a[-1000:]] != [b.close for b in run(p.fetch_intraday("AAA", "US", "3m"))[0]]


def test_sintetico_intraday_simbolos_especiais():
    p = SyntheticProvider()
    with pytest.raises(UnknownSymbol):
        run(p.fetch_intraday("INVALIDO", "US", "1m"))
    with pytest.raises(ProviderError):
        run(p.fetch_intraday("FALHA1", "US", "1m"))
    assert len(run(p.fetch_intraday("CURTO1", "US", "5m"))[0]) == 50
    with pytest.raises(ProviderError, match="intervalo não suportado"):
        run(p.fetch_intraday("AAA", "US", "10m"))
