import asyncio
import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import analysis, catalog, db, main, news, screener, service, universe
from app.config import INTERVALS, get_settings
from app.providers.base import ProviderError
from app.main import create_app, next_sleep


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("RADAR_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RADAR_PROVIDER", "synthetic")
    monkeypatch.setenv("RADAR_SKIP_BACKGROUND", "1")
    monkeypatch.setenv("RADAR_UNIVERSE", "0")
    analysis.invalidate()
    service.clear_intraday_cache()
    with TestClient(create_app()) as c:
        asyncio.run(service.refresh_all(c.app.state.conn, get_settings()))
        analysis.invalidate()
        yield c
    analysis.invalidate()


def _id(c, symbol):
    return next(a["id"] for a in c.get("/api/assets").json() if a["symbol"] == symbol)


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok" and body["assets"] == 13 and body["last_refresh"]
    assert r.headers["cache-control"] == "no-store"


def test_assets(client):
    items = client.get("/api/assets").json()
    assert len(items) == 13
    assert all(a["status"] == "ok" and a["verdict"] in {"comprar", "manter", "vender"} for a in items)


def test_candles(client):
    aid = _id(client, "AAPL")
    r = client.get(f"/api/assets/{aid}/candles")
    assert r.status_code == 200 and r.json()["candles"]
    assert client.get(f"/api/assets/{aid}/candles?interval=1wk").status_code == 200
    assert client.get(f"/api/assets/{aid}/candles?interval=2m").status_code == 422
    assert client.get("/api/assets/9999/candles").status_code == 404


def test_analysis(client):
    aid = _id(client, "AAPL")
    r = client.get(f"/api/assets/{aid}/analysis")
    assert r.status_code == 200 and "evidence" in r.json()["backtest"]
    assert client.get("/api/assets/9999/analysis").status_code == 404


def test_ranking(client):
    assert len(client.get("/api/ranking?market=CRYPTO").json()) == 2
    assert len(client.get("/api/ranking").json()) == 13
    assert client.get("/api/ranking?market=XX").status_code == 422


def test_portfolio(client):
    r = client.get("/api/portfolio")
    assert r.status_code == 200
    assert sum(w["weight"] for w in r.json()["weights"]) == pytest.approx(1)
    assert client.get("/api/portfolio?method=min_variance").status_code == 200
    assert client.get("/api/portfolio?method=x").status_code == 422
    assert client.get("/api/portfolio?market=CRYPTO").status_code == 200
    assert client.get("/api/portfolio?market=XX").status_code == 422


def test_create_asset_and_duplicates(client):
    r = client.post("/api/assets", json={"symbol": " tsla ", "market": "US"})
    assert r.status_code == 201 and r.json()["symbol"] == "TSLA"
    assert client.post("/api/assets", json={"symbol": "TSLA", "market": "US"}).status_code == 409
    r = client.post("/api/assets", json={"symbol": "PETR4.SA", "market": "B3"})
    assert r.status_code == 409 and r.json()["detail"] == "ativo já está na watchlist"
    assert client.post("/api/assets", json={"symbol": "btcusdt", "market": "CRYPTO"}).status_code == 409


def test_create_asset_invalid(client):
    n = len(client.get("/api/assets").json())
    r = client.post("/api/assets", json={"symbol": "INVALIDO", "market": "US"})
    assert r.status_code == 422 and r.json()["detail"] == "símbolo não encontrado em US"
    assert len(client.get("/api/assets").json()) == n
    assert client.post("/api/assets", json={"symbol": "X", "market": "LSE"}).status_code == 422
    assert client.post("/api/assets", json={"symbol": " ", "market": "US"}).status_code == 422


def test_short_history(client):
    r = client.post("/api/assets", json={"symbol": "CURTO1", "market": "US"})
    assert r.status_code == 201 and r.json()["status"] == "insuficiente"
    a = client.get(f"/api/assets/{r.json()['id']}/analysis")
    assert a.status_code == 200 and a.json()["status"] == "insuficiente"
    assert client.get("/api/ranking").status_code == 200
    assert client.get("/api/portfolio").status_code == 200


def test_delete(client):
    aid = _id(client, "BTC")
    assert client.delete(f"/api/assets/{aid}").status_code == 204
    assert client.delete(f"/api/assets/{aid}").status_code == 404


