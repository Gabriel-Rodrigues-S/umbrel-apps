"""Provedor Yahoo Finance (B3 e EUA)."""
from datetime import datetime, timedelta, timezone

import httpx

from .base import Candle, ProviderError, UnknownSymbol

URL = "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
                         "Chrome/124.0 Safari/537.36"}


class YahooProvider:
    def __init__(self, transport: httpx.AsyncBaseTransport | None = None):
        self._transport = transport

    async def fetch_daily(self, symbol: str, market: str) -> list[Candle]:
        ticker = f"{symbol}.SA" if market == "B3" else symbol
        params = {"range": "10y", "interval": "1d", "events": "div,splits"}
        try:
            async with httpx.AsyncClient(transport=self._transport, timeout=20, headers=HEADERS) as client:
                resp = await client.get(URL.format(ticker=ticker), params=params)
        except httpx.HTTPError as e:
            raise ProviderError(f"Yahoo indisponível: {e}") from e
        if resp.status_code == 404:
            raise UnknownSymbol(symbol)
        try:
            body = resp.json()
        except ValueError:
            body = None
        chart = body.get("chart") if isinstance(body, dict) else None
        if not isinstance(chart, dict):
            raise ProviderError(f"Yahoo: resposta inválida (HTTP {resp.status_code})")
        err = chart.get("error")
        if err and err.get("code") == "Not Found":
            raise UnknownSymbol(symbol)
        if resp.status_code != 200 or err or not chart.get("result"):
            raise ProviderError(f"Yahoo: erro (HTTP {resp.status_code}) {err or ''}".strip())
        return self._parse(chart["result"][0], symbol)

    @staticmethod
    def _parse(result: dict, symbol: str) -> list[Candle]:
        try:
            offset = timedelta(seconds=result["meta"].get("gmtoffset") or 0)
            q = result["indicators"]["quote"][0]
            adj = result["indicators"]["adjclose"][0]["adjclose"]
            stamps = result["timestamp"]
            rows = zip(stamps, q["open"], q["high"], q["low"], q["close"], adj, q["volume"])
        except (KeyError, IndexError, TypeError) as e:
            raise ProviderError(f"Yahoo: formato inesperado: {e!r}") from e
        by_date: dict[str, Candle] = {}  # datas duplicadas: fica a última
        for ts, o, h, l, c, a, v in rows:
            if None in (o, h, l, c, a) or not c:
                continue
            day = (datetime.fromtimestamp(ts, timezone.utc) + offset).strftime("%Y-%m-%d")
            f = a / c
            by_date[day] = Candle(day, o * f, h * f, l * f, a, v or 0)
        if not by_date:
            raise ProviderError(f"Yahoo: sem candles válidos para {symbol}")
        return sorted(by_date.values(), key=lambda x: x.date)
