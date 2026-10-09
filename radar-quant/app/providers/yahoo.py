"""Provedor Yahoo Finance (B3 e EUA)."""
import asyncio
import math
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import httpx

from .base import Bar, Candle, ProviderError, UnknownSymbol

URL = "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
# UA de navegador completo recebe HTTP 429 do Yahoo; este é aceito.
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; RadarQuantBot/1.0)"}
# intervalo do gráfico -> (interval, range) do Yahoo
INTRADAY_PARAMS = {"1m": ("1m", "7d"), "5m": ("5m", "60d"), "30m": ("30m", "60d"), "1h": ("60m", "730d")}


def _volume(v) -> float:
    """Volume como float; não numérico ou não finito vira 0.0."""
    try:
        x = float(v)
    except (ValueError, TypeError):
        return 0.0
    return x if math.isfinite(x) else 0.0


class YahooProvider:
    def __init__(self, transport: httpx.AsyncBaseTransport | None = None, retry_delay: float = 1.5):
        self._transport = transport
        self._retry_delay = retry_delay  # esperas: delay, 2*delay (até 2 retentativas)

    NATIVE_INTRADAY = frozenset(INTRADAY_PARAMS)

    async def fetch_daily(self, symbol: str, market: str) -> list[Candle]:
        params = {"range": "10y", "interval": "1d", "events": "div,splits"}
        return self._parse(await self._chart(symbol, market, params), symbol)

    async def fetch_intraday(self, symbol: str, market: str, interval: str) -> tuple[list[Bar], int | None]:
        if interval not in INTRADAY_PARAMS:
            raise ProviderError("intervalo não suportado")
        yi, rng = INTRADAY_PARAMS[interval]
        result = await self._chart(symbol, market, {"range": rng, "interval": yi})
        return self._parse_intraday(result), self._delay(result)

    async def _chart(self, symbol: str, market: str, params: dict) -> dict:
        """Baixa o gráfico (com retentativa) e devolve `chart.result[0]`."""
        # B3 ganha sufixo .SA; nos EUA o Yahoo usa hífen onde a bolsa usa ponto (BRK.B -> BRK-B)
        ticker = f"{symbol}.SA" if market == "B3" else symbol.replace(".", "-") if market == "US" else symbol
        url = URL.format(ticker=quote(ticker, safe=""))  # o ticker é um único segmento do caminho
        try:
            async with httpx.AsyncClient(transport=self._transport, timeout=20, headers=HEADERS) as client:
                for attempt in range(3):
                    resp = await client.get(url, params=params)
                    if (resp.status_code != 429 and resp.status_code < 500) or attempt == 2:
                        break
                    await asyncio.sleep(self._retry_delay * (attempt + 1))
        except httpx.InvalidURL as e:  # não é subclasse de httpx.HTTPError
            raise ProviderError(f"Yahoo: URL inválida: {e}") from e
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
        if isinstance(err, dict) and err.get("code") == "Not Found":
            raise UnknownSymbol(symbol)
        result = chart.get("result")
        if resp.status_code != 200 or err or not isinstance(result, list) or not result \
                or not isinstance(result[0], dict):
            raise ProviderError(f"Yahoo: erro (HTTP {resp.status_code}) {err or ''}".strip())
        return result[0]

    @staticmethod
    def _parse(result: dict, symbol: str) -> list[Candle]:
        by_date: dict[str, Candle] = {}  # datas duplicadas: fica a última
        try:
            offset = timedelta(seconds=result["meta"].get("gmtoffset") or 0)
            q = result["indicators"]["quote"][0]
            adj = result["indicators"]["adjclose"][0]["adjclose"]
            stamps = result["timestamp"]
            cols = (stamps, q["open"], q["high"], q["low"], q["close"], adj, q["volume"])
            if len({len(c) for c in cols}) != 1:
                raise ProviderError("Yahoo: séries com tamanhos diferentes")
            for ts, o, h, l, c, a, v in zip(*cols):
                if None in (o, h, l, c, a) or not all(math.isfinite(x) for x in (o, h, l, c, a)) \
                        or min(o, h, l, c, a) <= 0:
                    continue
                day = (datetime.fromtimestamp(ts, timezone.utc) + offset).strftime("%Y-%m-%d")
                f = a / c
                by_date[day] = Candle(day, o * f, h * f, l * f, a, _volume(v))
        except (ValueError, TypeError, IndexError, KeyError, AttributeError, OverflowError, OSError) as e:
            raise ProviderError(f"Yahoo: formato inesperado: {e!r}") from e
        if not by_date:
            raise ProviderError(f"Yahoo: sem candles válidos para {symbol}")
        return sorted(by_date.values(), key=lambda x: x.date)

    @staticmethod
    def _delay(result: dict) -> int | None:
        """Atraso da cotação em minutos, se a fonte informar um número válido."""
        meta = result.get("meta")
        d = meta.get("exchangeDataDelayedBy") if isinstance(meta, dict) else None
        if isinstance(d, bool) or not isinstance(d, (int, float)) or not math.isfinite(d) or d < 0:
            return None
        return int(d)

    @staticmethod
    def _parse_intraday(result: dict) -> list[Bar]:
        bars: dict[int, Bar] = {}  # timestamps duplicados: fica a última
        try:
            q = result["indicators"]["quote"][0]
            cols = (result["timestamp"], q["open"], q["high"], q["low"], q["close"], q["volume"])
            if len({len(c) for c in cols}) != 1:
                raise ProviderError("Yahoo: séries com tamanhos diferentes")
            for ts, o, h, l, c, v in zip(*cols):
                if None in (o, h, l, c) or not all(math.isfinite(x) for x in (o, h, l, c)) \
                        or min(o, h, l, c) <= 0:
                    continue
                bars[int(ts)] = Bar(int(ts), o, h, l, c, _volume(v))
        except (ValueError, TypeError, IndexError, KeyError, AttributeError, OverflowError) as e:
            raise ProviderError(f"Yahoo: formato inesperado: {e!r}") from e
        if not bars:
            raise ProviderError("sem dados intraday")
        return [bars[t] for t in sorted(bars)]
