"""Provedor sintético determinístico (testes e modo offline)."""
import zlib

import numpy as np
import pandas as pd

from .base import Bar, Candle, ProviderError, UnknownSymbol

END = "2026-10-07"
N = 1500
INTRADAY_END = 1791403200  # 2026-10-07T20:00:00Z
# intervalo -> (segundos por barra, nº de barras)
INTRADAY = {"1m": (60, 1500), "3m": (180, 1000), "5m": (300, 1500), "30m": (1800, 700), "1h": (3600, 900)}


def _check(symbol: str) -> None:
    if symbol.startswith("INVALID"):
        raise UnknownSymbol(symbol)
    if symbol.startswith("FALHA"):
        raise ProviderError("fonte indisponível")


class SyntheticProvider:
    NATIVE_INTRADAY = frozenset(INTRADAY)

    async def fetch_intraday(self, symbol: str, market: str, interval: str) -> tuple[list[Bar], int | None]:
        _check(symbol)
        if interval not in INTRADAY:
            raise ProviderError("intervalo não suportado")
        step, n = INTRADAY[interval]
        rng = np.random.default_rng(zlib.crc32(f"{market}:{symbol}:{interval}".encode()))
        closes = 50 * np.exp(np.cumsum(rng.normal(0, 0.002, n)))
        opens = np.concatenate(([50.0], closes[:-1]))
        highs = np.maximum(opens, closes) * (1 + np.abs(rng.normal(0, 0.001, n)))
        lows = np.minimum(opens, closes) * (1 - np.abs(rng.normal(0, 0.001, n)))
        vols = rng.integers(1_000, 50_000, n)
        times = INTRADAY_END - step * np.arange(n - 1, -1, -1)
        bars = [Bar(int(t), float(o), float(h), float(l), float(c), float(v))
                for t, o, h, l, c, v in zip(times, opens, highs, lows, closes, vols)]
        return (bars[-50:] if symbol.startswith("CURTO") else bars), None

    async def fetch_daily(self, symbol: str, market: str) -> list[Candle]:
        _check(symbol)
        seed = zlib.crc32(f"{market}:{symbol}".encode())
        mu = -0.0002 + (seed % 1000) / 1000 * 0.0010
        sigma = 0.012 + (seed % 7) * 0.002
        rng = np.random.default_rng(seed)
        dates = pd.bdate_range(end=END, periods=N)
        closes = 50 * np.exp(np.cumsum(rng.normal(mu - sigma**2 / 2, sigma, N)))
        opens = np.concatenate(([50.0], closes[:-1]))
        highs = np.maximum(opens, closes) * (1 + np.abs(rng.normal(0, 0.005, N)))
        lows = np.minimum(opens, closes) * (1 - np.abs(rng.normal(0, 0.005, N)))
        vols = rng.integers(100_000, 5_000_000, N)
        candles = [Candle(d.strftime("%Y-%m-%d"), float(o), float(h), float(l), float(c), float(v))
                   for d, o, h, l, c, v in zip(dates, opens, highs, lows, closes, vols)]
        return candles[-100:] if symbol.startswith("CURTO") else candles
