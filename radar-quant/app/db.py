"""Camada SQLite: ativos, candles diários, taxa livre de risco, catálogo, screener e notícias."""
import json
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
SCHEMA_VERSION = 2  # PRAGMA user_version: 1.0.0 = 0, 1.1.0 = 1, 1.1.1 = 2
_MIGRATION_1 = (
    """CREATE TABLE IF NOT EXISTS catalog (
        symbol TEXT NOT NULL, market TEXT NOT NULL, name TEXT NOT NULL, kind TEXT NOT NULL,
        indices TEXT NOT NULL DEFAULT '',
        PRIMARY KEY (symbol, market))""",
    """CREATE TABLE IF NOT EXISTS screener (
        asset_id INTEGER PRIMARY KEY REFERENCES assets(id) ON DELETE CASCADE,
        as_of TEXT NOT NULL, payload TEXT NOT NULL, updated_at TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS news (
        asset_id INTEGER NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
        url TEXT NOT NULL, title TEXT NOT NULL, source TEXT, published_at TEXT, fetched_at TEXT NOT NULL,
        PRIMARY KEY (asset_id, url))""",
    "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
    "CREATE INDEX IF NOT EXISTS idx_catalog_market ON catalog(market)",
    "CREATE INDEX IF NOT EXISTS idx_assets_watch ON assets(watch)",
)
_MIGRATION_2 = ("ALTER TABLE catalog ADD COLUMN alias TEXT",)  # nome completo aprendido (1.1.1)
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
        _migrate(conn)
    return conn


def _columns(conn, table: str) -> set[str]:
    return {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}


def _migrate(conn) -> None:
    """Leva um banco 1.0.0 ou 1.1.0 (ou recém-criado) ao schema atual, numa transação; idempotente."""
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version >= SCHEMA_VERSION:
        return
    try:
        conn.execute("BEGIN")
        if version < 1:
            cols = _columns(conn, "assets")
            if "watch" not in cols:
                conn.execute("ALTER TABLE assets ADD COLUMN watch INTEGER NOT NULL DEFAULT 1")
            if "last_viewed" not in cols:
                conn.execute("ALTER TABLE assets ADD COLUMN last_viewed TEXT")
            for stmt in _MIGRATION_1:
                conn.execute(stmt)
        if "alias" not in _columns(conn, "catalog"):
            for stmt in _MIGRATION_2:
                conn.execute(stmt)
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")  # transacional no SQLite
        conn.commit()
    except BaseException:
        conn.rollback()
        raise


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def list_assets(conn, watch: bool | None = True) -> list[dict]:
    """Por padrão só a watchlist; `watch=None` traz todos (inclusive os de cache)."""
    sql, args = "SELECT * FROM assets", ()
    if watch is not None:
        sql, args = sql + " WHERE watch = ?", (int(watch),)
    with _lock:
        rows = conn.execute(sql + " ORDER BY position, id", args).fetchall()
    return [dict(r) for r in rows]


def get_asset(conn, asset_id: int) -> dict | None:
    with _lock:
        r = conn.execute("SELECT * FROM assets WHERE id = ?", (asset_id,)).fetchone()
    return dict(r) if r else None


def find_asset(conn, symbol: str, market: str) -> dict | None:
    with _lock:
        r = conn.execute("SELECT * FROM assets WHERE symbol = ? AND market = ?", (symbol, market)).fetchone()
    return dict(r) if r else None


def add_asset(conn, symbol: str, market: str, watch: bool = True) -> int:
    with _lock:
        pos = conn.execute("SELECT COALESCE(MAX(position), 0) + 1 FROM assets").fetchone()[0]
        try:
            cur = conn.execute(
                "INSERT INTO assets (symbol, market, currency, position, watch) VALUES (?, ?, ?, ?, ?)",
                (symbol, market, CURRENCY[market], pos, int(watch)))
        except sqlite3.IntegrityError as e:
            conn.rollback()
            raise DuplicateAsset(f"{symbol} ({market}) já existe") from e
        conn.commit()
        return cur.lastrowid


def set_watch(conn, asset_id: int, watch: bool) -> None:
    with _write(conn):
        conn.execute("UPDATE assets SET watch = ? WHERE id = ?", (int(watch), asset_id))


def touch_viewed(conn, asset_id: int) -> None:
    with _write(conn):
        conn.execute("UPDATE assets SET last_viewed = ? WHERE id = ?", (_now(), asset_id))


def _delete_ids(conn, ids: list[int]) -> int:
    """Apaga ativos e tudo que depende deles. Chamar dentro de `_write`."""
    for i in ids:
        for table in ("candles", "screener", "news"):
            conn.execute(f"DELETE FROM {table} WHERE asset_id = ?", (i,))
        conn.execute("DELETE FROM meta WHERE key = ?", (_news_key(i),))
    return sum(conn.execute("DELETE FROM assets WHERE id = ?", (i,)).rowcount for i in ids)


