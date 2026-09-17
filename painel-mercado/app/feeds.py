import json
import logging
import re
import time
from html import unescape
from pathlib import Path

import feedparser
import httpx

logger = logging.getLogger(__name__)

DATA_FILE = Path("/app/data/news_cache.json")

FEEDS = [
    {"url": "https://www.infomoney.com.br/feed/", "source": "InfoMoney", "default_cat": "acoes"},
    {"url": "https://br.investing.com/rss/forex.rss", "source": "Investing.com", "default_cat": "cambio"},
    {"url": "https://br.investing.com/rss/commodities.rss", "source": "Investing.com", "default_cat": "commodities"},
    {"url": "https://br.investing.com/rss/bonds.rss", "source": "Investing.com", "default_cat": "juros"},
    {"url": "https://br.investing.com/rss/market_overview.rss", "source": "Investing.com", "default_cat": "global"},
    {"url": "https://br.investing.com/rss/news_301.rss", "source": "Investing.com", "default_cat": "cripto"},
    {"url": "https://cointelegraph.com.br/rss", "source": "Cointelegraph Brasil", "default_cat": "cripto"},
    {"url": "https://www.cnbc.com/id/10000664/device/rss/rss.html", "source": "CNBC", "default_cat": "global"},
    {"url": "https://www.cnbc.com/id/100003114/device/rss/rss.html", "source": "CNBC", "default_cat": "global"},
    {"url": "https://br.tradingview.com/feed/", "source": "TradingView Brasil", "default_cat": "acoes"},
    {"url": "https://livecoins.com.br/feed/", "source": "Livecoins", "default_cat": "cripto"},
    {"url": "https://invezz.com/feed/", "source": "Invezz", "default_cat": "global"},
    {"url": "https://br.beincrypto.com/feed/", "source": "BeInCrypto Brasil", "default_cat": "cripto"},
]

CATEGORY_LABELS = {
    "acoes": "Ações & B3",
    "cambio": "Câmbio",
    "juros": "Juros & BC",
    "cripto": "Cripto",
    "commodities": "Commodities",
    "global": "Mercados globais",
}

CATEGORY_KEYWORDS = {
    "cripto": ["bitcoin", "cripto", "ethereum", " btc", "blockchain", "token", "altcoin",
               "binance", "xrp", "solana", "stablecoin", "web3", "criptomoeda"],
    "cambio": ["dólar", "dolar", "câmbio", "cambio", "usd/brl", "ptax", "euro",
               "moeda americana", "moeda norte-americana"],
    "juros": ["selic", "copom", "juros", "fed ", "federal reserve", "banco central",
              "fomc", "ipca", "inflação", "inflacao", "taxa básica", "taxa basica", "powell",
              "rate hike", "interest rate", "warsh"],
    "commodities": ["petróleo", "petroleo", "minério", "minerio", "ouro", "prata", "soja",
                     "milho", "café", "cafe", "commodity", "commodities", "brent", "opep", "wti",
                     "gold", "oil", "silver"],
    "acoes": ["ação", "acao", "ações", "acoes", "bolsa", "ibovespa", "b3 ", "lucro",
              "balanço", "balanco", "dividendo", "ipo", "petrobras", "vale ", "itaú",
              "itau", "bradesco", "ações", "stock", "earnings", "nyse", "nasdaq:"],
    "global": ["wall street", "s&p", "nasdaq", "dow jones", "fmi", "china", "europa",
               "bce", "zona do euro", "estados unidos", "tariff", "trump", "trade war",
               "white house", "sanctions"],
}

EXCLUDE_KEYWORDS = [
    "loteria", "lotofácil", "lotofacil", "lotomania", "mega-sena", "megasena",
    "quina", "dia de sorte", "timemania", "dupla sena", "concurso", "sorteio",
    "horóscopo", "horoscopo", "novela", "+mais lidas",
]

MAX_ITEMS_TOTAL = 90
MAX_ITEMS_PER_CATEGORY = 15
MAX_ITEMS_PER_CATEGORY_IN_ALL = 8
FETCH_TIMEOUT = 12
ENTRIES_PER_FEED = 20
CATEGORY_ORDER = list(CATEGORY_LABELS.keys())

