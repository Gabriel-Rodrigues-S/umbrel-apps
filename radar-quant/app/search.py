"""Busca de papéis por código ou nome: índice em memória do catálogo e reforço on-line (busca do Yahoo).

A fonte do catálogo da B3 abrevia os nomes ("BCO BRASIL S.A."): o índice expande as abreviações e a busca
on-line ensina o nome completo (`alias`). O que vem da rede é de terceiros: símbolos filtrados, nomes saneados."""
import asyncio
import functools
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
TIMEOUT = 4  # segundos (aprendizado de nomes, em segundo plano)
SEARCH_TIMEOUT = 2  # teto da ida à rede na busca interativa: alguém está esperando a resposta
BREAKER_SECONDS = 60  # sem rede depois de falha de rede, timeout ou 5xx
NEGATIVE_SECONDS = 600  # resposta imprestável (corpo grande demais, JSON inválido, 4xx): não repetir a consulta
BREAKER_429_SECONDS = 15 * 60  # idem depois de HTTP 429: o host é o mesmo dos preços
MAX_QUOTES = 10  # itens de `quotes` considerados por resposta (pedimos 8)
MAX_INSERTS = 3  # papéis novos que uma consulta pode pôr no catálogo
QUOTE_KINDS = {"EQUITY": "Ação", "ETF": "ETF"}  # só estes tipos entram no catálogo
MAX_BODY = 1_000_000
MAX_NAME = 80
MIN_REMOTE_CHARS = 3  # consulta menor que isso não vai à rede
CACHE_SECONDS = 24 * 3600
CACHE_MAX = 256
SCORE_EXACT, SCORE_PREFIX, SCORE_REMOTE, SCORE_NAME = 1000, 600, 450, 300
SCORE_NICK, SCORE_NICK_EXTRA = 950, 500  # apelido de marca; EXTRA só acrescenta o papel, sem passar os demais
MIN_NICK_PREFIX = 4  # letras digitadas para um prefixo de apelido valer

ABBR = {"bco": "banco", "cia": "companhia", "part": "participacoes", "empr": "empreendimentos",
        "energ": "energia", "sid": "siderurgica", "ind": "industria", "com": "comercio",
        "adm": "administracao", "fin": "financeira", "inv": "investimentos", "transm": "transmissao",
        "distr": "distribuidora", "saneam": "saneamento", "educ": "educacao", "seg": "seguros",
        "tecnol": "tecnologia", "telecom": "telecomunicacoes", "petr": "petroleo", "bras": "brasil"}
STOPWORDS = frozenset("de do da dos das e s a sa the of inc corp co ltd plc nv ag on pn unit".split())
# fora da cobertura do nome: palavras vazias e sufixos societários
NAME_NOISE = STOPWORDS | frozenset({"corporation", "holding", "holdings"})
COVERAGE_POINTS, INDEX_POINTS, HOME_POINTS, STOCK_POINTS, RIGHTS_PENALTY = 150, 40, 30, 20, 250
HOME_MARKETS = ("B3", "CRYPTO")  # o dono é brasileiro; a lista de cripto é curta e curada
FULL_COVERAGE = 0.99
_RIGHTS_RE = re.compile(r"[A-Z0-9]{4}(1|2|9|10)")  # BBDC1, PETR10: direitos e recibos de subscrição da B3


def _nicks(boost: int, table: dict[str, str]) -> dict[str, tuple[int, tuple[tuple[str, str], ...]]]:
    return {nick: (boost, tuple(tuple(p.split("/")) for p in papers.split())) for nick, papers in table.items()}