def test_refresh_schedules(client):
    r = client.post("/api/refresh")
    assert r.status_code == 202 and r.json() == {"status": "agendado"}


def test_no_nan_in_responses(client):
    aid = _id(client, "AAPL")
    for url in ("/api/assets", f"/api/assets/{aid}/candles", f"/api/assets/{aid}/analysis",
                "/api/ranking", "/api/portfolio", "/api/health", "/api/search?q=a", f"/api/assets/{aid}/news",
                "/api/screener", "/api/screener/summary", "/api/screener/progress",
                *(f"/api/assets/{aid}/candles?interval={i}" for i in INTERVALS)):
        text = client.get(url).text
        assert "NaN" not in text and "Infinity" not in text
        json.loads(text)


def test_static_index(client):
    r = client.get("/")
    assert r.status_code == 200 and "text/html" in r.headers["content-type"]


def test_asset_without_data(client):
    n = len(client.get("/api/assets").json())
    r = client.post("/api/assets", json={"symbol": "FALHA1", "market": "US"})
    assert r.status_code == 502 and r.json()["detail"] == "fonte de dados indisponível agora"
    assert len(client.get("/api/assets").json()) == n and db.find_asset(client.app.state.conn, "FALHA1", "US") is None
    # ativo já gravado e com erro de refresh (sem candles) continua legível
    c = client.app.state.conn
    aid = db.add_asset(c, "FALHA2", "US")
    asyncio.run(service.refresh_asset(c, db.get_asset(c, aid), get_settings()))
    assert db.get_asset(c, aid)["last_error"]
    item = next(a for a in client.get("/api/assets").json() if a["id"] == aid)
    assert item["status"] == "insuficiente" and item["last_error"] and item["price"] is None
    r = client.get(f"/api/assets/{aid}/candles")
    assert r.status_code == 200 and r.json()["candles"] == []
    r = client.get(f"/api/assets/{aid}/analysis")
    assert r.status_code == 200 and r.json()["status"] == "insuficiente"


@pytest.mark.parametrize("symbol", ["AB\x00CD", "../../x", "A" * 32])  # acima de 32 o modelo recusa antes
def test_create_asset_simbolo_invalido(client, symbol):
    n = len(client.get("/api/assets").json())
    r = client.post("/api/assets", json={"symbol": symbol, "market": "US"})
    assert r.status_code == 422 and r.json()["detail"] == "símbolo inválido"
    assert len(client.get("/api/assets").json()) == n


def test_create_asset_erro_inesperado_apaga_o_ativo(client, monkeypatch):
    class Explode:
        async def fetch_daily(self, symbol, market):
            raise RuntimeError("bug no provedor")

    monkeypatch.setattr(service, "get_provider", lambda market, settings: Explode())
    n = len(client.get("/api/assets").json())
    with pytest.raises(RuntimeError):
        client.post("/api/assets", json={"symbol": "TSLA", "market": "US"})
    assets = client.get("/api/assets").json()
    assert len(assets) == n and all(a["symbol"] != "TSLA" for a in assets)


def test_static_cache_control(client):
    for url in ("/", "/app.js", "/style.css"):
        r = client.get(url)
        assert r.status_code == 200 and r.headers["cache-control"] == "no-cache"
    assert client.get("/api/assets").headers["cache-control"] == "no-store"


def test_candles_semanal_e_mensal_terminam_na_ultima_data_real(client):
    aid = _id(client, "AAPL")
    last = {i: client.get(f"/api/assets/{aid}/candles?interval={i}").json()["candles"][-1]["time"]
            for i in ("1d", "1wk", "1mo")}
    assert last == {"1d": "2026-10-07", "1wk": "2026-10-07", "1mo": "2026-10-07"}
    assert client.get(f"/api/assets/{aid}/analysis").json()["equity"][-1]["date"] == "2026-10-07"


def test_refresh_em_andamento_nao_agenda_outro(client):
    client.app.state.refresh_lock = SimpleNamespace(locked=lambda: True)
    r = client.post("/api/refresh")
    assert r.status_code == 202 and r.json() == {"status": "em andamento"}
    assert not client.app.state.tasks


