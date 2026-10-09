"""Catálogo de papéis (B3, EUA, cripto) e composição dos índices, de fontes públicas."""
import base64
import csv
import io
import json
import re
from datetime import datetime, timedelta, timezone

import httpx

from . import db
from .config import INDICES

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; RadarQuantBot/1.0)"}
MAX_BYTES = 5_000_000
MIN_ROWS = {"US": 3000, "B3": 200}
MIN_INDEX = {"IBOV": 40, "IBRA": 80, "SP500": 400, "NDX": 90}  # abaixo disso a fonte é lixo

URL_NASDAQ = "https://www.nasdaqtrader.com/dynamic/symdir/nasdaqlisted.txt"
URL_OTHER = "https://www.nasdaqtrader.com/dynamic/symdir/otherlisted.txt"
URL_BRAPI = "https://brapi.dev/api/quote/list"
URL_B3_INDEX = "https://sistemaswebb3-listados.b3.com.br/indexProxy/indexCall/GetPortfolioDay/"
URL_SP500 = "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/main/data/constituents.csv"
URL_WIKI = "https://en.wikipedia.org/w/api.php"
# A página "Nasdaq-100" deixou de listar os componentes; a lista fica em outra página (a primeira que servir).
WIKI_PAGES = ("List_of_NASDAQ-100_companies", "Nasdaq-100")

_US_RE = re.compile(r"[A-Z][A-Z0-9.]{0,9}")
_B3_RE = re.compile(r"[A-Z0-9]{4,6}[0-9]{1,2}")
_NDX_ROW_RE = re.compile(r"^\|\s*(?:\{\{NasdaqSymbol\|)?([A-Z]{1,5})(?:\}\})?\s*(?:\|\||$)", re.M)
_SUFFIX_RE = re.compile(r"\s+(?:Class [A-Z]\s+)?(?:Common Stock|Ordinary Shares?)\s*$", re.I)
_ETF_NAME_RE = re.compile(r"ETF|ISHARES|INDEX", re.I)
_CTRL_RE = re.compile(r"[\x00-\x1f\x7f]")

CRYPTO_CATALOG = [(s, n, "Cripto") for s, n in [
    ("BTC", "Bitcoin"), ("ETH", "Ethereum"), ("BNB", "BNB"), ("XRP", "XRP"), ("SOL", "Solana"),
    ("ADA", "Cardano"), ("DOGE", "Dogecoin"), ("TRX", "TRON"), ("AVAX", "Avalanche"),
    ("LINK", "Chainlink"), ("DOT", "Polkadot"), ("LTC", "Litecoin"), ("BCH", "Bitcoin Cash"),
    ("ATOM", "Cosmos"), ("UNI", "Uniswap"), ("XLM", "Stellar"), ("ETC", "Ethereum Classic"),
    ("NEAR", "NEAR Protocol"), ("SHIB", "Shiba Inu"), ("TON", "Toncoin")]]


class CatalogError(Exception):
    pass


async def _get(url, transport=None, params=None) -> str:
    try:
        async with httpx.AsyncClient(transport=transport, timeout=30, headers=HEADERS,
                                     follow_redirects=True) as client:
            resp = await client.get(url, params=params)
    except (httpx.HTTPError, httpx.InvalidURL) as e:
        raise CatalogError(f"{url}: fonte indisponível: {e}") from e
    if resp.status_code != 200:
        raise CatalogError(f"{url}: HTTP {resp.status_code}")
    if len(resp.content) > MAX_BYTES:
        raise CatalogError(f"{url}: resposta grande demais")
    return resp.text


def _json(text: str, url: str):
    try:
        return json.loads(text)
    except ValueError as e:
        raise CatalogError(f"{url}: JSON inválido") from e


def _clean(name: str) -> str:
    """Sem caracteres de controle, espaços colapsados, até 80 caracteres."""
    return " ".join(_CTRL_RE.sub(" ", name).split())[:80]


def _clean_name(name: str) -> str:
    return _clean(_SUFFIX_RE.sub("", _clean(name).split(" - ")[0]))


