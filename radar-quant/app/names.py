"""Nome completo dos papéis da B3: a fonte do catálogo abrevia; a busca do Yahoo ensina e o banco guarda (`alias`)."""
import asyncio
import logging

import httpx

from . import db, search

log = logging.getLogger("radar.names")

MAX_FAILS = 3  # falhas de rede seguidas que interrompem o lote
_unnamed: set[tuple[str, str]] = set()  # papéis que a fonte não conhece: não insistir neste processo


async def _lookup(symbol: str, market: str, transport=None) -> str | None:
    """Nome do papel na busca do Yahoo; None se ela não o conhece. Levanta em falha de rede/parse."""
    ticker = f"{symbol}.SA" if market == "B3" else symbol.replace(".", "-")
    for quote in await search.yahoo_quotes(ticker, transport):
        if quote.get("symbol") == ticker:
            return search.clean_name(quote.get("longname")) or search.clean_name(quote.get("shortname")) or None
    return None


async def fetch_name(symbol: str, market: str, transport: httpx.AsyncBaseTransport | None = None) -> str | None:
    if market not in ("B3", "US"):
        return None
    try:
        return await _lookup(symbol, market, transport)
    except Exception as e:  # noqa: BLE001 - qualquer falha vira "sem nome"
        log.warning("nome de %s não obtido: %s: %s", symbol, type(e).__name__, e)
        return None


async def learn_names(conn, market: str, symbols: list[str], pace: float = 0.5, limit: int = 40,
                      sleep=asyncio.sleep, transport: httpx.AsyncBaseTransport | None = None) -> int:
    """Busca e grava o nome completo dos `symbols` ainda sem alias (até `limit` consultas); devolve quantos gravou."""
    missing = await asyncio.to_thread(db.missing_alias, conn, market, symbols)
    todo = [s for s in missing if (s, market) not in _unnamed][:limit]
    saved = fails = 0
    try:
        for i, symbol in enumerate(todo):
            if i:
                await sleep(pace)
            try:
                name = await _lookup(symbol, market, transport)
            except Exception as e:  # noqa: BLE001
                log.warning("nome de %s não obtido: %s: %s", symbol, type(e).__name__, e)
                fails += 1
                if fails >= MAX_FAILS:
                    break
                continue
            fails = 0
            try:
                if name and await asyncio.to_thread(db.set_alias, conn, symbol, market, db.pretty_name(name)):
                    saved += 1
                    continue
            except Exception:  # noqa: BLE001 - nome que não grava vale como "sem nome": o lote segue
                log.exception("falha ao gravar o nome de %s", symbol)
            _unnamed.add((symbol, market))
    finally:
        if saved:
            search.invalidate()
    return saved