@pytest.mark.parametrize("asset_id", ["999999999999999999999", str(2**63), "0", "-1"])
def test_id_fora_do_intervalo(client, asset_id):
    assert client.get(f"/api/assets/{asset_id}/analysis").status_code == 422
    assert client.get(f"/api/assets/{asset_id}/candles").status_code == 422
    assert client.delete(f"/api/assets/{asset_id}").status_code == 422
    assert client.get(f"/api/assets/{2**63 - 1}/analysis").status_code == 404


def test_next_sleep_limita_esperas_curtas():
    n, esperas = 0, []
    for _ in range(5):  # erro persistente: 3 esperas curtas, depois o intervalo normal
        s, n = next_sleep(True, n, 6)
        esperas.append(s)
    assert esperas == [600, 600, 600, 6 * 3600, 6 * 3600] and n == 3
    assert next_sleep(False, n, 6) == (6 * 3600, 0)  # refresh limpo zera o contador
    assert next_sleep(False, 0, 6) == (6 * 3600, 0)
    assert next_sleep(True, 0, 6) == (600, 1)
    assert next_sleep(True, 0, 0.1) == (360, 1)  # intervalo configurado menor que a espera curta


def test_laco_usa_espera_curta_e_depois_volta_ao_normal(client, monkeypatch):
    db.add_asset(client.app.state.conn, "FALHA1", "US")
    esperas = []

    async def fake_sleep(s):
        esperas.append(s)
        if len(esperas) == 5:
            raise asyncio.CancelledError

    monkeypatch.setattr(main.asyncio, "sleep", fake_sleep)
    client.app.state.refresh_lock = asyncio.Lock()
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(main.loop_refresh(client.app))
    assert esperas == [600, 600, 600, 6 * 3600, 6 * 3600]


# ---------- 1.1: busca, abrir, intraday, notícias, screener ----------

def _open(c, symbol="AMZN", market="US"):
    return c.post("/api/assets/open", json={"symbol": symbol, "market": market})


def test_search(client):
    r = client.get("/api/search?q=pet")
    assert r.status_code == 200 and r.json()[0]["symbol"] == "PETR4"
    assert set(r.json()[0]) == {"symbol", "market", "name", "kind", "indices"}
    assert client.get("/api/search?q=").json() == []
    assert client.get("/api/search?q=%25").status_code == 200
    assert len(client.get("/api/search?q=a&limit=2").json()) == 2
    for bad in ("limit=0", "limit=99", "limit=x", "q=" + "a" * 65):
        assert client.get(f"/api/search?{bad}").status_code == 422


def test_open_asset(client):
    r = _open(client)
    assert r.status_code == 200 and r.json()["symbol"] == "AMZN" and r.json()["watch"] is False
    assert len(client.get("/api/assets").json()) == 13
    a = client.get(f"/api/assets/{r.json()['id']}/analysis")
    assert a.status_code == 200 and "swing" in a.json()
    assert _open(client).status_code == 200  # reabrir é idempotente


def test_open_asset_invalid(client):
    n = len(db.list_assets(client.app.state.conn, watch=None))
    r = _open(client, "INVALIDO")
    assert r.status_code == 422 and r.json()["detail"] == "símbolo não encontrado em US"
    assert _open(client, "AB\x00CD").status_code == 422
    assert _open(client, "AMZN", "XX").status_code == 422
    assert client.post("/api/assets/open", json={"symbol": "AMZN"}).status_code == 422
    assert len(db.list_assets(client.app.state.conn, watch=None)) == n


def test_open_asset_fonte_fora_do_ar(client):
    n = len(db.list_assets(client.app.state.conn, watch=None))
    r = _open(client, "FALHA1")
    assert r.status_code == 502 and r.json()["detail"] == "fonte de dados indisponível agora"
    assert len(db.list_assets(client.app.state.conn, watch=None)) == n


def test_promote_and_demote(client):
    aid = _open(client).json()["id"]
    r = client.post("/api/assets", json={"symbol": "amzn", "market": "US"})
    assert r.status_code == 201 and r.json()["watch"] is True and r.json()["id"] == aid
    assert len(client.get("/api/assets").json()) == 14
    assert client.post("/api/assets", json={"symbol": "AMZN", "market": "US"}).status_code == 409
    assert client.delete(f"/api/assets/{aid}").status_code == 204  # membro de SP500: só rebaixa
    assert len(client.get("/api/assets").json()) == 13
    assert client.get(f"/api/assets/{aid}/analysis").status_code == 200
    assert db.get_asset(client.app.state.conn, aid)["watch"] == 0