# Apelido de marca (normalizado) -> (pontuação, papéis em ordem de preferência). Nem o catálogo nem a busca
# on-line ligam "vivo" à VIVT3. Só vale para os papéis que existem no catálogo no momento.
NICKNAMES = {
    **_nicks(SCORE_NICK, {
        "vivo": "VIVT3/B3", "magalu": "MGLU3/B3", "nubank": "ROXO34/B3 NU/US", "nu": "NU/US", "bb": "BBAS3/B3",
        "santander": "SANB11/B3 BSBR/US", "btg": "BPAC11/B3", "xp": "XP/US", "mercado livre": "MELI34/B3 MELI/US",
        "tim": "TIMS3/B3", "oi": "OIBR3/B3", "americanas": "AMER3/B3", "casas bahia": "BHIA3/B3",
        "renner": "LREN3/B3", "assai": "ASAI3/B3", "natura": "NATU3/B3 NTCO3/B3", "rede dor": "RDOR3/B3",
        "porto seguro": "PSSA3/B3", "sabesp": "SBSP3/B3", "copel": "CPLE6/B3 CPLE3/B3",
        "cemig": "CMIG4/B3 CMIG3/B3", "csn": "CSNA3/B3", "gerdau": "GGBR4/B3", "usiminas": "USIM5/B3",
        "braskem": "BRKM5/B3", "klabin": "KLBN11/B3", "azul": "AZUL4/B3", "inter": "INBR32/B3",
        "stone": "STNE/US", "pagbank": "PAGS/US"}),
    # a busca por nome já acha o papel americano em 1º: aqui o apelido só acrescenta o BDR da B3
    **_nicks(SCORE_NICK_EXTRA, {
        "google": "GOGL34/B3 GOOGL/US GOOG/US", "facebook": "M1TA34/B3 META/US", "amazon": "AMZO34/B3 AMZN/US",
        "tesla": "TSLA34/B3 TSLA/US", "nvidia": "NVDC34/B3 NVDA/US", "microsoft": "MSFT34/B3 MSFT/US",
        "apple": "AAPL34/B3 AAPL/US"}),
}
US_EXCHANGES = frozenset({"NMS", "NGM", "NCM", "NYQ", "ASE", "PCX", "BTS"})
_B3_RE = re.compile(r"[A-Z0-9]{4,6}[0-9]{1,2}")
_FRACTION_RE = re.compile(r"[A-Z0-9]{4}[0-9]{1,2}F")  # PETR4F: mercado fracionário
_US_RE = re.compile(r"[A-Z]{1,5}(-[A-Z])?")
_NOT_WORD_RE = re.compile(r"[^a-z0-9]+")
_CLASS_RE = re.compile(r"([A-Z0-9]{4})(\d{1,2})")  # código da B3: empresa + classe
_CLASS_ORDER = {"4": 0, "3": 1, "11": 2}  # PN antes de ON antes de unit; o resto depois
_DROP = ("Cs", "Co", "Cn")  # substitutos solitários, uso privado, não atribuídos: o SQLite nem codifica

_lock = threading.Lock()
_state: tuple | None = None  # (conexão, geração, entradas do índice, item por (símbolo, mercado))
_generation = 0  # sobe a cada `invalidate()`; índice de geração antiga é refeito na próxima busca
_remote_cache: dict[str, tuple[float, list[dict]]] = {}  # consulta normalizada -> (validade, acertos)
_pending: dict[str, asyncio.Future] = {}  # consultas em voo: quem chega depois espera a mesma requisição
_blocked_until = 0.0  # disjuntor: até este instante (`_now()`) a busca não vai à rede


class SearchError(Exception):
    status: int | None = None  # status HTTP, quando a falha foi essa


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
    """Nome vindo de terceiros: sem controle/formatação nem o que não se codifica em UTF-8, espaços
    colapsados, até MAX_NAME."""
    if not isinstance(value, str):
        return ""
    kept = ((c, unicodedata.category(c)) for c in value)
    text = "".join(" " if cat in ("Cc", "Cf") else c for c, cat in kept if cat not in _DROP)
    return " ".join(text.encode("utf-8", "ignore").decode().split())[:MAX_NAME]


# ---------- índice em memória ----------

def invalidate() -> None:
    """Marca o índice como velho; a próxima busca o reconstrói (numa thread). Chamar quando o catálogo ou um
    alias mudar. Não espera o lock: pode ser chamada do event loop com uma reconstrução em curso."""
    global _generation
    _generation += 1


