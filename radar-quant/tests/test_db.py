import pytest

from app import db
from app.providers.base import Candle


@pytest.fixture
def conn(tmp_path):
    return db.connect(tmp_path / "sub" / "radar.db")


def c(date, close):
    return Candle(date, close, close, close, close, 1.0)


def test_add_e_list(conn):
    a = db.add_asset(conn, "PETR4", "B3")
    b = db.add_asset(conn, "AAPL", "US")
    rows = db.list_assets(conn)
    assert [r["id"] for r in rows] == [a, b]
    assert rows[0]["currency"] == "BRL" and rows[1]["currency"] == "USD"
    assert rows[1]["position"] == rows[0]["position"] + 1
    assert db.get_asset(conn, a)["symbol"] == "PETR4"
    assert db.get_asset(conn, 999) is None


def test_duplicado(conn):
    db.add_asset(conn, "PETR4", "B3")
    with pytest.raises(db.DuplicateAsset):
        db.add_asset(conn, "PETR4", "B3")


def test_upsert_candles_substitui_e_ordena(conn):
    a = db.add_asset(conn, "AAPL", "US")
    assert db.upsert_candles(conn, a, [c("2024-01-03", 3), c("2024-01-02", 2)]) == 2
    db.upsert_candles(conn, a, [c("2024-01-02", 9)])
    rows = db.load_candles(conn, a)
    assert [r["date"] for r in rows] == ["2024-01-02", "2024-01-03"]
    assert rows[0]["close"] == 9


def test_delete_remove_candles(conn):
    a = db.add_asset(conn, "AAPL", "US")
    db.upsert_candles(conn, a, [c("2024-01-02", 2)])
    assert db.delete_asset(conn, a) is True
    assert db.load_candles(conn, a) == []
    assert db.get_asset(conn, a) is None
    assert db.delete_asset(conn, a) is False


def test_refresh_status(conn):
    a = db.add_asset(conn, "AAPL", "US")
    db.set_refresh_status(conn, a, "falhou")
    r = db.get_asset(conn, a)
    assert r["last_error"] == "falhou" and r["last_refresh"]
    db.set_refresh_status(conn, a, None)
    assert db.get_asset(conn, a)["last_error"] is None


def test_rf_ida_e_volta(conn):
    db.upsert_rf(conn, [("2024-01-03", 0.0004), ("2024-01-02", 0.0003)])
    db.upsert_rf(conn, [("2024-01-02", 0.0005)])
    assert db.load_rf(conn) == [("2024-01-02", 0.0005), ("2024-01-03", 0.0004)]