def test_delete_fora_de_indice_apaga(client):
    aid = _open(client, "BTC", "CRYPTO").json()["id"]  # já na watchlist, fora de índice
    assert client.delete(f"/api/assets/{aid}").status_code == 204
    assert client.delete(f"/api/assets/{aid}").status_code == 404
    vis = _open(client, "ZZZZ", "US").json()["id"]  # visitado, fora de índice
    assert client.delete(f"/api/assets/{vis}").status_code == 204
    assert client.get(f"/api/assets/{vis}/analysis").status_code == 404


def test_add_grava_linha_do_screener(client):
    r = client.post("/api/assets", json={"symbol": "TSLA", "market": "US"})
    assert any(x["asset_id"] == r.json()["id"] for x in db.load_screener(client.app.state.conn))


@pytest.mark.parametrize("interval", INTERVALS)
def test_candles_todos_os_intervalos(client, interval):
    aid = _id(client, "AAPL")
    r = client.get(f"/api/assets/{aid}/candles?interval={interval}")
    assert r.status_code == 200
    body = r.json()
    assert body["interval"] == interval and body["candles"]
    if interval in ("1m", "3m", "5m", "10m", "30m", "1h"):
        assert body["intraday"] is True and isinstance(body["candles"][0]["time"], int)
        assert body["last_bar_time"] == body["candles"][-1]["time"] and "delay_minutes" in body
    else:
        assert not body.get("intraday") and isinstance(body["candles"][0]["time"], str)


def test_candles_intraday_indisponivel(client, monkeypatch):
    class OnlyDaily:
        NATIVE_INTRADAY = frozenset({"1m", "5m", "30m", "1h"})

        async def fetch_intraday(self, symbol, market, interval):
            raise ProviderError("fora do ar")

    monkeypatch.setattr(service, "get_provider", lambda market, settings: OnlyDaily())
    aid = _id(client, "AAPL")
    r = client.get(f"/api/assets/{aid}/candles?interval=5m")
    assert r.status_code == 422 and r.json()["detail"] == "intraday indisponível para este ativo agora"
    assert client.get(f"/api/assets/{aid}/candles?interval=1wk").status_code == 200


def test_news(client):
    aid = _id(client, "AAPL")
    r = client.get(f"/api/assets/{aid}/news")
    assert r.status_code == 200 and len(r.json()["items"]) == 3 and r.json()["stale"] is False
    assert client.get("/api/assets/9999/news").status_code == 404
    assert client.get("/api/assets/0/news").status_code == 422


def test_news_nunca_derruba(client, monkeypatch):
    async def boom(*a, **k):
        raise RuntimeError("x")

    monkeypatch.setattr(news, "fetch_news", boom)
    monkeypatch.setattr(client.app.state, "settings", SimpleNamespace(provider="live"))
    r = client.get(f"/api/assets/{_id(client, 'AAPL')}/news")
    assert r.status_code == 200 and r.json()["stale"] is True


def test_screener(client):
    # "total 0" depende de nenhuma linha da watchlist ter sido gravada ainda (AAPL, MSFT e NVDA são do SP500)
    assert db.load_screener(client.app.state.conn) == []
    assert client.get("/api/screener?scope=SP500").json()["total"] == 0  # universo ainda não rodou
    r = client.get("/api/screener")
    assert r.status_code == 200 and r.json()["scope"] == "watchlist" and r.json()["total"] == 13
    assert all(row["setups"].keys() == {"reversao", "queda", "rompimento"} for row in r.json()["rows"])
    asyncio.run(universe.refresh_universe(client.app.state.conn, get_settings(), pace=0))
    assert client.get("/api/screener?scope=SP500").json()["total"] == 8
    assert client.get("/api/screener?scope=NDX&sort=symbol&order=asc").json()["rows"][0]["symbol"] == "AAPL"
    for q in ("setup=reversao", "verdict=comprar", "evidence=sem_evidencia", "market=US", "sort=symbol&order=asc"):
        assert client.get(f"/api/screener?{q}").status_code == 200
    p2 = client.get("/api/screener?page_size=5&page=2").json()
    assert p2["page"] == 2 and len(p2["rows"]) == 5 and p2["total"] == 13
    for bad in ("scope=XX", "sort=__class__", "page=0", "page_size=201", "verdict=x", "scope=" + "a" * 33):
        assert client.get(f"/api/screener?{bad}").status_code == 422, bad