def _entry(row: dict) -> tuple:
    code = _words(row["symbol"])
    names = [_words(n) for n in (row["name"], row["alias"] or "")]
    tokens = frozenset(t for words in names for w in words for t in _variants(w))
    firsts = tuple({t for words in names for w in words[:1] for t in _variants(w)})
    blob = " " + " ".join(code + sorted(tokens))  # " tok": prefixo de token = substring
    # para a cobertura: as palavras distintas de cada nome (cru e alias), cada uma com suas variantes;
    # nome que é o próprio código (FIIs, ETFs e BDRs na fonte da B3) não cobre nada
    cover = tuple(tuple(_variants(w) for w in dict.fromkeys(words) if w not in NAME_NOISE)
                  for words in names if words != code)
    item = {"symbol": row["symbol"], "market": row["market"],
            "name": db.display_name(row["symbol"], row["name"], row["alias"]),
            "kind": row["kind"], "indices": row["indices"]}
    bonus = (INDEX_POINTS * len(row["indices"]) + HOME_POINTS * (row["market"] in HOME_MARKETS)
             + STOCK_POINTS * (row["kind"] == "Ação"))
    rights = RIGHTS_PENALTY * bool(row["market"] == "B3" and _RIGHTS_RE.fullmatch(row["symbol"]))
    return row["symbol"], blob, firsts, tokens, cover, bonus, rights, item


def _coverage(cover: tuple, wanted: tuple[str, ...]) -> float:
    """Fração das palavras do nome que a consulta casou (igualdade vale 1, só prefixo vale meio), no melhor
    entre o nome cru e o alias: "Bitcoin" (1,0) passa "Bitcoin Cash" (0,5); "itau" prefere "Itaú" a "Itaúsa"."""
    best = 0.0
    for words in cover:
        hit = 0.0
        for variants in words:  # laço explícito: roda para todo papel que casa (milhares numa consulta curta)
            for v in variants:
                if v in wanted:
                    hit += 1.0
                    break
            else:
                for v in variants:
                    if v.startswith(wanted):
                        hit += 0.5
                        break
        if hit > best * len(words):
            best = hit / len(words)
    return best


def _index(conn) -> tuple[list[tuple], dict]:
    global _state
    with _lock:
        if _state is None or _state[0] is not conn or _state[1] != _generation:
            generation = _generation  # lida antes do catálogo: invalidação durante a obra vale para a próxima
            entries = [_entry(r) for r in db.all_catalog(conn)]
            _state = (conn, generation, entries, {(e[-1]["symbol"], e[-1]["market"]): e[-1] for e in entries})
        return _state[2], _state[3]


@functools.lru_cache(maxsize=32768)
def _tie(symbol: str, market: str) -> tuple:
    """Desempate: símbolo mais curto, depois ordem alfabética; classes da mesma empresa na B3 ficam juntas,
    PN (4) antes de ON (3) antes de unit (11) antes das demais."""
    m = _CLASS_RE.fullmatch(symbol) if market == "B3" else None
    if m:
        return 5, m[1], _CLASS_ORDER.get(m[2], 3), symbol, market
    return len(symbol), symbol, 0, symbol, market


def _order(scored: tuple):
    score, coverage, item = scored[:3]
    return -score, -coverage, *_tie(item["symbol"], item["market"])


def _code(q: str) -> str:
    """A consulta como código de papel: maiúsculas, sem um sufixo `.SA`."""
    code = q.strip().upper()
    return code[:-3] if code.endswith(".SA") else code


