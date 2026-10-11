import sqlite3

import pytest

from app import db
from app.providers.base import Candle

# Schema exato da 1.0.0 (user_version = 0).
_SCHEMA_100 = """
CREATE TABLE IF NOT EXISTS assets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    market TEXT NOT NULL,
    name TEXT,
    currency TEXT NOT NULL,
    position INTEGER NOT NULL,
    last_refresh TEXT,
    last_error TEXT,
    UNIQUE (symbol, market)
);
CREATE TABLE IF NOT EXISTS candles (
    asset_id INTEGER NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
    date TEXT NOT NULL,
    open REAL, high REAL, low REAL, close REAL, volume REAL,
    PRIMARY KEY (asset_id, date)
);
CREATE TABLE IF NOT EXISTS rf_rates (
    date TEXT PRIMARY KEY,
    rate REAL NOT NULL
);
"""


def _banco_100(path):
    raw = sqlite3.connect(path)
    raw.executescript(_SCHEMA_100)
    raw.execute("INSERT INTO assets (symbol, market, currency, position) VALUES ('PETR4','B3','BRL',1)")
    raw.execute("INSERT INTO assets (symbol, market, currency, position) VALUES ('AAPL','US','USD',2)")
    raw.execute("INSERT INTO candles VALUES (1,'2024-01-02',1,2,0.5,1.5,100)")
    raw.execute("INSERT INTO candles VALUES (2,'2024-01-02',3,4,2.5,3.5,200)")
    raw.execute("INSERT INTO rf_rates VALUES ('2024-01-02', 0.11)")
    raw.commit()
    raw.close()


def _estado(conn):
    return (conn.execute("PRAGMA user_version").fetchone()[0],
            [dict(r) for r in conn.execute("SELECT * FROM assets ORDER BY id")],
            [tuple(r) for r in conn.execute("SELECT * FROM candles ORDER BY asset_id, date")],
            db.load_rf(conn))


def _tabelas(conn):
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def test_migra_banco_100_preservando_dados(tmp_path):
    p = tmp_path / "radar.db"
    _banco_100(p)
    conn = db.connect(p)
    user_version, assets, candles, rf = _estado(conn)
    assert user_version == db.SCHEMA_VERSION == 2
    assert [a["symbol"] for a in assets] == ["PETR4", "AAPL"]
    assert all(a["watch"] == 1 and a["last_viewed"] is None for a in assets)
    assert candles == [(1, "2024-01-02", 1, 2, 0.5, 1.5, 100), (2, "2024-01-02", 3, 4, 2.5, 3.5, 200)]
    assert rf == [("2024-01-02", 0.11)]
    assert {"catalog", "screener", "news", "meta"} <= _tabelas(conn)
    assert len(db.list_assets(conn)) == 2


def test_migracao_idempotente(tmp_path):
    p = tmp_path / "radar.db"
    _banco_100(p)
    antes = _estado(db.connect(p))
    depois = _estado(db.connect(p))
    assert antes == depois


def test_migracao_nao_desfaz_escolha_do_usuario(tmp_path):
    p = tmp_path / "radar.db"
    _banco_100(p)
    conn = db.connect(p)
    conn.execute("UPDATE assets SET watch = 0 WHERE symbol = 'AAPL'")
    conn.commit()
    conn.close()
    conn = db.connect(p)
    assert {a["symbol"]: a["watch"] for a in db.list_assets(conn, None)} == {"PETR4": 1, "AAPL": 0}


