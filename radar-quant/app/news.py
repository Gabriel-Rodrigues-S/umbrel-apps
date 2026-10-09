"""Notícias por ativo: Google Notícias (RSS) e busca do Yahoo, saneadas, sem duplicatas, com cache no SQLite.

O conteúdo vem de terceiros: só URLs http(s), textos limitados, XML com DTD/entidades rejeitado."""
import html
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import httpx

from . import db

TTL_SECONDS = 1800
MAX_ITEMS = 20
MAX_BODY = 2_000_000
MAX_TITLE = 300
MAX_SOURCE = 80
MAX_URL = 2000

GOOGLE_URL = "https://news.google.com/rss/search"
YAHOO_URL = "https://query1.finance.yahoo.com/v1/finance/search"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; RadarQuantBot/1.0)"}


class NewsError(Exception):
    pass


def _clean(value, limit: int) -> str:
    if not isinstance(value, str):
        return ""
    return re.sub(r"\s+", " ", html.unescape(value)).strip()[:limit]


def _url(value) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    if len(value) > MAX_URL or not re.match(r"https?://", value, re.IGNORECASE):
        return None
    return value


def _item(title, url, source, published_at) -> dict | None:
    title, url = _clean(title, MAX_TITLE), _url(url)
    if not title or not url:
        return None
    return {"title": title, "url": url, "source": _clean(source, MAX_SOURCE) or None,
            "published_at": published_at}


def _rss_date(text: str | None) -> str | None:
    try:
        dt = parsedate_to_datetime(text)
    except (TypeError, ValueError, IndexError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def parse_google_rss(text: str) -> list[dict]:
    if not isinstance(text, str) or len(text) > MAX_BODY:
        raise NewsError("RSS grande demais")
    upper = text.upper()
    if "<!DOCTYPE" in upper or "<!ENTITY" in upper:
        raise NewsError("RSS com DTD/entidades rejeitado")
    try:
        root = ET.fromstring(text)
    except ET.ParseError as e:
        raise NewsError(f"RSS malformado: {e}") from e
    out = []
    for el in root.iter("item"):
        source = _clean(el.findtext("source"), MAX_SOURCE)
        title = _clean(el.findtext("title"), 10 * MAX_TITLE)  # corta só depois de tirar o sufixo
        suffix = f" - {source}"
        if source and title.endswith(suffix):
            title = title[: -len(suffix)]
        it = _item(title, el.findtext("link"), source, _rss_date(el.findtext("pubDate")))
        if it:
            out.append(it)
    return out


def parse_yahoo(payload: dict) -> list[dict]:
    entries = payload.get("news") if isinstance(payload, dict) else None
    if not isinstance(entries, list):
        return []
    out = []
    for e in entries:
        if not isinstance(e, dict):
            continue
        published = None
        try:
            published = datetime.fromtimestamp(e["providerPublishTime"], timezone.utc).isoformat()
        except (KeyError, TypeError, ValueError, OverflowError, OSError):
            pass
        it = _item(e.get("title"), e.get("link"), e.get("publisher"), published)
        if it:
            out.append(it)
    return out


def merge(items: list[dict]) -> list[dict]:
    seen, unique = set(), []
    for it in items:
        key = re.sub(r"\W+", " ", it["title"].lower()).strip()
        if key not in seen:
            seen.add(key)
            unique.append(it)
    dated = sorted((i for i in unique if i.get("published_at")), key=lambda i: i["published_at"], reverse=True)
    return (dated + [i for i in unique if not i.get("published_at")])[:MAX_ITEMS]


def synthetic_news(symbol: str) -> list[dict]:
    return [{"title": f"Notícia de exemplo {n} sobre {symbol}", "url": f"https://example.com/noticia/{symbol}/{n}",
             "source": "Exemplo", "published_at": f"2024-01-0{n}T12:00:00+00:00"} for n in (1, 2, 3)]


async def _get(client: httpx.AsyncClient, url: str, params: dict) -> httpx.Response:
    resp = await client.get(url, params=params)
    if resp.status_code != 200:
        raise NewsError(f"HTTP {resp.status_code}")
    if len(resp.content) > MAX_BODY:
        raise NewsError("resposta grande demais")
    return resp


async def fetch_news(symbol: str, market: str, name: str | None,
                     transport: httpx.AsyncBaseTransport | None = None) -> list[dict]:
    if market == "US":
        google = {"q": f"{symbol} stock", "hl": "en-US", "gl": "US", "ceid": "US:en"}
    else:
        query = (name or symbol) if market == "CRYPTO" else symbol
        google = {"q": query, "hl": "pt-BR", "gl": "BR", "ceid": "BR:pt-419"}
    jobs = [(GOOGLE_URL, google, lambda r: parse_google_rss(r.text))]
    if market == "US":
        yahoo = {"q": symbol, "newsCount": 10, "quotesCount": 0}
        jobs.append((YAHOO_URL, yahoo, lambda r: parse_yahoo(r.json())))
    items, ok = [], False
    async with httpx.AsyncClient(transport=transport, timeout=15, headers=HEADERS) as client:
        for url, params, parse in jobs:
            try:
                items += parse(await _get(client, url, params))
                ok = True
            except (httpx.HTTPError, NewsError, ValueError):
                continue  # uma fonte fora do ar não impede a outra
    if not ok:
        raise NewsError("todas as fontes de notícias falharam")
    return merge(items)


def _fresh(fetched_at: str | None) -> bool:
    try:
        age = datetime.now(timezone.utc) - datetime.fromisoformat(fetched_at)
    except (TypeError, ValueError):
        return False
    return age.total_seconds() < TTL_SECONDS


async def get_news(conn, asset: dict, settings, transport: httpx.AsyncBaseTransport | None = None) -> dict:
    cached, fetched_at = db.load_news(conn, asset["id"])
    if _fresh(fetched_at):
        return {"items": cached, "fetched_at": fetched_at, "stale": False}
    try:
        if settings.provider == "synthetic":
            items = synthetic_news(asset["symbol"])
        else:
            entry = db.catalog_entry(conn, asset["symbol"], asset["market"])
            items = await fetch_news(asset["symbol"], asset["market"], (entry or {}).get("name"), transport)
    except NewsError:
        return {"items": cached, "fetched_at": fetched_at, "stale": True}
    db.replace_news(conn, asset["id"], items)
    cached, fetched_at = db.load_news(conn, asset["id"])
    return {"items": cached, "fetched_at": fetched_at, "stale": False}
