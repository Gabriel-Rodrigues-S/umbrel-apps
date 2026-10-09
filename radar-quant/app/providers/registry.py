"""Escolha do provedor conforme mercado e configuração."""
from ..config import MARKETS, Settings
from .base import Provider
from .bcb import fetch_cdi
from .binance import BinanceProvider
from .synthetic import SyntheticProvider
from .yahoo import YahooProvider


def get_provider(market: str, settings: Settings) -> Provider:
    if market not in MARKETS:
        raise ValueError(f"mercado inválido: {market}")
    if settings.provider == "synthetic":
        return SyntheticProvider()
    return BinanceProvider() if market == "CRYPTO" else YahooProvider()


async def fetch_rf_rates(settings: Settings) -> list[tuple[str, float]]:
    """Taxa livre de risco diária (CDI); vazia no modo sintético."""
    return [] if settings.provider == "synthetic" else await fetch_cdi()
