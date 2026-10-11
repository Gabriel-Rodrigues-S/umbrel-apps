"""Busca de papéis por código ou nome: índice em memória do catálogo e reforço on-line (busca do Yahoo).

A fonte do catálogo da B3 abrevia os nomes ("BCO BRASIL S.A."): o índice expande as abreviações e a busca
on-line ensina o nome completo (`alias`). O que vem da rede é de terceiros: símbolos filtrados, nomes saneados."""
import asyncio
import json
import logging
import re
import threading
import time
import unicodedata

import httpx

from . import db

log = logging.getLogger("radar.search")

YAHOO_URL = "https://query1.finance.yahoo.com/v1/finance/search"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; RadarQuantBot/1.0)"}
TIMEOUT = 4  # segundos
MAX_BODY = 1_000_000
MAX_NAME = 80
MIN_REMOTE_CHARS = 3  # consulta menor que isso não vai à rede
MIN_LOCAL = 5  # com menos resultados locais que isso, consulta a rede
CACHE_SECONDS = 24 * 3600
CACHE_MAX = 256
SCORE_EXACT, SCORE_PREFIX, SCORE_REMOTE, SCORE_NAME = 1000, 600, 450, 300

ABBR = {"bco": "banco", "cia": "companhia", "part": "participacoes", "empr": "empreendimentos",
        "energ": "energia", "sid": "siderurgica", "ind": "industria", "com": "comercio",
        "adm": "administracao", "fin": "financeira", "inv": "investimentos", "transm": "transmissao",
        "distr": "distribuidora", "saneam": "saneamento", "educ": "educacao", "seg": "seguros",
        "tecnol": "tecnologia", "telecom": "telecomunicacoes", "petr": "petroleo", "bras": "brasil"}
STOPWORDS = frozenset("de do da dos das e s a sa the of inc corp co ltd plc nv ag on pn unit".split())
US_EXCHANGES = frozenset({"NMS", "NGM", "NCM", "NYQ", "ASE", "PCX", "BTS"})
_B3_RE = re.compile(r"[A-Z0-9]{4,6}[0-9]{1,2}")
_FRACTION_RE = re.compile(r"[A-Z0-9]{4}[0-9]{1,2}F")  # PETR4F: mercado fracionário
_US_RE = re.compile(r"[A-Z]{1,5}(-[A-Z])?")
_NOT_WORD_RE = re.compile(r"[^a-z0-9]+")

_lock = threading.Lock()
_state: tuple | None = None  # (conexão, entradas do índice)
_remote_cache: dict[str, tuple[float, list[dict]]] = {}  # consulta normalizada -> (instante, acertos)


class SearchError(Exception):
    pass


def _now() -> float:  # relógio trocável nos testes
    return time.monotonic()


def _words(text: str) -> list[str]:
    """Palavras em minúsculas, sem acento; pontuação vira espaço."""
    flat = "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))
    return _NOT_WORD_RE.sub(" ", flat.lower()).split()


def _variants(word: str) -> tuple[str, ...]:
    return (word, ABBR[word]) if word in ABBR else (word,)


def normalize(text: str) -> list[str]:
    """Tokens de busca: cada palavra e, se for abreviação da B3, também a forma por extenso."""
    return [t for w in _words(text) for t in _variants(w)]


def clean_name(value) -> str:
    """Nome vindo de terceiros: sem caracteres de controle/formatação, espaços colapsados, até MAX_NAME."""
    if not isinstance(value, str):
        return ""
    return " ".join("".join(" " if unicodedata.category(c) in ("Cc", "Cf") else c for c in value).split())[:MAX_NAME]


# ---------- índice em memória ----------

def invalidate() -> None:
    """Derruba o índice; a próxima busca o reconstrói. Chamar quando o catálogo ou um alias mudar."""
    global _state
    with _lock:
        _state = None


def _entry(row: dict) -> tuple:
    names = [_words(n) for n in (row["name"], row["alias"] or "")]
    tokens = frozenset(t for words in names for w in words for t in _variants(w))
    firsts = tuple({t for words in names for w in words[:1] for t in _variants(w)})
    blob = " " + " ".join(_words(row["symbol"]) + sorted(tokens))  # " tok": prefixo de token = substring
    item = {"symbol": row["symbol"], "market": row["market"], "name": row["alias"] or row["name"],
            "kind": row["kind"], "indices": row["indices"]}
    return row["symbol"], blob, firsts, tokens, 60 * bool(row["indices"]) + 20 * (row["kind"] == "Ação"), item


def _index(conn) -> list[tuple]:
    global _state
    with _lock:
        if _state is None or _state[0] is not conn:
            _state = (conn, [_entry(r) for r in db.all_catalog(conn)])
        return _state[1]


def _order(scored: tuple[int, dict]):
    score, item = scored
    return -score, len(item["symbol"]), item["symbol"], item["market"]


def _rank(conn, q: str) -> list[tuple[int, dict]]:
    """Todos os papéis que casam com a consulta, como (pontuação, item), do melhor para o pior."""
    words = _words(q)
    groups = [_variants(w) for w in ([w for w in words if w not in STOPWORDS] or words)]
    needles = [tuple(" " + v for v in g) for g in groups]
    code = q.strip().upper()
    code = code[:-3] if code.endswith(".SA") else code
    if not code:
        return []
    out = []
    for symbol, blob, firsts, tokens, bonus, item in _index(conn):
        if symbol == code:
            score = SCORE_EXACT
        elif symbol.startswith(code):
            score = SCORE_PREFIX
        elif needles and all(any(n in blob for n in g) for g in needles):
            score = (SCORE_NAME + 80 * any(f.startswith(v) for v in groups[0] for f in firsts)
                     + 40 * any(v in tokens for g in groups for v in g))
        else:
            continue
        out.append((score + bonus, item))
    out.sort(key=_order)
    return out