def _parse_us(text: str, sym_col: str) -> list[tuple[str, str, str]]:
    lines = text.splitlines()
    need = {sym_col, "Security Name", "Test Issue", "ETF"}
    if not lines or not need <= set(lines[0].split("|")):
        raise CatalogError(f"cabeçalho inesperado (esperado: {', '.join(sorted(need))})")
    out = []
    try:
        for r in csv.DictReader(lines, delimiter="|"):
            sym = (r.get(sym_col) or "").strip()
            if r.get("Test Issue") == "Y" or not _US_RE.fullmatch(sym):  # rodapé e `$` caem aqui
                continue
            out.append((sym, _clean_name(r.get("Security Name") or "") or sym,
                        "ETF" if r.get("ETF") == "Y" else "Ação"))
    except csv.Error as e:
        raise CatalogError(f"CSV inválido: {e}") from e
    return out


async def fetch_us(transport=None) -> list[tuple[str, str, str]]:
    seen, out = set(), []
    for url, col in ((URL_NASDAQ, "Symbol"), (URL_OTHER, "ACT Symbol")):
        rows = _parse_us(await _get(url, transport), col)
        if not rows:
            raise CatalogError(f"{url}: nenhuma linha válida")
        for row in rows:
            if row[0] not in seen:
                seen.add(row[0])
                out.append(row)
    return out


async def fetch_b3(transport=None) -> list[tuple[str, str, str]]:
    data = _json(await _get(URL_BRAPI, transport), URL_BRAPI)
    stocks = data.get("stocks") if isinstance(data, dict) else None
    if not isinstance(stocks, list):
        raise CatalogError("brapi: resposta sem `stocks`")
    items = [s for s in stocks if isinstance(s, dict) and isinstance(s.get("stock"), str)]
    known = {s["stock"].upper() for s in items}
    out = []
    for s in items:
        sym, name, typ = s["stock"].upper(), str(s.get("name") or ""), s.get("type")
        if (sym.endswith("F") and sym[:-1] in known) or not _B3_RE.fullmatch(sym):
            continue
        if typ == "stock":
            kind = "Ação"
        elif typ == "fund":
            etf = s.get("subType") == "etf" or _ETF_NAME_RE.search(name)
            kind = "ETF" if etf else "FII"
        elif typ == "bdr":
            kind = "BDR"
        else:
            continue
        out.append((sym, _clean(name) or sym, kind))
    return out


def _parse_ndx(text: str) -> list[str]:
    data = _json(text, URL_WIKI)
    try:
        wiki = data["parse"]["wikitext"]["*"]
    except (KeyError, TypeError) as e:
        raise CatalogError("Wikipedia: resposta sem wikitext") from e
    if not isinstance(wiki, str):
        raise CatalogError("Wikipedia: wikitext inválido")
    found = list(dict.fromkeys(_NDX_ROW_RE.findall(wiki)))
    if not MIN_INDEX["NDX"] <= len(found) <= 110:
        raise CatalogError(f"Wikipedia: {len(found)} tickers no Nasdaq-100 (esperado 90 a 110)")
    return found


async def fetch_index(index: str, transport=None) -> list[str]:
    if index not in INDICES:
        raise ValueError(f"índice desconhecido: {index}")
    if index in ("IBOV", "IBRA"):
        arg = {"language": "pt-br", "pageNumber": 1, "pageSize": 300, "index": index, "segment": "1"}
        url = URL_B3_INDEX + base64.b64encode(json.dumps(arg, separators=(",", ":")).encode()).decode()
        data = _json(await _get(url, transport), URL_B3_INDEX)
        results = data.get("results") if isinstance(data, dict) else None
        if not isinstance(results, list):
            raise CatalogError("B3: resposta sem `results`")
        syms = [str(r["cod"]).strip().upper() for r in results if isinstance(r, dict) and r.get("cod")]
    elif index == "SP500":
        text = await _get(URL_SP500, transport)
        try:
            syms = [r["Symbol"].strip() for r in csv.DictReader(io.StringIO(text)) if r.get("Symbol")]
        except (csv.Error, KeyError) as e:
            raise CatalogError("S&P 500: CSV inválido") from e
    else:
        err = None
        for page in WIKI_PAGES:
            try:
                params = {"action": "parse", "page": page, "prop": "wikitext", "format": "json"}
                return _parse_ndx(await _get(URL_WIKI, transport, params))
            except CatalogError as e:
                err = e
        raise err
    syms = list(dict.fromkeys(s for s in syms if _US_RE.fullmatch(s) or _B3_RE.fullmatch(s)))
    if len(syms) < MIN_INDEX[index]:
        raise CatalogError(f"{index}: só {len(syms)} membros (mínimo {MIN_INDEX[index]})")
    return syms


