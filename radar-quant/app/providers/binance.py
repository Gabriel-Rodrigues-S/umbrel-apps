"""Provedor Binance (cripto, pares USDT)."""
import math
import time
from datetime import datetime, timezone

import httpx

from .base import Bar, Candle, ProviderError, UnknownSymbol

HOSTS = ("https://api.binance.com", "https://data-api.binance.vision")
DAY_MS = 86_400_000
FALLBACK_STATUS = {403, 451}
INTRADAY_STEP = {"1m": 60, "3m": 180, "5m": 300, "30m": 1800, "1h": 3600}


class BinanceProvider:
    NATIVE_INTRADAY = frozenset(INTRADAY_STEP)

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
                try:
                    start = int(page[-1][0]) + DAY_MS
                except (ValueError, TypeError, IndexError, KeyError, OverflowError) as e:
                    raise ProviderError(f"Binance: página malformada: {e!r}") from e
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        candles = []
        try:
            for r in rows:
                day = datetime.fromtimestamp(r[0] / 1000, timezone.utc).strftime("%Y-%m-%d")
                if day == today:  # candle do dia corrente ainda está em formação
                    continue
                o, h, l, c, v = (float(x) for x in r[1:6])
                if not all(math.isfinite(x) for x in (o, h, l, c, v)) or min(o, h, l, c) <= 0:
                    continue
                candles.append(Candle(day, o, h, l, c, v))
        except (ValueError, TypeError, IndexError, KeyError, AttributeError, OverflowError, OSError) as e:
            raise ProviderError(f"Binance: formato inesperado: {e!r}") from e
        if not candles:
            raise ProviderError(f"Binance: sem candles para {symbol}")
        return candles

    async def fetch_intraday(self, symbol: str, market: str, interval: str) -> tuple[list[Bar], int | None]:
        if interval not in self.NATIVE_INTRADAY:
            raise ProviderError("intervalo não suportado")
        params = {"symbol": f"{symbol}USDT", "interval": interval, "limit": 1000}
        async with httpx.AsyncClient(transport=self._transport, timeout=20) as client:
            rows = await self._get(client, params, symbol)
        bars = []
        for r in rows:  # a barra em formação é mantida; linhas ruins são ignoradas
            try:
                o, h, l, c, v = (float(x) for x in r[1:6])
                t = int(r[0]) // 1000
            except (ValueError, TypeError, IndexError, KeyError, OverflowError):
                continue
            if all(math.isfinite(x) for x in (o, h, l, c, v)) and min(o, h, l, c) > 0:
                bars.append(Bar(t, o, h, l, c, v))
        if not bars:
            raise ProviderError(f"Binance: sem barras intraday para {symbol}")
        return bars, 0

    async def _page(self, client: httpx.AsyncClient, pair: str, start: int, symbol: str) -> list[list]:
        params = {"symbol": pair, "interval": "1d", "limit": 1000, "startTime": start}
        return await self._get(client, params, symbol)

    async def _get(self, client: httpx.AsyncClient, params: dict, symbol: str) -> list[list]:
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
