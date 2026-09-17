import sqlite3
from contextlib import contextmanager
from pathlib import Path

DB_PATH = Path("/app/data/bot.db")


def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with get_conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS bots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                timeframe TEXT NOT NULL DEFAULT '5m',
                fast_period INTEGER NOT NULL DEFAULT 9,
                slow_period INTEGER NOT NULL DEFAULT 21,
                starting_balance REAL NOT NULL DEFAULT 1000,
                cash REAL NOT NULL,
                position_qty REAL NOT NULL DEFAULT 0,
                position_entry_price REAL,
                status TEXT NOT NULL DEFAULT 'running',
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                bot_id INTEGER NOT NULL REFERENCES bots(id),
                side TEXT NOT NULL,
                price REAL NOT NULL,
                qty REAL NOT NULL,
                pnl REAL,
                reason TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS equity_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                bot_id INTEGER NOT NULL REFERENCES bots(id),
                equity REAL NOT NULL,
                price REAL NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            """
        )


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()