def delete_asset(conn, asset_id: int) -> bool:
    with _write(conn):
        return _delete_ids(conn, [asset_id]) > 0


def purge_viewed(conn, older_than: str, keep_ids: set[int]) -> int:
    """Apaga ativos de cache (watch=0) fora de `keep_ids` não vistos desde `older_than` (ISO)."""
    with _write(conn):
        rows = conn.execute("SELECT id FROM assets WHERE watch = 0 AND (last_viewed IS NULL OR last_viewed < ?)",
                            (older_than,)).fetchall()
        return _delete_ids(conn, [r["id"] for r in rows if r["id"] not in keep_ids])


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
    now = _now()
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


# ---------- catálogo ----------

def _split(indices: str) -> list[str]:
    return [i for i in indices.split(",") if i]


def _catalog_dict(r) -> dict:
    """Linha do catálogo para os chamadores: `name` é o nome exibido (alias, se houver)."""
    d = dict(r)
    d["name"] = d.pop("alias", None) or d["name"]
    d["indices"] = _split(d["indices"])
    return d


def replace_catalog_market(conn, market: str, rows: Iterable[tuple[str, str, str]]) -> int:
    """Troca o catálogo do mercado por (symbol, name, kind); quem continua mantém `indices` e `alias`.

    `rows` vazio não apaga nada e devolve 0: fonte que falhou não pode zerar o catálogo.
    """
    new = {sym: (name, kind) for sym, name, kind in rows}
    if not new:
        return 0
    with _write(conn):
        old = {r["symbol"]: (r["indices"], r["alias"]) for r in
               conn.execute("SELECT symbol, indices, alias FROM catalog WHERE market = ?", (market,))}
        conn.execute("DELETE FROM catalog WHERE market = ?", (market,))
        conn.executemany(
            "INSERT INTO catalog (symbol, market, name, kind, indices, alias) VALUES (?, ?, ?, ?, ?, ?)",
            [(sym, market, name, kind, *old.get(sym, ("", None))) for sym, (name, kind) in new.items()])
    return len(new)


def upsert_catalog_entry(conn, symbol: str, market: str, name: str, kind: str) -> None:
    """Insere o papel se não existir; quem já existe fica como está (nome, índices e alias)."""
    with _write(conn):
        conn.execute("INSERT OR IGNORE INTO catalog (symbol, market, name, kind, indices) VALUES (?, ?, ?, ?, '')",
                     (symbol, market, name, kind))


def set_alias(conn, symbol: str, market: str, alias: str) -> bool:
    """Grava o nome completo aprendido; False se o papel não está no catálogo."""
    with _write(conn):
        return conn.execute("UPDATE catalog SET alias = ? WHERE symbol = ? AND market = ?",
                            (alias, symbol, market)).rowcount > 0


def missing_alias(conn, market: str, symbols: Iterable[str] | None = None) -> list[str]:
    """Papéis do mercado sem alias, em ordem alfabética; com `symbols`, só eles (na ordem recebida)."""
    with _lock:
        missing = [r["symbol"] for r in conn.execute(
            "SELECT symbol FROM catalog WHERE market = ? AND (alias IS NULL OR alias = '') ORDER BY symbol",
            (market,))]
    if symbols is None:
        return missing
    have = set(missing)
    return [s for s in dict.fromkeys(symbols) if s in have]


def all_catalog(conn) -> list[dict]:
    """Catálogo inteiro com o nome cru da fonte em `name` e o aprendido em `alias` (para o índice de busca)."""
    with _lock:
        rows = conn.execute("SELECT * FROM catalog ORDER BY market, symbol").fetchall()
    return [{**dict(r), "indices": _split(r["indices"])} for r in rows]


def set_index_members(conn, index: str, market: str, symbols: Iterable[str]) -> int:
    """Define os membros do índice no mercado; mexe só nesse índice e insere símbolos ausentes."""
    symbols = list(dict.fromkeys(symbols))
    with _write(conn):
        for r in conn.execute("SELECT symbol, indices FROM catalog WHERE market = ?", (market,)).fetchall():
            cur = _split(r["indices"])
            if index in cur:
                conn.execute("UPDATE catalog SET indices = ? WHERE symbol = ? AND market = ?",
                             (",".join(i for i in cur if i != index), r["symbol"], market))
        for sym in symbols:
            conn.execute("INSERT OR IGNORE INTO catalog (symbol, market, name, kind, indices) "
                         "VALUES (?, ?, ?, 'Ação', '')", (sym, market, sym))
            cur = _split(conn.execute("SELECT indices FROM catalog WHERE symbol = ? AND market = ?",
                                      (sym, market)).fetchone()["indices"])
            conn.execute("UPDATE catalog SET indices = ? WHERE symbol = ? AND market = ?",
                         (",".join(cur + [index]), sym, market))
    return len(symbols)