def test_screener_summary_e_progress(client):
    r = client.get("/api/screener/summary?scope=watchlist")
    assert r.status_code == 200 and len(r.json()["setups"]) == 3 and r.json()["count"] == 13
    assert 0 <= r.json()["pct_above_sma200"] <= 1
    assert client.get("/api/screener/summary?scope=XX").status_code == 422
    r = client.get("/api/screener/progress?scope=IBRA")
    assert r.status_code == 200 and r.json()["total"] == 8
    assert set(r.json()) == {"scope", "total", "ready", "insufficient", "failed"}
    assert client.get("/api/screener/progress?scope=XX").status_code == 422


def test_health_catalogo_e_universo(client):
    c = client.app.state.conn
    h = client.get("/api/health").json()
    total = len(db.index_members(c))
    assert h["catalog"] > 0 and set(h["universe"]) == {"total", "ready"} and h["universe"]["total"] == total
    assert 0 < h["universe"]["ready"] < total  # só os membros que já estão na watchlist têm dados
    asyncio.run(universe.refresh_universe(c, get_settings(), pace=0))
    h = client.get("/api/health").json()
    assert h["universe"]["ready"] == h["universe"]["total"] == total


def test_health_nao_varre_o_screener(client, monkeypatch):
    monkeypatch.setattr(db, "load_screener", lambda *a, **k: pytest.fail("health leu o screener"))
    assert client.get("/api/health").status_code == 200


def test_open_repetido_nao_recomputa(client, monkeypatch):
    calls = []
    real = screener.store_row
    monkeypatch.setattr(screener, "store_row", lambda c, a: calls.append(a["symbol"]) or real(c, a))
    assert _open(client).status_code == 200
    assert calls == ["AMZN"]
    computed = []
    real_compute = analysis._compute
    monkeypatch.setattr(analysis, "_compute", lambda *a: computed.append(1) or real_compute(*a))
    for _ in range(3):
        assert _open(client).status_code == 200
    assert calls == ["AMZN"] and computed == []
    # promover também não recalcula
    assert client.post("/api/assets", json={"symbol": "AMZN", "market": "US"}).status_code == 201
    assert calls == ["AMZN"] and computed == []


def test_open_regrava_se_refresh_novo_ou_sem_linha(client, monkeypatch):
    aid = _open(client).json()["id"]
    c = client.app.state.conn
    calls = []
    real = screener.store_row
    monkeypatch.setattr(screener, "store_row", lambda c_, a: calls.append(1) or real(c_, a))
    c.execute("DELETE FROM screener WHERE asset_id = ?", (aid,))  # sem linha válida
    c.commit()
    assert _open(client).status_code == 200 and len(calls) == 1
    c.execute("UPDATE assets SET last_refresh = '2000-01-01T00:00:00+00:00' WHERE id = ?", (aid,))  # velho: refresh
    c.commit()
    assert _open(client).status_code == 200 and len(calls) == 2


def test_rotas_novas_sem_cache(client):
    aid = _id(client, "AAPL")
    for url in ("/api/search?q=a", f"/api/assets/{aid}/news", "/api/screener", "/api/screener/summary",
                "/api/screener/progress", f"/api/assets/{aid}/candles?interval=5m"):
        assert client.get(url).headers["cache-control"] == "no-store", url
    assert _open(client).headers["cache-control"] == "no-store"


def test_falha_do_catalogo_nao_derruba_o_laco(client, monkeypatch):
    async def boom(*a, **k):
        raise RuntimeError("fonte do catálogo caiu")

    esperas = []

    async def fake_sleep(s):
        esperas.append(s)
        raise asyncio.CancelledError

    monkeypatch.setattr(catalog, "catalog_is_stale", lambda conn: True)
    monkeypatch.setattr(catalog, "refresh_catalog", boom)
    monkeypatch.setattr(main.asyncio, "sleep", fake_sleep)
    client.app.state.refresh_lock = asyncio.Lock()
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(main.loop_refresh(client.app))
    assert esperas  # chegou ao sleep: a falha do catálogo foi engolida