_cache = {"items": [], "by_cat": {}, "updated": 0, "sources": []}


def _clean_text(raw):
    text = re.sub(r"<[^>]+>", " ", raw or "")
    text = unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _is_excluded(title):
    low = title.lower()
    return any(word in low for word in EXCLUDE_KEYWORDS)


def _classify(title, summary, default_cat):
    text = f"{title} {summary}".lower()
    best_cat, best_hits = default_cat, 0
    for cat, words in CATEGORY_KEYWORDS.items():
        hits = sum(1 for w in words if w in text)
        if hits > best_hits:
            best_cat, best_hits = cat, hits
    return best_cat


def _load_disk_cache():
    try:
        if DATA_FILE.exists():
            data = json.loads(DATA_FILE.read_text())
            _cache.update(data)
            logger.info("cache de notícias carregado do disco (%d itens)", len(_cache.get("items", [])))
    except Exception:
        logger.exception("falha ao carregar cache de notícias do disco")


def _save_disk_cache():
    try:
        DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
        DATA_FILE.write_text(json.dumps(_cache))
    except Exception:
        logger.exception("falha ao salvar cache de notícias no disco")


def fetch_all():
    items = []
    seen_titles = set()
    ok_sources = set()
    headers = {"User-Agent": "Mozilla/5.0 (compatible; PainelMercadoBot/1.0; +https://github.com/garod004/umbrel-apps)"}
    with httpx.Client(timeout=FETCH_TIMEOUT, headers=headers, follow_redirects=True) as client:
        for feed in FEEDS:
            try:
                resp = client.get(feed["url"])
                resp.raise_for_status()
                parsed = feedparser.parse(resp.content)
            except Exception as exc:
                logger.warning("falha ao buscar feed %s: %s", feed["url"], exc)
                continue
            got_any = False
            for entry in parsed.entries[:ENTRIES_PER_FEED]:
                title = _clean_text(getattr(entry, "title", ""))
                if not title or _is_excluded(title):
                    continue
                dedupe_key = title.lower()[:80]
                if dedupe_key in seen_titles:
                    continue
                seen_titles.add(dedupe_key)
                summary = _clean_text(getattr(entry, "summary", ""))[:300]
                link = getattr(entry, "link", "")
                published = getattr(entry, "published_parsed", None) or getattr(entry, "updated_parsed", None)
                ts = time.mktime(published) if published else time.time()
                category = _classify(title, summary, feed["default_cat"])
                items.append({
                    "title": title,
                    "summary": summary,
                    "link": link,
                    "source": feed["source"],
                    "category": category,
                    "ts": ts,
                })
                got_any = True
            if got_any:
                ok_sources.add(feed["source"])
    items.sort(key=lambda x: x["ts"], reverse=True)
    return items, sorted(ok_sources)


def _interleave_by_category(by_cat):
    """Mistura as categorias em rodízio para que nenhuma domine o topo da lista
    'Tudo' e todas fiquem visíveis sem precisar rolar até o fim."""
    lists = [by_cat.get(cat, [])[:MAX_ITEMS_PER_CATEGORY_IN_ALL] for cat in CATEGORY_ORDER]
    result = []
    round_idx = 0
    while True:
        added = False
        for lst in lists:
            if round_idx < len(lst):
                result.append(lst[round_idx])
                added = True
        if not added:
            break
        round_idx += 1
    return result


def refresh():
    items, ok_sources = fetch_all()
    if not items:
        logger.warning("nenhuma notícia obtida nesta atualização; mantendo cache anterior")
        return
    by_cat = {}
    for it in items:
        by_cat.setdefault(it["category"], []).append(it)
    by_cat = {c: v[:MAX_ITEMS_PER_CATEGORY] for c, v in by_cat.items()}
    _cache["items"] = _interleave_by_category(by_cat)[:MAX_ITEMS_TOTAL]
    _cache["by_cat"] = by_cat
    _cache["updated"] = time.time()
    _cache["sources"] = ok_sources
    _save_disk_cache()
    logger.info("notícias atualizadas: %d itens de %s", len(items), ok_sources)


def get_cache():
    return _cache


_load_disk_cache()
