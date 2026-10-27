"""SQLite: alertas, inscrições de push e retenção.

Data guardada em segundos UTC (epoch, inteiro); a conversão para o fuso local
(TZ do contêiner) só acontece na saída.
"""
import sqlite3
import time
from datetime import datetime
from pathlib import Path

GRAVIDADES = ("grave", "normal", "info")

_ESQUEMA = """
CREATE TABLE IF NOT EXISTS alertas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    origem TEXT NOT NULL,
    gravidade TEXT NOT NULL CHECK (gravidade IN ('grave', 'normal', 'info')),
    titulo TEXT NOT NULL,
    detalhes TEXT NOT NULL DEFAULT '',
    criado_em INTEGER NOT NULL,
    lido INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS alertas_criado_em ON alertas (criado_em);
CREATE TABLE IF NOT EXISTS inscricoes (
    endpoint TEXT PRIMARY KEY,
    p256dh TEXT NOT NULL,
    auth TEXT NOT NULL,
    criado_em INTEGER NOT NULL
);
"""


def abrir(caminho) -> sqlite3.Connection:
    """Abre (e cria) o banco em modo WAL. Uma conexão por uso; autocommit."""
    caminho = Path(caminho)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(caminho, timeout=10, isolation_level=None)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA busy_timeout=10000")
    # trocar para WAL exige trava exclusiva: só quando ainda não está (fica gravado no arquivo)
    if con.execute("PRAGMA journal_mode").fetchone()[0] != "wal":
        con.execute("PRAGMA journal_mode=WAL")
    con.executescript(_ESQUEMA)
    return con


def inserir(con, origem, gravidade, titulo, detalhes, *, criado_em: float | None = None) -> int:
    agora = int(time.time() if criado_em is None else criado_em)
    cur = con.execute(
        "INSERT INTO alertas (origem, gravidade, titulo, detalhes, criado_em) VALUES (?, ?, ?, ?, ?)",
        (origem, gravidade, titulo, detalhes or "", agora),
    )
    return cur.lastrowid


def inserir_se_ausente(con, origem, gravidade, titulo, detalhes, *, janela_s: int) -> int | None:
    """Insere só se não houver alerta igual (origem+título) na janela. Atômico (um só comando)."""
    agora = int(time.time())
    cur = con.execute(
        "INSERT INTO alertas (origem, gravidade, titulo, detalhes, criado_em) "
        "SELECT ?, ?, ?, ?, ? WHERE NOT EXISTS ("
        "  SELECT 1 FROM alertas WHERE origem = ? AND titulo = ? AND criado_em > ?)",
        (origem, gravidade, titulo, detalhes or "", agora, origem, titulo, agora - janela_s),
    )
    return cur.lastrowid if cur.rowcount == 1 else None


def _iso_local(epoch: int) -> str:
    return datetime.fromtimestamp(epoch).astimezone().isoformat(timespec="seconds")


def listar(con) -> list[dict]:
    """Graves não lidos primeiro; depois do mais novo para o mais antigo."""
    linhas = con.execute(
        "SELECT id, origem, gravidade, titulo, detalhes, criado_em, lido FROM alertas "
        "ORDER BY (gravidade = 'grave' AND lido = 0) DESC, criado_em DESC, id DESC"
    ).fetchall()
    return [
        {"id": r["id"], "origem": r["origem"], "gravidade": r["gravidade"], "titulo": r["titulo"],
         "detalhes": r["detalhes"], "criado_em": _iso_local(r["criado_em"]), "lido": bool(r["lido"])}
        for r in linhas
    ]


def marcar_lido(con, id_: int) -> bool:
    return con.execute("UPDATE alertas SET lido = 1 WHERE id = ?", (id_,)).rowcount == 1


def limpar_antigos(con, dias: int = 365) -> int:
    limite = int(time.time()) - dias * 86400
    return con.execute("DELETE FROM alertas WHERE criado_em < ?", (limite,)).rowcount


def salvar_inscricao(con, sub: dict) -> None:
    """Upsert pelo endpoint. `sub` já validado por quem chama."""
    con.execute(
        "INSERT INTO inscricoes (endpoint, p256dh, auth, criado_em) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(endpoint) DO UPDATE SET p256dh = excluded.p256dh, auth = excluded.auth",
        (sub["endpoint"], sub["keys"]["p256dh"], sub["keys"]["auth"], int(time.time())),
    )


def inscricoes(con) -> list[dict]:
    return [
        {"endpoint": r["endpoint"], "keys": {"p256dh": r["p256dh"], "auth": r["auth"]}}
        for r in con.execute("SELECT endpoint, p256dh, auth FROM inscricoes ORDER BY criado_em")
    ]


def remover_inscricao(con, endpoint: str) -> None:
    con.execute("DELETE FROM inscricoes WHERE endpoint = ?", (endpoint,))