def search_catalog(conn, q: str, limit: int = 12) -> list[dict]:
    """Prefixo de símbolo primeiro, depois nome (ou alias) contendo `q`; curingas do LIKE escapados."""
    q = q.strip()
    if not q:
        return []
    esc = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    with _lock:
        rows = conn.execute(
            "SELECT * FROM catalog WHERE symbol LIKE :pre ESCAPE '\\' OR name LIKE :sub ESCAPE '\\' "
            "OR alias LIKE :sub ESCAPE '\\' "
            "ORDER BY symbol LIKE :pre ESCAPE '\\' DESC, symbol LIMIT :lim",
            {"pre": esc + "%", "sub": "%" + esc + "%", "lim": limit}).fetchall()
    return [_catalog_dict(r) for r in rows]


def catalog_entry(conn, symbol: str, market: str) -> dict | None:
    with _lock:
        r = conn.execute("SELECT * FROM catalog WHERE symbol = ? AND market = ?", (symbol, market)).fetchone()
    return _catalog_dict(r) if r else None


def index_members(conn, index: str | None = None) -> list[dict]:
    with _lock:
        rows = conn.execute("SELECT * FROM catalog WHERE indices != '' ORDER BY market, symbol").fetchall()
    out = [_catalog_dict(r) for r in rows]
    return out if index is None else [d for d in out if index in d["indices"]]


def catalog_count(conn, market: str | None = None) -> int:
    sql, args = "SELECT COUNT(*) FROM catalog", ()
    if market is not None:
        sql, args = sql + " WHERE market = ?", (market,)
    with _lock:
        return conn.execute(sql, args).fetchone()[0]


# ---------- screener ----------

def upsert_screener(conn, asset_id: int, as_of: str, payload: dict) -> None:
    with _write(conn):
        conn.execute("INSERT OR REPLACE INTO screener (asset_id, as_of, payload, updated_at) VALUES (?, ?, ?, ?)",
                     (asset_id, as_of, json.dumps(payload), _now()))


def load_screener(conn, asset_ids: Iterable[int] | None = None) -> list[dict]:
    """Linhas do screener ordenadas por ativo; com `asset_ids`, lê só essas (em lotes de 500)."""
    if asset_ids is None:
        sql, batches = "SELECT * FROM screener ORDER BY asset_id", [()]
    else:
        ids = sorted(set(asset_ids))
        batches = [ids[i:i + 500] for i in range(0, len(ids), 500)]
        sql = None
    rows = []
    with _lock:
        for batch in batches:
            q = sql or f"SELECT * FROM screener WHERE asset_id IN ({','.join('?' * len(batch))})"
            rows += conn.execute(q, tuple(batch)).fetchall()
    rows.sort(key=lambda r: r["asset_id"])
    return [{"asset_id": r["asset_id"], "as_of": r["as_of"], "updated_at": r["updated_at"],
             "payload": json.loads(r["payload"])} for r in rows]


# ---------- notícias ----------

def _news_key(asset_id: int) -> str:
    return f"news_fetched:{asset_id}"


def replace_news(conn, asset_id: int, items: list[dict]) -> None:
    """Troca as notícias do ativo. O `fetched_at` fica em `meta` (chave news_fetched:<id>) para
    existir também quando a lista é vazia (consulta feita, nada encontrado)."""
    now = _now()
    rows = [(asset_id, i["url"], i["title"], i.get("source"), i.get("published_at"), now) for i in items]
    with _write(conn):
        conn.execute("DELETE FROM news WHERE asset_id = ?", (asset_id,))
        conn.executemany("INSERT OR REPLACE INTO news (asset_id, url, title, source, published_at, fetched_at) "
                         "VALUES (?, ?, ?, ?, ?, ?)", rows)
        conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (_news_key(asset_id), now))


def touch_news(conn, asset_id: int) -> None:
    """Renova só o carimbo de busca das notícias (as linhas ficam como estão)."""
    with _write(conn):
        conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (_news_key(asset_id), _now()))


def load_news(conn, asset_id: int) -> tuple[list[dict], str | None]:
    with _lock:
        rows = conn.execute("SELECT title, url, source, published_at FROM news WHERE asset_id = ? "
                            "ORDER BY published_at DESC", (asset_id,)).fetchall()
    return [dict(r) for r in rows], get_meta(conn, _news_key(asset_id))


# ---------- meta ----------

def get_meta(conn, key: str) -> str | None:
    with _lock:
        r = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return r["value"] if r else None


def set_meta(conn, key: str, value: str) -> None:
    with _write(conn):
        conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (key, value))
