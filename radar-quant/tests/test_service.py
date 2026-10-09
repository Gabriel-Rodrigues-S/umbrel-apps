import asyncio

import pandas as pd
import pytest

from app import db, service
from app.config import DEFAULT_WATCHLIST, Settings
from app.providers.base import Candle, ProviderError, UnknownSymbol


@pytest.fixture
def conn(tmp_path):
    return db.connect(tmp_path / "radar.db")


@pytest.fixture
def settings(tmp_path):
    return Settings(data_dir=tmp_path, provider="synthetic", refresh_hours=6)


class Quebrado:
    def __init__(self, exc):
        self.exc = exc

    async def fetch_daily(self, symbol, market):
        raise self.exc


def test_seed_watchlist_idempotente(conn):
    service.seed_watchlist(conn)
    service.seed_watchlist(conn)
    assert len(db.list_assets(conn)) == len(DEFAULT_WATCHLIST) == 13


def test_refresh_all_grava_candles(conn, settings):
    service.seed_watchlist(conn)
    asyncio.run(service.refresh_all(conn, settings))
    for a in db.list_assets(conn):
        df = service.load_frame(conn, a["id"])
        assert len(df) == 1500 and a["last_error"] is None
        assert isinstance(df.index, pd.DatetimeIndex) and df.index.is_monotonic_increasing
        assert list(df.columns) == ["open", "high", "low", "close", "volume"]


def test_refresh_all_isola_falha(conn, settings):
    ok = db.add_asset(conn, "PETR4", "B3")
    bad = db.add_asset(conn, "FALHA1", "B3")
    asyncio.run(service.refresh_all(conn, settings))
    assert len(db.load_candles(conn, ok)) == 1500
    assert db.get_asset(conn, ok)["last_error"] is None
    assert "indisponível" in db.get_asset(conn, bad)["last_error"]
    assert db.load_candles(conn, bad) == []


def test_falha_preserva_candles_antigos(conn, settings):
    a = db.add_asset(conn, "PETR4", "B3")
    db.upsert_candles(conn, a, [Candle("2024-01-02", 1, 1, 1, 1, 1)])
    asset = db.get_asset(conn, a)
    asyncio.run(service.refresh_asset(conn, asset, settings, provider=Quebrado(ProviderError("fora do ar"))))
    assert len(db.load_candles(conn, a)) == 1
    assert db.get_asset(conn, a)["last_error"] == "fora do ar"


def test_unknown_symbol_relanca_e_grava(conn, settings):
    a = db.add_asset(conn, "INVALID1", "US")
    with pytest.raises(UnknownSymbol):
        asyncio.run(service.refresh_asset(conn, db.get_asset(conn, a), settings))
    assert "INVALID1" in db.get_asset(conn, a)["last_error"]


def test_refresh_all_nao_para_em_unknown_symbol(conn, settings):
    db.add_asset(conn, "INVALID1", "US")
    ok = db.add_asset(conn, "AAPL", "US")
    asyncio.run(service.refresh_all(conn, settings))
    assert len(db.load_candles(conn, ok)) == 1500


def test_resample_semanal_e_mensal():
    idx = pd.bdate_range("2024-01-01", periods=10)
    df = pd.DataFrame({"open": range(10, 20), "high": range(20, 30), "low": range(0, 10),
                       "close": range(100, 110), "volume": [1.0] * 10}, index=idx)
    w = service.resample(df, "1wk")
    assert len(w) == 2
    assert w.iloc[0]["open"] == 10 and w.iloc[0]["close"] == 104 and w.iloc[0]["volume"] == 5
    assert w.iloc[0]["high"] == 24 and w.iloc[0]["low"] == 0
    assert len(service.resample(df, "1mo")) == 1
    assert service.resample(df, "1d") is df
    with pytest.raises(ValueError):
        service.resample(df, "2h")


def test_load_rf_series(conn):
    assert service.load_rf_series(conn).empty
    db.upsert_rf(conn, [("2024-01-03", 0.0004), ("2024-01-02", 0.0005)])
    rf = service.load_rf_series(conn)
    assert isinstance(rf.index, pd.DatetimeIndex) and rf.iloc[0] == 0.0005