def test_falha_no_meio_da_migracao_nao_deixa_rastro(tmp_path, monkeypatch):
    p = tmp_path / "radar.db"
    _banco_100(p)
    boa = db._MIGRATION_1
    monkeypatch.setattr(db, "_MIGRATION_1", boa[:2] + ("CREATE TABLE ruim (",) + boa[2:])
    with pytest.raises(sqlite3.Error):
        db.connect(p)
    raw = sqlite3.connect(p)
    assert raw.execute("PRAGMA user_version").fetchone()[0] == 0
    assert "watch" not in {r[1] for r in raw.execute("PRAGMA table_info(assets)")}
    assert not {"catalog", "screener", "news", "meta"} & {
        r[0] for r in raw.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    raw.close()
    monkeypatch.setattr(db, "_MIGRATION_1", boa)
    conn = db.connect(p)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 2
    assert [a["watch"] for a in db.list_assets(conn, None)] == [1, 1]


def test_banco_novo_tem_mesmo_schema_final(tmp_path):
    novo = db.connect(tmp_path / "novo.db")
    p = tmp_path / "velho.db"
    _banco_100(p)
    velho = db.connect(p)
    assert novo.execute("PRAGMA user_version").fetchone()[0] == 2
    assert _tabelas(novo) == _tabelas(velho)
    cols = lambda c: [r["name"] for r in c.execute("PRAGMA table_info(assets)")]
    assert sorted(cols(novo)) == sorted(cols(velho))
    # o banco migrado continua aceitando escrita normal
    a = db.add_asset(velho, "VALE3", "B3")
    db.upsert_candles(velho, a, [Candle("2024-01-02", 1, 1, 1, 1, 1)])
    assert db.get_asset(velho, a)["watch"] == 1


# ---------- 1.1.1: schema v2 (catalog.alias) ----------

# Schema exato da 1.1.0 (user_version = 1).
_SCHEMA_110 = """
CREATE TABLE assets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    market TEXT NOT NULL,
    name TEXT,
    currency TEXT NOT NULL,
    position INTEGER NOT NULL,
    last_refresh TEXT,
    last_error TEXT,
    watch INTEGER NOT NULL DEFAULT 1,
    last_viewed TEXT,
    UNIQUE (symbol, market)
);
CREATE TABLE candles (
    asset_id INTEGER NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
    date TEXT NOT NULL,
    open REAL, high REAL, low REAL, close REAL, volume REAL,
    PRIMARY KEY (asset_id, date)
);
CREATE TABLE rf_rates (date TEXT PRIMARY KEY, rate REAL NOT NULL);
CREATE TABLE catalog (
    symbol TEXT NOT NULL, market TEXT NOT NULL, name TEXT NOT NULL, kind TEXT NOT NULL,
    indices TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (symbol, market));
CREATE TABLE screener (
    asset_id INTEGER PRIMARY KEY REFERENCES assets(id) ON DELETE CASCADE,
    as_of TEXT NOT NULL, payload TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE news (
    asset_id INTEGER NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
    url TEXT NOT NULL, title TEXT NOT NULL, source TEXT, published_at TEXT, fetched_at TEXT NOT NULL,
    PRIMARY KEY (asset_id, url));
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE INDEX idx_catalog_market ON catalog(market);
CREATE INDEX idx_assets_watch ON assets(watch);
PRAGMA user_version = 1;
"""


def _banco_110(path):
    raw = sqlite3.connect(path)
    raw.executescript(_SCHEMA_110)
    raw.execute("INSERT INTO assets (symbol, market, currency, position, watch) VALUES ('BBAS3','B3','BRL',1,1)")
    raw.execute("INSERT INTO assets (symbol, market, currency, position, watch) VALUES ('AAPL','US','USD',2,0)")
    raw.execute("INSERT INTO candles VALUES (1,'2024-01-02',1,2,0.5,1.5,100)")
    raw.execute("INSERT INTO rf_rates VALUES ('2024-01-02', 0.11)")
    raw.execute("INSERT INTO catalog VALUES ('BBAS3','B3','BCO BRASIL S.A.','Ação','IBOV,IBRA')")
    raw.execute("INSERT INTO catalog VALUES ('AAPL','US','Apple Inc.','Ação','SP500')")
    raw.execute("INSERT INTO screener VALUES (1,'2024-01-02','{\"symbol\": \"BBAS3\"}','2024-01-03T00:00:00+00:00')")
    raw.execute("INSERT INTO news VALUES (1,'https://a.example/1','Título','Fonte',NULL,'2024-01-03T00:00:00+00:00')")
    raw.execute("INSERT INTO meta VALUES ('catalog_refreshed_at','2024-01-03T00:00:00+00:00')")
    raw.commit()
    raw.close()


def _estado_110(conn):
    return (_estado(conn), db.all_catalog(conn), db.load_screener(conn), db.load_news(conn, 1),
            db.get_meta(conn, "catalog_refreshed_at"))


def test_migra_banco_110_para_v2_sem_perder_nada(tmp_path):
    p = tmp_path / "radar.db"
    _banco_110(p)
    conn = db.connect(p)
    (version, assets, candles, rf), cat, scr, (news, _), stamp = _estado_110(conn)
    assert version == 2
    assert [(a["symbol"], a["watch"]) for a in assets] == [("BBAS3", 1), ("AAPL", 0)]
    assert candles == [(1, "2024-01-02", 1, 2, 0.5, 1.5, 100)] and rf == [("2024-01-02", 0.11)]
    assert cat == [
        {"symbol": "BBAS3", "market": "B3", "name": "BCO BRASIL S.A.", "kind": "Ação", "indices": ["IBOV", "IBRA"],
         "alias": None},
        {"symbol": "AAPL", "market": "US", "name": "Apple Inc.", "kind": "Ação", "indices": ["SP500"],
         "alias": None}]
    assert scr[0]["payload"] == {"symbol": "BBAS3"} and news[0]["title"] == "Título"
    assert stamp == "2024-01-03T00:00:00+00:00"
    assert db.set_alias(conn, "BBAS3", "B3", "Banco do Brasil S.A.")  # o banco migrado aceita a coluna nova


def test_migracao_v2_idempotente(tmp_path):
    p = tmp_path / "radar.db"
    _banco_110(p)
    conn = db.connect(p)
    db.set_alias(conn, "BBAS3", "B3", "Banco do Brasil S.A.")
    antes = _estado_110(conn)
    conn.close()
    conn = db.connect(p)
    assert _estado_110(conn) == antes
    db._migrate(conn)  # rodar de novo não muda nada
    assert _estado_110(conn) == antes


def test_banco_100_chega_na_v2(tmp_path):
    p = tmp_path / "radar.db"
    _banco_100(p)
    conn = db.connect(p)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 2
    assert "alias" in {r["name"] for r in conn.execute("PRAGMA table_info(catalog)")}
    assert [a["symbol"] for a in db.list_assets(conn)] == ["PETR4", "AAPL"]


def test_falha_no_meio_da_migracao_v2_nao_avanca_a_versao(tmp_path, monkeypatch):
    p = tmp_path / "radar.db"
    _banco_110(p)
    boa = db._MIGRATION_2
    monkeypatch.setattr(db, "_MIGRATION_2", boa + ("CREATE TABLE ruim (",))
    with pytest.raises(sqlite3.Error):
        db.connect(p)
    raw = sqlite3.connect(p)
    assert raw.execute("PRAGMA user_version").fetchone()[0] == 1
    assert "alias" not in {r[1] for r in raw.execute("PRAGMA table_info(catalog)")}  # o ALTER foi desfeito
    assert raw.execute("SELECT COUNT(*) FROM catalog").fetchone()[0] == 2
    raw.close()
    monkeypatch.setattr(db, "_MIGRATION_2", boa)
    conn = db.connect(p)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 2
    assert [c["alias"] for c in db.all_catalog(conn)] == [None, None]


def test_falha_na_v2_partindo_da_100_desfaz_tambem_a_v1(tmp_path, monkeypatch):
    p = tmp_path / "radar.db"
    _banco_100(p)
    monkeypatch.setattr(db, "_MIGRATION_2", ("CREATE TABLE ruim (",))
    with pytest.raises(sqlite3.Error):
        db.connect(p)
    raw = sqlite3.connect(p)
    assert raw.execute("PRAGMA user_version").fetchone()[0] == 0
    assert "catalog" not in {r[0] for r in raw.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    raw.close()