def _rank(conn, q: str) -> list[tuple[float, float, dict, bool]]:
    """Todos os papéis que casam com a consulta, como (pontuação, cobertura, item, resolvido), do melhor para
    o pior. `resolvido`: toda palavra da consulta é uma palavra inteira do nome, ou a consulta é um apelido.

    Símbolo exato 1000; apelido de marca 950; prefixo de símbolo 600; nome 300 (+80 primeira palavra, +40
    igualdade); mais 150 x cobertura do nome, 40 por índice, 30 se B3/cripto, 20 se ação; direito/recibo da
    B3 perde 250."""
    words = _words(q)
    groups = [_variants(w) for w in ([w for w in words if w not in STOPWORDS] or words)]
    needles = [tuple(" " + v for v in g) for g in groups]
    code = _code(q)
    if not code:
        return []
    wanted = tuple(v for g in groups for v in g)
    entries, by_key = _index(conn)
    out = []
    for symbol, blob, firsts, tokens, cover, bonus, rights, item in entries:
        if symbol == code:
            score = SCORE_EXACT + rights  # quem digitou o código inteiro quer esse papel: sem penalidade
        elif symbol.startswith(code):
            score = SCORE_PREFIX
        elif needles and all(any(n in blob for n in g) for g in needles):
            score = (SCORE_NAME + 80 * any(f.startswith(v) for v in groups[0] for f in firsts)
                     + 40 * any(v in tokens for v in wanted))
        else:
            continue
        coverage = _coverage(cover, wanted)
        solid = bool(groups) and all(any(v in tokens for v in g) for g in groups)
        out.append((score + COVERAGE_POINTS * coverage + bonus - rights, coverage, item, solid))
    nick = _nicknamed(" ".join(words), by_key)
    if nick:
        rows = {(r[2]["symbol"], r[2]["market"]): r for r in out}
        for key, score in nick.items():
            old = rows.get(key, (0, 0.0, by_key[key], True))
            rows[key] = (max(score, old[0]), old[1], old[2], True)
        out = list(rows.values())
    out.sort(key=_order)
    return out


def _nicknamed(query: str, by_key: dict) -> dict[tuple[str, str], int]:
    """Papéis do catálogo que a consulta alcança por apelido de marca (igual, ou prefixo com 4+ letras), com
    a pontuação de cada um; a ordem de preferência do apelido desempata (950, 949...)."""
    out: dict[tuple[str, str], int] = {}
    for nick, (boost, papers) in NICKNAMES.items():
        if query == nick or (len(query) >= MIN_NICK_PREFIX and nick.startswith(query)):
            for i, key in enumerate(k for k in papers if k in by_key):
                out[key] = max(out.get(key, 0), boost - i)
    return out


def _public(ranked: list[tuple], limit: int) -> list[dict]:
    return [{**r[2], "indices": list(r[2]["indices"])} for r in ranked[:limit]]  # cópia: o índice fica intacto


def search_local(conn, q: str, limit: int = 12) -> list[dict]:
    return _public(_rank(conn, q), limit)


# ---------- reforço on-line ----------

def clear_remote_cache() -> None:
    """Esquece o cache, as consultas em voo e o disjuntor (testes)."""
    global _blocked_until
    _remote_cache.clear()
    _pending.clear()
    _blocked_until = 0.0


async def yahoo_quotes(q: str, transport: httpx.AsyncBaseTransport | None = None,
                       timeout: float = TIMEOUT) -> list[dict]:
    """Os primeiros MAX_QUOTES itens de `quotes` da busca do Yahoo. Levanta em qualquer falha (rede, status,
    tamanho, JSON)."""
    async def fetch() -> bytes:
        async with httpx.AsyncClient(transport=transport, timeout=timeout, headers=HEADERS) as client:
            async with client.stream("GET", YAHOO_URL,
                                     params={"q": q, "quotesCount": 8, "newsCount": 0}) as resp:
                if resp.status_code != 200:
                    error = SearchError(f"HTTP {resp.status_code}")
                    error.status = resp.status_code
                    raise error
                body = b""
                async for chunk in resp.aiter_bytes():
                    body += chunk
                    if len(body) > MAX_BODY:
                        raise SearchError("resposta grande demais")
        return body

    data = json.loads(await asyncio.wait_for(fetch(), timeout))  # teto para a chamada inteira
    quotes = data.get("quotes") if isinstance(data, dict) else None
    if not isinstance(quotes, list):
        raise SearchError("JSON inesperado")
    return [x for x in quotes[:MAX_QUOTES] if isinstance(x, dict)]


