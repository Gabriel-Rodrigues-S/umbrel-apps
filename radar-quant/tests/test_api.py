import asyncio
import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import analysis, service
from app.config import get_settings
from app.main import create_app


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("RADAR_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RADAR_PROVIDER", "synthetic")
    monkeypatch.setenv("RADAR_SKIP_BACKGROUND", "1")
    analysis.invalidate()
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
    assert client.get(f"/api/assets/{aid}/candles?interval=5m").status_code == 422
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
    aid = _id(client, "AAPL")
    assert client.delete(f"/api/assets/{aid}").status_code == 204
    assert client.delete(f"/api/assets/{aid}").status_code == 404


def test_refresh_schedules(client):
    r = client.post("/api/refresh")
    assert r.status_code == 202 and r.json() == {"status": "agendado"}


def test_no_nan_in_responses(client):
    aid = _id(client, "AAPL")
    for url in ("/api/assets", f"/api/assets/{aid}/candles", f"/api/assets/{aid}/analysis",
                "/api/ranking", "/api/portfolio", "/api/health"):
        text = client.get(url).text
        assert "NaN" not in text and "Infinity" not in text
        json.loads(text)


def test_static_index(client):
    r = client.get("/")
    assert r.status_code == 200 and "text/html" in r.headers["content-type"]


def test_asset_without_data(client):
    r = client.post("/api/assets", json={"symbol": "FALHA1", "market": "US"})
    assert r.status_code == 201 and r.json()["status"] == "insuficiente" and r.json()["last_error"]
    aid = r.json()["id"]
    assert client.get(f"/api/assets/{aid}/candles").status_code == 200
    assert client.get(f"/api/assets/{aid}/analysis").status_code == 200


@pytest.mark.parametrize("symbol", ["AB\x00CD", "../../x", "A" * 100])
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


def test_espera_do_laco_encurta_quando_ha_erro(client):
    from app.main import sleep_seconds
    assert sleep_seconds(client.app) == 6 * 3600
    aid = client.post("/api/assets", json={"symbol": "FALHA1", "market": "US"}).json()["id"]
    assert sleep_seconds(client.app) == 600
    client.delete(f"/api/assets/{aid}")
    assert sleep_seconds(client.app) == 6 * 3600