def _public(ranked: list[tuple[int, dict]], limit: int) -> list[dict]:
    return [{**item, "indices": list(item["indices"])} for _, item in ranked[:limit]]  # cópia: o índice fica intacto


def search_local(conn, q: str, limit: int = 12) -> list[dict]:
    return _public(_rank(conn, q), limit)


# ---------- reforço on-line ----------

def clear_remote_cache() -> None:
    _remote_cache.clear()


async def yahoo_quotes(q: str, transport: httpx.AsyncBaseTransport | None = None) -> list[dict]:
    """Itens de `quotes` da busca do Yahoo. Levanta em qualquer falha (rede, status, tamanho, JSON)."""
    async def fetch() -> bytes:
        async with httpx.AsyncClient(transport=transport, timeout=TIMEOUT, headers=HEADERS) as client:
            async with client.stream("GET", YAHOO_URL,
                                     params={"q": q, "quotesCount": 8, "newsCount": 0}) as resp:
                if resp.status_code != 200:
                    raise SearchError(f"HTTP {resp.status_code}")
                body = b""
                async for chunk in resp.aiter_bytes():
                    body += chunk
                    if len(body) > MAX_BODY:
                        raise SearchError("resposta grande demais")
        return body

    data = json.loads(await asyncio.wait_for(fetch(), TIMEOUT))  # teto para a chamada inteira
    quotes = data.get("quotes") if isinstance(data, dict) else None
    if not isinstance(quotes, list):
        raise SearchError("JSON inesperado")
    return [x for x in quotes if isinstance(x, dict)]


def _map(quote: dict) -> dict | None:
    """Item do Yahoo -> {symbol, market, name}; None para outras bolsas, fracionário e OTC."""
    symbol, exchange = quote.get("symbol"), quote.get("exchange")
    if not isinstance(symbol, str):
        return None
    if symbol.endswith(".SA") and exchange == "SAO":
        symbol, market = symbol[:-3], "B3"
        if _FRACTION_RE.fullmatch(symbol) or not _B3_RE.fullmatch(symbol):
            return None
    elif exchange in US_EXCHANGES and _US_RE.fullmatch(symbol):
        symbol, market = symbol.replace("-", "."), "US"
    else:
        return None
    return {"symbol": symbol, "market": market,
            "name": clean_name(quote.get("longname")) or clean_name(quote.get("shortname")) or None}


async def search_remote(q: str, transport: httpx.AsyncBaseTransport | None = None) -> list[dict]:
    """Acertos da busca do Yahoo já mapeados e filtrados; nunca levanta (falha = lista vazia, sem cache)."""
    key = " ".join(q.lower().split())
    if len(key) < MIN_REMOTE_CHARS:
        return []
    hit = _remote_cache.get(key)
    if hit and _now() - hit[0] < CACHE_SECONDS:
        return [dict(h) for h in hit[1]]
    try:
        found = {}
        for quote in await yahoo_quotes(key, transport):
            mapped = _map(quote)
            if mapped:
                found.setdefault((mapped["symbol"], mapped["market"]), mapped)
    except Exception as e:  # noqa: BLE001 - rede, status, tamanho, JSON, recursão: a busca local segue valendo
        log.warning("busca on-line de %r falhou: %s: %s", key, type(e).__name__, e)
        return []
    _remote_cache.pop(key, None)
    _remote_cache[key] = (_now(), list(found.values()))
    while len(_remote_cache) > CACHE_MAX:
        del _remote_cache[next(iter(_remote_cache))]  # a mais antiga
    return [dict(h) for h in found.values()]


def _learn(conn, ranked: list[tuple[int, dict]], hits: list[dict]) -> list[tuple[int, dict]]:
    """Grava o que a rede ensinou (alias de quem não tinha, papel fora do catálogo) e junta aos locais."""
    best = {(item["symbol"], item["market"]): (score, item) for score, item in ranked}
    missing = {(s, m) for m in {h["market"] for h in hits}
               for s in db.missing_alias(conn, m, [h["symbol"] for h in hits if h["market"] == m])}
    learned = False
    for h in hits:
        key = (h["symbol"], h["market"])
        if db.catalog_entry(conn, *key) is None:
            db.upsert_catalog_entry(conn, *key, h["name"] or h["symbol"], "Ação")
            learned = True
        elif h["name"] and key in missing:
            learned |= db.set_alias(conn, *key, h["name"])
        entry = db.catalog_entry(conn, *key)
        if entry:
            best[key] = (max(SCORE_REMOTE, best[key][0] if key in best else 0), entry)
    if learned:
        invalidate()
    return sorted(best.values(), key=_order)


async def search(conn, q: str, limit: int, settings, transport: httpx.AsyncBaseTransport | None = None) -> list[dict]:
    """Busca local; se ela for fraca (e fora do modo sintético), reforça com a busca on-line e aprende."""
    ranked = await asyncio.to_thread(_rank, conn, q)
    weak = len(ranked) < MIN_LOCAL or ranked[0][0] < SCORE_NAME
    if settings.provider != "synthetic" and len(q.strip()) >= MIN_REMOTE_CHARS and weak:
        hits = await search_remote(q, transport)
        if hits:
            ranked = await asyncio.to_thread(_learn, conn, ranked, hits)
    return _public(ranked, limit)
