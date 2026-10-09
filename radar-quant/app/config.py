"""Configuração e constantes do Radar Quant."""
import os
import re
from dataclasses import dataclass
from pathlib import Path

MARKETS = ("B3", "US", "CRYPTO")
PERIODS_PER_YEAR = {"B3": 252, "US": 252, "CRYPTO": 365}
CURRENCY = {"B3": "BRL", "US": "USD", "CRYPTO": "USD"}
DEFAULT_WATCHLIST = [("PETR4", "B3"), ("VALE3", "B3"), ("ITUB4", "B3"), ("BBAS3", "B3"),
                     ("WEGE3", "B3"), ("BOVA11", "B3"),
                     ("AAPL", "US"), ("MSFT", "US"), ("NVDA", "US"), ("SPY", "US"), ("QQQ", "US"),
                     ("BTC", "CRYPTO"), ("ETH", "CRYPTO")]
# Letras, dígitos e a pontuação dos tickers reais (BRK.B, BRK-B, ^BVSP, EURUSD=X); até 20 caracteres.
# O símbolo vai para a URL do provedor: nada de barras, espaços ou caracteres de controle.
_SYMBOL_RE = re.compile(r"[A-Z0-9^][A-Z0-9.\-^=]{0,19}")


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    provider: str  # "live" | "synthetic"
    refresh_hours: float


def get_settings() -> Settings:
    """Lê o ambiente a cada chamada (facilita testes)."""
    return Settings(
        data_dir=Path(os.environ.get("RADAR_DATA_DIR", "/app/data")),
        provider=os.environ.get("RADAR_PROVIDER", "live"),
        refresh_hours=float(os.environ.get("RADAR_REFRESH_HOURS", "6")),
    )


def normalize_symbol(symbol: str, market: str) -> str:
    s = symbol.strip().upper()
    if market == "B3" and s.endswith(".SA"):
        s = s[:-3]
    elif market == "CRYPTO":
        for suf in ("USDT", "-USD"):
            if s.endswith(suf):
                s = s[: -len(suf)]
                break
    if not s:
        raise ValueError("símbolo vazio")
    if not _SYMBOL_RE.fullmatch(s):
        raise ValueError("símbolo inválido")
    return s
