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


@dataclass(frozen=True)
class Bar:
    time: int  # epoch em segundos, UTC
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
    NATIVE_INTRADAY: frozenset[str]  # intervalos intradiários que a fonte entrega direto

    async def fetch_daily(self, symbol: str, market: str) -> list[Candle]: ...

    async def fetch_intraday(self, symbol: str, market: str, interval: str) -> tuple[list[Bar], int | None]:
        """Barras em ordem crescente e o atraso em minutos informado pela fonte (ou None)."""
        ...
