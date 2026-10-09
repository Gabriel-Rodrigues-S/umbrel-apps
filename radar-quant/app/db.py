"""Camada SQLite: ativos, candles diários e taxa livre de risco."""
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from app.config import CURRENCY
from app.providers.base import Candle

_lock = threading.RLock()  # a conexão é compartilhada entre threads

_SCHEMA = """
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
_UPSERT_CANDLE = ("INSERT OR REPLACE INTO candles (asset_id, date, open, high, low, close, volume) "
                  "VALUES (?, ?, ?, ?, ?, ?, ?)")
MIN_TRIM_CANDLES = 250  # lote menor que isso não é uma janela confiável para apagar histórico


class DuplicateAsset(Exception):
    pass


@contextmanager
def _write(conn):
    """Escrita sob o lock numa única transação: commit no sucesso, rollback em qualquer erro."""
    with _lock:
        try:
            yield
        except BaseException:
            conn.rollback()
            raise
        conn.commit()


def connect(path: Path) -> sqlite3.Connection:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    with _lock:
        conn.executescript(_SCHEMA)
        conn.commit()
    return conn


def list_assets(conn) -> list[dict]:
    with _lock:
        rows = conn.execute("SELECT * FROM assets ORDER BY position, id").fetchall()
    return [dict(r) for r in rows]


def get_asset(conn, asset_id: int) -> dict | None:
    with _lock:
        r = conn.execute("SELECT * FROM assets WHERE id = ?", (asset_id,)).fetchone()
    return dict(r) if r else None


def add_asset(conn, symbol: str, market: str) -> int:
    with _lock:
        pos = conn.execute("SELECT COALESCE(MAX(position), 0) + 1 FROM assets").fetchone()[0]
        try:
            cur = conn.execute(
                "INSERT INTO assets (symbol, market, currency, position) VALUES (?, ?, ?, ?)",
                (symbol, market, CURRENCY[market], pos))
        except sqlite3.IntegrityError as e:
            conn.rollback()
            raise DuplicateAsset(f"{symbol} ({market}) já existe") from e
        conn.commit()
        return cur.lastrowid


def delete_asset(conn, asset_id: int) -> bool:
    with _write(conn):
        conn.execute("DELETE FROM candles WHERE asset_id = ?", (asset_id,))
        cur = conn.execute("DELETE FROM assets WHERE id = ?", (asset_id,))
    return cur.rowcount > 0


def _candle_rows(asset_id: int, candles: Iterable[Candle]) -> list[tuple]:
    return [(asset_id, c.date, c.open, c.high, c.low, c.close, c.volume) for c in candles]


def upsert_candles(conn, asset_id: int, candles: Iterable[Candle]) -> int:
    rows = _candle_rows(asset_id, candles)
    with _write(conn):
        conn.executemany(_UPSERT_CANDLE, rows)
    return len(rows)


def replace_candles(conn, asset_id: int, candles: Iterable[Candle]) -> int:
    """Grava a janela recebida e apaga o que ficou antes dela.

    A fonte reajusta o histórico inteiro a cada dividendo/split; linhas que já saíram
    da janela ficariam com o fator antigo. Lote curto (resposta parcial da fonte) ou
    vazio não apaga nada: só faz o upsert.
    """
    rows = _candle_rows(asset_id, candles)
    if not rows:
        return 0
    with _write(conn):
        if len(rows) >= MIN_TRIM_CANDLES:
            conn.execute("DELETE FROM candles WHERE asset_id = ? AND date < ?",
                         (asset_id, min(r[1] for r in rows)))
        conn.executemany(_UPSERT_CANDLE, rows)
    return len(rows)


def load_candles(conn, asset_id: int) -> list[sqlite3.Row]:
    with _lock:
        return conn.execute(
            "SELECT * FROM candles WHERE asset_id = ? ORDER BY date", (asset_id,)).fetchall()


def set_refresh_status(conn, asset_id: int, error: str | None) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with _lock:
        conn.execute("UPDATE assets SET last_refresh = ?, last_error = ? WHERE id = ?",
                     (now, error, asset_id))
        conn.commit()


def upsert_rf(conn, rows: Iterable[tuple[str, float]]) -> None:
    with _write(conn):
        conn.executemany("INSERT OR REPLACE INTO rf_rates (date, rate) VALUES (?, ?)", list(rows))


def load_rf(conn) -> list[tuple[str, float]]:
    with _lock:
        rows = conn.execute("SELECT date, rate FROM rf_rates ORDER BY date").fetchall()
    return [(r["date"], r["rate"]) for r in rows]