def _map(quote: dict) -> dict | None:
    """Item do Yahoo -> {symbol, market, name, kind}; None para outras bolsas, fracionário e OTC.
    `kind` só vem para ação e ETF: é o que autoriza inserir o papel no catálogo."""
    symbol, exchange, quote_type = quote.get("symbol"), quote.get("exchange"), quote.get("quoteType")
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
            "name": clean_name(quote.get("longname")) or clean_name(quote.get("shortname")) or None,
            "kind": QUOTE_KINDS.get(quote_type) if isinstance(quote_type, str) else None}


def _remember(key: str, hits: list[dict], seconds: float) -> None:
    _remote_cache.pop(key, None)
    _remote_cache[key] = (_now() + seconds, hits)
    while len(_remote_cache) > CACHE_MAX:
        del _remote_cache[next(iter(_remote_cache))]  # a mais antiga


async def _fetch_remote(key: str, transport) -> list[dict]:
    """Uma ida à rede: mapeia, guarda no cache e registra; falha abre o disjuntor e devolve lista vazia."""
    global _blocked_until
    started = time.monotonic()
    try:
        found = {}
        for quote in await yahoo_quotes(key, transport, SEARCH_TIMEOUT):
            mapped = _map(quote)
            if mapped:
                found.setdefault((mapped["symbol"], mapped["market"]), mapped)
    except Exception as e:  # noqa: BLE001 - rede, status, tamanho, JSON, recursão: a busca local segue valendo
        status = getattr(e, "status", None)
        if isinstance(e, (httpx.HTTPError, asyncio.TimeoutError, OSError)) or (status or 0) >= 500 or status == 429:
            pause = BREAKER_429_SECONDS if status == 429 else BREAKER_SECONDS
            _blocked_until = _now() + pause  # a fonte está mal (e é a mesma dos preços): disjuntor
            log.warning("busca on-line de %r falhou (%s: %s); sem rede por %d s", key, type(e).__name__, e, pause)
        else:  # resposta imprestável só para esta consulta: cache negativo curto, sem disjuntor
            _remember(key, [], NEGATIVE_SECONDS)
            log.warning("busca on-line de %r sem resposta útil (%s: %s)", key, type(e).__name__, e)
        return []
    hits = list(found.values())
    _remember(key, hits, CACHE_SECONDS)
    log.info("busca on-line de %r: %d acerto(s) em %.2f s", key, len(hits), time.monotonic() - started)
    return hits


async def _consult(q: str, transport: httpx.AsyncBaseTransport | None = None) -> tuple[list[dict], bool]:
    """(acertos, se a fonte foi consultada — agora, por outra chamada em voo ou pelo cache)."""
    key = " ".join(q.lower().split())
    if len(key) < MIN_REMOTE_CHARS:
        return [], False
    hit = _remote_cache.get(key)
    if hit and _now() < hit[0]:
        return [dict(h) for h in hit[1]], True
    flying = _pending.get(key)
    if flying is not None:  # shield: desistir de esperar não cancela a requisição dos outros
        return [dict(h) for h in await asyncio.shield(flying)], True
    if _now() < _blocked_until:
        return [], False
    future = _pending[key] = asyncio.get_running_loop().create_future()
    hits: list[dict] = []
    try:
        hits = await _fetch_remote(key, transport)
    finally:  # também no cancelamento: quem esperava segue só com o resultado local
        _pending.pop(key, None)
        future.set_result(hits)
    return [dict(h) for h in hits], True


async def search_remote(q: str, transport: httpx.AsyncBaseTransport | None = None) -> list[dict]:
    """Acertos da busca do Yahoo já mapeados e filtrados; nunca levanta (falha = lista vazia).

    Resposta boa (mesmo vazia) vale por CACHE_SECONDS e resposta imprestável por NEGATIVE_SECONDS; depois de
    falha da fonte o disjuntor pula a rede por um tempo; consultas iguais em voo compartilham a requisição."""
    return (await _consult(q, transport))[0]


