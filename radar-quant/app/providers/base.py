"""Contrato comum dos provedores de candles diários."""
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class Candle:
    date: str  # "YYYY-MM-DD"
    open: float
    high: float
    low: float
    close: float
    volume: float


class ProviderError(Exception):
    """Falha ao obter dados de um provedor."""


class UnknownSymbol(ProviderError):
    """Símbolo não existe no provedor."""


class Provider(Protocol):
    async def fetch_daily(self, symbol: str, market: str) -> list[Candle]: ...
