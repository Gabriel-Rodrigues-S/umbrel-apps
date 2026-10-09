import asyncio
import json

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