def synthetic_catalog():
    b3 = [("PETR4", "Petrobras PN", "Ação"), ("VALE3", "Vale ON", "Ação"),
          ("ITUB4", "Itaú Unibanco PN", "Ação"), ("BBAS3", "Banco do Brasil ON", "Ação"),
          ("WEGE3", "WEG ON", "Ação"), ("BOVA11", "iShares Ibovespa", "ETF"),
          ("ABCD3", "Alfa ON", "Ação"), ("EFGH4", "Beta PN", "Ação"),
          ("IJKL11", "Gama FII", "FII"), ("MNOP3", "Delta ON", "Ação")]
    us = [("AAPL", "Apple", "Ação"), ("MSFT", "Microsoft", "Ação"), ("NVDA", "NVIDIA", "Ação"),
          ("SPY", "SPDR S&P 500", "ETF"), ("QQQ", "Invesco QQQ", "ETF"), ("TSLA", "Tesla", "Ação"),
          ("AMZN", "Amazon", "Ação"), ("GOOG", "Alphabet", "Ação"), ("META", "Meta Platforms", "Ação"),
          ("NFLX", "Netflix", "Ação"), ("BRK.B", "Berkshire Hathaway", "Ação")]
    ibov = ["PETR4", "VALE3", "ITUB4", "BBAS3", "WEGE3"]
    return ({"B3": b3, "US": us, "CRYPTO": CRYPTO_CATALOG},
            {"IBOV": ibov, "IBRA": ibov + ["ABCD3", "EFGH4", "MNOP3"],
             "SP500": ["AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "GOOG", "META", "NFLX"],
             "NDX": ["AAPL", "MSFT", "NVDA", "TSLA"]})


def catalog_is_stale(conn, days: int = 7) -> bool:
    if db.catalog_count(conn) == 0:
        return True
    try:
        at = datetime.fromisoformat(db.get_meta(conn, "catalog_refreshed_at") or "")
    except ValueError:
        return True
    if at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - at > timedelta(days=days)


def _stamp(conn) -> None:
    db.set_meta(conn, "catalog_refreshed_at", datetime.now(timezone.utc).isoformat())


async def refresh_catalog(conn, settings, transport=None) -> dict:
    """Cada fonte em `try` próprio; o que falhar (ou vier encolhido) mantém o que já estava gravado."""
    out = {"markets": {}, "indices": {}, "errors": []}
    if settings.provider == "synthetic":
        markets, indices = synthetic_catalog()
        for m, rows in markets.items():
            out["markets"][m] = db.replace_catalog_market(conn, m, rows)
        for i, syms in indices.items():
            out["indices"][i] = db.set_index_members(conn, i, INDICES[i][0], syms)
        _stamp(conn)
        return out
    fetched = False
    for market, fetch in (("US", fetch_us), ("B3", fetch_b3)):
        try:
            rows = await fetch(transport)
            if len(rows) < MIN_ROWS[market]:
                raise CatalogError(f"{market}: só {len(rows)} linhas (mínimo {MIN_ROWS[market]})")
            out["markets"][market] = db.replace_catalog_market(conn, market, rows)
            fetched = True
        except Exception as e:  # noqa: BLE001 - uma fonte ruim não derruba as outras
            out["errors"].append(f"{market}: {e}")
    out["markets"]["CRYPTO"] = db.replace_catalog_market(conn, "CRYPTO", CRYPTO_CATALOG)
    for index, (market, _) in INDICES.items():
        try:
            syms = await fetch_index(index, transport)
            old = len(db.index_members(conn, index))
            if old and len(syms) * 2 < old:
                raise CatalogError(f"encolheu de {old} para {len(syms)} membros; mantida a composição anterior")
            out["indices"][index] = db.set_index_members(conn, index, market, syms)
        except Exception as e:  # noqa: BLE001
            out["errors"].append(f"{index}: {e}")
    if fetched:
        _stamp(conn)
    return out