def test_loop_universo_sem_passada_devida(client, monkeypatch):
    chamadas = []

    async def fake_refresh(*a, **k):
        chamadas.append("refresh")

    async def fake_sleep(s):
        chamadas.append(s)
        raise asyncio.CancelledError

    monkeypatch.setattr(universe, "universe_due", lambda conn, now: False)
    monkeypatch.setattr(universe, "refresh_universe", fake_refresh)
    monkeypatch.setattr(main.asyncio, "sleep", fake_sleep)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(main.loop_universe(client.app))
    assert chamadas == [600]


def test_loop_universo_intervalo_conforme_membros(client, monkeypatch):
    esperas = []

    async def fake_sleep(s):
        esperas.append(s)
        raise asyncio.CancelledError

    monkeypatch.setattr(universe, "universe_due", lambda conn, now: False)
    monkeypatch.setattr(main.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(db, "index_members", lambda conn, index=None: [])
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(main.loop_universe(client.app))
    assert esperas == [60]


def test_refresh_everything_grava_screener_da_watchlist(client):
    db.upsert_screener(client.app.state.conn, _id(client, "AAPL"), "x", {"status": "insuficiente"})
    asyncio.run(main.refresh_everything(client.app))
    rows = {r["asset_id"]: r for r in db.load_screener(client.app.state.conn)}
    assert len(rows) == 13 and rows[_id(client, "AAPL")]["payload"].get("symbol") == "AAPL"


def test_loop_universo(client, monkeypatch):
    chamadas = []

    async def fake_refresh(conn, settings, **kw):
        chamadas.append("refresh")
        raise RuntimeError("fonte caiu")  # não pode derrubar o laço

    async def fake_sleep(s):
        chamadas.append(s)
        if chamadas.count(600) == 2:
            raise asyncio.CancelledError

    monkeypatch.setattr(universe, "refresh_universe", fake_refresh)
    monkeypatch.setattr(main.asyncio, "sleep", fake_sleep)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(main.loop_universe(client.app))
    assert chamadas == ["refresh", 600, "refresh", 600]  # nunca rodou nesse banco: sempre devido


def test_catalogo_sintetico_na_subida(client):
    assert db.catalog_count(client.app.state.conn) > 0


# ---------- revisão final ----------

def test_campos_novos_nas_rotas(client):
    aid = _id(client, "PETR4")
    assert client.get(f"/api/assets/{aid}/analysis").json()["session_open"] is False
    assert all(a["session_open"] is False for a in client.get("/api/assets").json())
    r = client.get("/api/screener").json()
    assert r["stale_rows"] == 0 and all(row["session_open"] is False for row in r["rows"])
    assert all(row["name"] for row in r["rows"])


@pytest.mark.parametrize("route", ["/api/assets", "/api/assets/open"])
def test_new_asset_limita_tamanho(client, route):
    r = client.post(route, json={"symbol": "A" * 33, "market": "US"})
    assert r.status_code == 422 and r.json()["detail"][0]["type"] == "string_too_long"
    r = client.post(route, json={"symbol": "AMZN", "market": "U" * 9})
    assert r.status_code == 422 and r.json()["detail"][0]["type"] == "string_too_long"
    assert client.post(route, json={"symbol": "A" * 32, "market": "US"}).json()["detail"] == "símbolo inválido"


@pytest.mark.parametrize("route", ["/api/assets", "/api/assets/open"])
def test_ativo_some_entre_abrir_e_resumir(client, monkeypatch, route):
    async def fantasma(conn, symbol, market, settings):
        return {"id": 987654, "symbol": "AMZN", "market": "US", "last_refresh": None}
    monkeypatch.setattr(service, "open_asset", fantasma)
    r = TestClient(client.app, raise_server_exceptions=False).post(route, json={"symbol": "AMZN", "market": "US"})
    assert r.status_code == 502 and r.json()["detail"] == "ativo removido durante a abertura"
