"""Provedor Binance (cripto, pares USDT)."""
import time
from datetime import datetime, timezone

import httpx

from .base import Candle, ProviderError, UnknownSymbol

HOSTS = ("https://api.binance.com", "https://data-api.binance.vision")
DAY_MS = 86_400_000
FALLBACK_STATUS = {403, 451}


class BinanceProvider:
    def __init__(self, transport: httpx.AsyncBaseTransport | None = None):
        self._transport = transport

    async def fetch_daily(self, symbol: str, market: str) -> list[Candle]:
        pair = f"{symbol}USDT"
        start = int(time.time() * 1000) - 3000 * DAY_MS
        rows: list[list] = []
        async with httpx.AsyncClient(transport=self._transport, timeout=20) as client:
            for _ in range(3):
                page = await self._page(client, pair, start, symbol)
                rows += page
                if len(page) < 1000:
                    break
                start = page[-1][0] + DAY_MS
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        candles = []
        for r in rows:
            day = datetime.fromtimestamp(r[0] / 1000, timezone.utc).strftime("%Y-%m-%d")
            if day == today:  # candle do dia corrente ainda está em formação
                continue
            candles.append(Candle(day, float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])))
        if not candles:
            raise ProviderError(f"Binance: sem candles para {symbol}")
        return candles

    async def _page(self, client: httpx.AsyncClient, pair: str, start: int, symbol: str) -> list[list]:
        params = {"symbol": pair, "interval": "1d", "limit": 1000, "startTime": start}
        last = "sem resposta"
        for host in HOSTS:
            try:
                resp = await client.get(f"{host}/api/v3/klines", params=params)
            except httpx.HTTPError as e:
                last = str(e)
                continue
            if resp.status_code >= 500 or resp.status_code in FALLBACK_STATUS:
                last = f"HTTP {resp.status_code}"
                continue
            try:
                body = resp.json()
            except ValueError:
                raise ProviderError("Binance: resposta não é JSON") from None
            if resp.status_code == 400 and isinstance(body, dict) and body.get("code") == -1121:
                raise UnknownSymbol(symbol)
            if resp.status_code != 200 or not isinstance(body, list):
                raise ProviderError(f"Binance: erro HTTP {resp.status_code}")
            return body
        raise ProviderError(f"Binance indisponível: {last}")
