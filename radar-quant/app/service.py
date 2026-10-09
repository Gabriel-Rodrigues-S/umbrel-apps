"""Serviço de dados: atualização a partir dos provedores e leitura de séries."""
import logging

import pandas as pd

from app import db
from app.config import DEFAULT_WATCHLIST, Settings
from app.providers.base import ProviderError, UnknownSymbol
from app.providers.registry import fetch_rf_rates, get_provider

log = logging.getLogger("radar.service")

_RESAMPLE_RULE = {"1wk": "W-FRI", "1mo": "ME"}
_AGG = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}


def seed_watchlist(conn) -> None:
    """Cria a watchlist padrão, mas só se ainda não houver ativos."""
    if db.list_assets(conn):
        return
    for symbol, market in DEFAULT_WATCHLIST:
        db.add_asset(conn, symbol, market)


async def refresh_asset(conn, asset: dict, settings: Settings, provider=None) -> None:
    """Busca e grava os candles. Em falha, mantém os candles antigos e registra o erro."""
    provider = provider or get_provider(asset["market"], settings)
    try:
        candles = await provider.fetch_daily(asset["symbol"], asset["market"])
    except UnknownSymbol as e:
        db.set_refresh_status(conn, asset["id"], str(e))
        raise
    except ProviderError as e:
        db.set_refresh_status(conn, asset["id"], str(e))
        return
    db.upsert_candles(conn, asset["id"], candles)
    db.set_refresh_status(conn, asset["id"], None)


async def refresh_all(conn, settings: Settings) -> None:
    try:
        db.upsert_rf(conn, await fetch_rf_rates(settings))
    except Exception as e:  # taxa livre de risco é opcional
        log.warning("falha ao atualizar taxa livre de risco: %s", e)
    for asset in db.list_assets(conn):
        try:
            await refresh_asset(conn, asset, settings)
        except Exception as e:  # um ativo ruim não interrompe os demais
            log.warning("falha ao atualizar %s: %s", asset["symbol"], e)
            if not isinstance(e, UnknownSymbol):
                db.set_refresh_status(conn, asset["id"], f"erro inesperado: {e}")


def load_frame(conn, asset_id: int) -> pd.DataFrame:
    rows = db.load_candles(conn, asset_id)
    df = pd.DataFrame([tuple(r) for r in rows],
                      columns=["asset_id", "date", "open", "high", "low", "close", "volume"])
    df.index = pd.DatetimeIndex(pd.to_datetime(df.pop("date")))
    return df.drop(columns="asset_id").astype(float)


def resample(df: pd.DataFrame, interval: str) -> pd.DataFrame:
    if interval == "1d":
        return df
    if interval not in _RESAMPLE_RULE:
        raise ValueError(f"intervalo inválido: {interval}")
    return df.resample(_RESAMPLE_RULE[interval]).agg(_AGG).dropna(subset=["close"])


def load_rf_series(conn) -> pd.Series:
    rows = db.load_rf(conn)
    return pd.Series([r for _, r in rows], index=pd.DatetimeIndex(pd.to_datetime([d for d, _ in rows])),
                     dtype=float)