def _learn(conn, ranked: list[tuple], hits: list[dict]) -> list[tuple]:
    """Grava o que a rede ensinou e junta os acertos aos locais.

    Alias para quem não tinha; papel fora do catálogo só entra com nome e tipo conhecidos (ação ou ETF), no
    máximo MAX_INSERTS por consulta. Falha ao gravar um papel não impede os demais nem a resposta."""
    best = {(r[2]["symbol"], r[2]["market"]): r for r in ranked}
    missing = {(s, m) for m in {h["market"] for h in hits}
               for s in db.missing_alias(conn, m, [h["symbol"] for h in hits if h["market"] == m])}
    learned, inserted = False, 0
    for h in hits:
        key = (h["symbol"], h["market"])
        entry = None
        try:
            entry = db.catalog_entry(conn, *key)
            if entry is None:
                if h["name"] and h["kind"] and inserted < MAX_INSERTS:
                    db.upsert_catalog_entry(conn, *key, h["name"], h["kind"])
                    inserted += 1
                    learned = True
            elif h["name"] and key in missing:
                learned |= db.set_alias(conn, *key, db.pretty_name(h["name"]))
            entry = db.catalog_entry(conn, *key)
        except Exception:  # noqa: BLE001
            log.exception("falha ao gravar o que a busca on-line trouxe sobre %s", h["symbol"])
            if entry is None and h["name"] and h["kind"]:  # não entrou no catálogo, mas a busca o mostra
                entry = {"symbol": h["symbol"], "market": h["market"], "kind": h["kind"], "indices": [],
                         "name": db.display_name(h["symbol"], h["name"])}
        if entry:
            score, coverage, _, solid = best.get(key, (0, 0.0, None, False))
            best[key] = (max(SCORE_REMOTE, score), coverage, entry, solid)
    if learned:
        invalidate()
    return sorted(best.values(), key=_order)


def _weak(ranked: list[tuple], q: str) -> bool:
    """O catálogo não resolve a consulta: nenhum resultado `resolvido` (palavras inteiras do nome, apelido),
    nenhum nome coberto por inteiro, nenhum na faixa de prefixo de símbolo (ou acima) e nenhum símbolo exato
    que baste. Símbolo exato basta quando a consulta tem dígito ou o papel é da B3/cripto."""
    code = _code(q)
    digit = any(c.isdigit() for c in code)
    for score, coverage, item, solid in ranked:
        if solid:
            return False
        if item["symbol"] == code:
            if digit or item["market"] in HOME_MARKETS:
                return False
        elif coverage >= FULL_COVERAGE or score >= SCORE_PREFIX:
            return False
    return True


async def search_detail(conn, q: str, limit: int, settings, transport: httpx.AsyncBaseTransport | None = None,
                        remote: bool = True) -> tuple[list[dict], bool]:
    """(resultados, se a fonte on-line foi consultada). Busca local; só se o catálogo não resolver, fora do
    modo sintético e com `remote`, reforça com a busca on-line e aprende. `remote=False`: nunca toca a rede."""
    ranked = await asyncio.to_thread(_rank, conn, q)
    consulted = False
    if remote and settings.provider != "synthetic" and len(q.strip()) >= MIN_REMOTE_CHARS and _weak(ranked, q):
        hits, consulted = await _consult(q, transport)
        if hits:
            try:
                ranked = await asyncio.to_thread(_learn, conn, ranked, hits)
            except Exception:  # noqa: BLE001 - o que o catálogo já tinha continua valendo
                log.exception("falha ao juntar os acertos da busca on-line de %r", q)
    return _public(ranked, limit), consulted


async def search(conn, q: str, limit: int, settings, transport: httpx.AsyncBaseTransport | None = None,
                 remote: bool = True) -> list[dict]:
    return (await search_detail(conn, q, limit, settings, transport, remote))[0]
