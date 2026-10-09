import pandas as pd
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


def _lote(start, n, close):
    return [c(d.strftime("%Y-%m-%d"), close) for d in pd.date_range(start, periods=n)]


def _closes(conn, a):
    return [(r["date"], r["close"]) for r in db.load_candles(conn, a)]


def test_replace_candles_apaga_o_que_saiu_da_janela(conn):
    a, outro = db.add_asset(conn, "AAPL", "US"), db.add_asset(conn, "MSFT", "US")
    db.upsert_candles(conn, a, [c("2024-01-02", 100), c("2024-01-03", 100), c("2024-01-04", 100)])
    db.upsert_candles(conn, outro, [c("2024-01-02", 7)])
    # janela reajustada (split 10:1) que já começa depois das duas primeiras datas
    lote = _lote("2024-01-04", db.MIN_TRIM_CANDLES, 10)
    assert db.replace_candles(conn, a, lote[::-1]) == db.MIN_TRIM_CANDLES == 250
    assert _closes(conn, a) == [(x.date, 10) for x in lote]
    assert _closes(conn, outro) == [("2024-01-02", 7)]


def test_replace_candles_lote_curto_nao_apaga_historico(conn):
    a = db.add_asset(conn, "AAPL", "US")
    db.upsert_candles(conn, a, [c("2024-01-02", 100), c("2024-01-03", 100)])
    # resposta curta do provedor: não é uma janela confiável, só faz o upsert
    assert db.replace_candles(conn, a, _lote("2024-01-03", 10, 10)) == 10
    got = _closes(conn, a)
    assert got[:2] == [("2024-01-02", 100), ("2024-01-03", 10)] and len(got) == 11
    assert db.replace_candles(conn, a, _lote("2024-01-04", db.MIN_TRIM_CANDLES - 1, 10)) == 249
    assert _closes(conn, a)[0] == ("2024-01-02", 100)


def test_replace_candles_lista_vazia_nao_apaga(conn):
    a = db.add_asset(conn, "AAPL", "US")
    db.upsert_candles(conn, a, [c("2024-01-02", 2)])
    assert db.replace_candles(conn, a, []) == 0
    assert _closes(conn, a) == [("2024-01-02", 2)]


@pytest.mark.parametrize("write", ["replace_candles", "upsert_candles"])
def test_escrita_de_candles_com_erro_no_meio_nao_muda_nada(conn, write):
    a = db.add_asset(conn, "AAPL", "US")
    db.upsert_candles(conn, a, [c("2024-01-02", 2), c("2024-01-03", 3)])
    with pytest.raises(Exception):
        # lote grande o bastante para apagar o histórico; a última linha não é gravável
        getattr(db, write)(conn, a, _lote("2024-01-03", 250, 9) + [c("2025-01-01", object())])
    assert not conn.in_transaction
    assert _closes(conn, a) == [("2024-01-02", 2), ("2024-01-03", 3)]


def test_upsert_rf_com_erro_no_meio_nao_muda_nada(conn):
    db.upsert_rf(conn, [("2024-01-02", 0.0003)])
    with pytest.raises(Exception):
        db.upsert_rf(conn, [("2024-01-02", 0.0009), ("2024-01-03", None)])  # rate é NOT NULL
    assert not conn.in_transaction
    assert db.load_rf(conn) == [("2024-01-02", 0.0003)]


def test_delete_asset_com_erro_nao_apaga_candles(conn):
    a = db.add_asset(conn, "AAPL", "US")
    db.upsert_candles(conn, a, [c("2024-01-02", 2)])
    conn.execute("CREATE TRIGGER trava BEFORE DELETE ON assets BEGIN SELECT RAISE(ABORT, 'travado'); END")
    with pytest.raises(Exception):
        db.delete_asset(conn, a)
    assert not conn.in_transaction
    assert len(db.load_candles(conn, a)) == 1 and db.get_asset(conn, a)
