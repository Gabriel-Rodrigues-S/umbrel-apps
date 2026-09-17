import json
import logging
import time
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

DATA_FILE = Path("/app/data/quotes_cache.json")

YAHOO_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
SELIC_URL = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.432/dados/ultimos/1?formato=json"
FETCH_TIMEOUT = 10

TICKERS = [
    {"key": "ibov", "label": "Ibovespa", "symbol": "%5EBVSP"},
    {"key": "sp500", "label": "S&P 500", "symbol": "%5EGSPC"},
    {"key": "nasdaq", "label": "Nasdaq", "symbol": "%5EIXIC"},
    {"key": "usdbrl", "label": "USD/BRL", "symbol": "BRL=X"},
    {"key": "eurusd", "label": "EUR/USD", "symbol": "EURUSD=X"},
    {"key": "btc", "label": "Bitcoin", "symbol": "BTC-USD"},
    {"key": "eth", "label": "Ethereum", "symbol": "ETH-USD"},
    {"key": "wti", "label": "Petróleo (WTI)", "symbol": "CL=F"},
    {"key": "gold", "label": "Ouro", "symbol": "GC=F"},
]

_cache = {"quotes": {}, "updated": 0}


def _load_disk_cache():
    try:
        if DATA_FILE.exists():
            data = json.loads(DATA_FILE.read_text())
            _cache.update(data)
            logger.info("cache de cotações carregado do disco (%d itens)", len(_cache.get("quotes", {})))
    except Exception:
        logger.exception("falha ao carregar cache de cotações do disco")


def _save_disk_cache():
    try:
        DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
        DATA_FILE.write_text(json.dumps(_cache))
    except Exception:
        logger.exception("falha ao salvar cache de cotações no disco")


def _fetch_symbol(client, symbol):
    resp = client.get(YAHOO_URL.format(symbol=symbol), params={"interval": "1d", "range": "1d"})
    resp.raise_for_status()
    meta = resp.json()["chart"]["result"][0]["meta"]
    return {
        "price": meta.get("regularMarketPrice"),
        "change_pct": meta.get("regularMarketChangePercent"),
        "currency": meta.get("currency"),
    }


def _fetch_selic(client):
    resp = client.get(SELIC_URL)
    resp.raise_for_status()
    data = resp.json()
    if data:
        return float(data[0]["valor"].replace(",", "."))
    return None


def refresh():
    quotes = {}
    headers = {"User-Agent": "Mozilla/5.0 (compatible; PainelMercadoBot/1.0)"}
    with httpx.Client(timeout=FETCH_TIMEOUT, headers=headers) as client:
        for t in TICKERS:
            try:
                quotes[t["key"]] = {"label": t["label"], **_fetch_symbol(client, t["symbol"])}
            except Exception as exc:
                logger.warning("falha ao buscar cotação %s: %s", t["key"], exc)
        try:
            selic = _fetch_selic(client)
            if selic is not None:
                quotes["selic"] = {"label": "Selic", "price": selic, "change_pct": None, "currency": "%"}
        except Exception as exc:
            logger.warning("falha ao buscar Selic: %s", exc)
    if quotes:
        _cache["quotes"] = quotes
        _cache["updated"] = time.time()
        _save_disk_cache()
        logger.info("cotações atualizadas: %s", ", ".join(quotes.keys()))
    else:
        logger.warning("nenhuma cotação obtida nesta atualização; mantendo cache anterior")


def get_cache():
    return _cache


_load_disk_cache()
