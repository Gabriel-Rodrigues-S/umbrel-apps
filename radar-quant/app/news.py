"""Notícias por ativo: Google Notícias (RSS) e busca do Yahoo, saneadas, sem duplicatas, com cache no SQLite.

O conteúdo vem de terceiros: só URLs http(s), textos limitados, XML com DTD/entidades rejeitado."""
import asyncio
import html
import json
import re
import unicodedata
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit

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
    text = re.sub(r"\s+", " ", html.unescape(value))
    # tira controle (Cc) e formatação/direção como U+202E (Cf)
    text = "".join(c for c in text if unicodedata.category(c) not in ("Cc", "Cf"))
    return text.strip()[:limit]


def _url(value) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    if len(value) > MAX_URL or any(c.isspace() or unicodedata.category(c) == "Cc" for c in value):
        return None
    try:
        parts = urlsplit(value)
    except ValueError:
        return None
    return value if parts.scheme.lower() in ("http", "https") and parts.netloc else None


def _item(title, url, source, published_at) -> dict | None:
    title, url = _clean(title, MAX_TITLE), _url(url)
    if not title or not url:
        return None
    return {"title": title, "url": url, "source": _clean(source, MAX_SOURCE) or None,
            "published_at": published_at}


def _iso(dt: datetime) -> str | None:
    """ISO UTC; datas mais de 1 dia no futuro (feed hostil ou relógio errado) viram None."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return None if dt > datetime.now(timezone.utc) + timedelta(days=1) else dt.isoformat()


def _rss_date(text: str | None) -> str | None:
    try:
        return _iso(parsedate_to_datetime(text))
    except (TypeError, ValueError, IndexError, OverflowError):
        return None


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
            published = _iso(datetime.fromtimestamp(e["providerPublishTime"], timezone.utc))
        except (KeyError, TypeError, ValueError, OverflowError, OSError):
            pass
        it = _item(e.get("title"), e.get("link"), e.get("publisher"), published)
        if it:
            out.append(it)
    return out


def merge(items: list[dict]) -> list[dict]:
    seen, unique = set(), []
    for it in items:
        key = re.sub(r"\W+", " ", it["title"].lower()).strip() or it["title"].lower()
        if key not in seen:
            seen.add(key)
            unique.append(it)
    dated = sorted((i for i in unique if i.get("published_at")), key=lambda i: i["published_at"], reverse=True)
    return (dated + [i for i in unique if not i.get("published_at")])[:MAX_ITEMS]


def synthetic_news(symbol: str) -> list[dict]:
    return [{"title": f"Notícia de exemplo {n} sobre {symbol}", "url": f"https://example.com/noticia/{symbol}/{n}",
             "source": "Exemplo", "published_at": f"2024-01-0{n}T12:00:00+00:00"} for n in (1, 2, 3)]


async def _get(client: httpx.AsyncClient, url: str, params: dict) -> bytes:
    """Lê o corpo em blocos e aborta ao passar de MAX_BODY bytes."""
    async with client.stream("GET", url, params=params) as resp:
        if resp.status_code != 200:
            raise NewsError(f"HTTP {resp.status_code}")
        body = b""
        async for chunk in resp.aiter_bytes():
            body += chunk
            if len(body) > MAX_BODY:
                raise NewsError("resposta grande demais")
    return body


def _parse_yahoo_body(body: bytes) -> list[dict]:
    try:
        return parse_yahoo(json.loads(body))
    except (ValueError, RecursionError) as e:
        raise NewsError(f"JSON inválido: {e!r}") from e


async def fetch_news(symbol: str, market: str, name: str | None,
                     transport: httpx.AsyncBaseTransport | None = None) -> list[dict]:
    if market == "US":
        google = {"q": f"{symbol} stock", "hl": "en-US", "gl": "US", "ceid": "US:en"}
    else:
        query = (name or symbol) if market == "CRYPTO" else symbol
        google = {"q": query, "hl": "pt-BR", "gl": "BR", "ceid": "BR:pt-419"}
    jobs = [(GOOGLE_URL, google, lambda b: parse_google_rss(b.decode("utf-8", errors="replace")))]
    if market == "US":
        jobs.append((YAHOO_URL, {"q": symbol, "newsCount": 10, "quotesCount": 0}, _parse_yahoo_body))

    async def one(client, url, params, parse):
        return parse(await _get(client, url, params))

    async with httpx.AsyncClient(transport=transport, timeout=15, headers=HEADERS) as client:
        results = await asyncio.gather(*(one(client, *j) for j in jobs), return_exceptions=True)
    good = [r for r in results if isinstance(r, list)]  # uma fonte fora do ar não impede a outra
    if not good:
        raise NewsError("todas as fontes de notícias falharam")
    return merge([i for r in good for i in r])


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
    except Exception:  # nenhuma falha de rede/parse chega ao chamador
        return {"items": cached, "fetched_at": fetched_at, "stale": True}
    if not items and cached:  # busca "ok" porém vazia não apaga cache bom
        return {"items": cached, "fetched_at": fetched_at, "stale": True}
    db.replace_news(conn, asset["id"], items)
    cached, fetched_at = db.load_news(conn, asset["id"])
    return {"items": cached, "fetched_at": fetched_at, "stale": False}
