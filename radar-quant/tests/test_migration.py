import sqlite3

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
    assert user_version == db.SCHEMA_VERSION == 1
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


def test_banco_novo_tem_mesmo_schema_final(tmp_path):
    novo = db.connect(tmp_path / "novo.db")
    p = tmp_path / "velho.db"
    _banco_100(p)
    velho = db.connect(p)
    assert novo.execute("PRAGMA user_version").fetchone()[0] == 1
    assert _tabelas(novo) == _tabelas(velho)
    cols = lambda c: [r["name"] for r in c.execute("PRAGMA table_info(assets)")]
    assert sorted(cols(novo)) == sorted(cols(velho))
    # o banco migrado continua aceitando escrita normal
    a = db.add_asset(velho, "VALE3", "B3")
    db.upsert_candles(velho, a, [Candle("2024-01-02", 1, 1, 1, 1, 1)])
    assert db.get_asset(velho, a)["watch"] == 1
