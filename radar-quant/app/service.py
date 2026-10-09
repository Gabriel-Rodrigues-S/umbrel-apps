"""Serviço de dados: atualização a partir dos provedores e leitura de séries."""
import asyncio
import logging
import threading
import time
from datetime import datetime, timezone

import pandas as pd

from app import db
from app.config import DEFAULT_WATCHLIST, INTRADAY, INTRADAY_SECONDS, Settings, normalize_symbol
from app.providers.base import Bar, ProviderError, UnknownSymbol
from app.providers.registry import fetch_rf_rates, get_provider

log = logging.getLogger("radar.service")

_RESAMPLE_RULE = {"1wk": "W-FRI", "1mo": "ME"}
_CIVIL_PERIOD = {"3mo": lambda i: i.year * 10 + (i.month - 1) // 3, "6mo": lambda i: i.year * 10 + (i.month - 1) // 6,
                 "1y": lambda i: i.year}  # trimestre, semestre e ano civis
_AGG = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}


def seed_watchlist(conn) -> None:
    """Cria a watchlist padrão, mas só se ainda não houver ativos."""
    if db.list_assets(conn):
        return
    for symbol, market in DEFAULT_WATCHLIST:
        db.add_asset(conn, symbol, market)


async def refresh_asset(conn, asset: dict, settings: Settings, provider=None) -> None:
    """Busca e grava a janela de candles (descartando o histórico anterior a ela).

    Em falha, mantém os candles antigos e registra o erro.
    """
    provider = provider or get_provider(asset["market"], settings)
    try:
        candles = await provider.fetch_daily(asset["symbol"], asset["market"])
    except UnknownSymbol:
        db.set_refresh_status(conn, asset["id"], "símbolo não encontrado")
        raise
    except ProviderError as e:
        db.set_refresh_status(conn, asset["id"], str(e))
        return
    db.replace_candles(conn, asset["id"], candles)
    db.set_refresh_status(conn, asset["id"], None)


async def refresh_all(conn, settings: Settings) -> None:
    """Atualiza só a watchlist (os ativos de cache têm rotina própria)."""
    try:
        db.upsert_rf(conn, await fetch_rf_rates(settings))
    except Exception as e:  # taxa livre de risco é opcional
        log.warning("falha ao atualizar taxa livre de risco: %s", e)
    for asset in db.list_assets(conn, watch=True):
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


def resample_real_dates(df: pd.DataFrame, rule: str, how) -> pd.DataFrame:
    """Reamostra rotulando cada balde com a última data real contida nele.

    O rótulo padrão é o fim do período, que num balde parcial ainda não aconteceu.
    Baldes vazios ficam com data NaT e são descartados.
    """
    out = df.resample(rule).agg(how)
    out.index = pd.DatetimeIndex(df.index.to_series().resample(rule).max())
    return out[out.index.notna()]


def resample(df: pd.DataFrame, interval: str) -> pd.DataFrame:
    if interval == "1d":
        return df
    if interval in _CIVIL_PERIOD:
        if df.empty:
            return df
        grp = df.groupby(df.index.map(_CIVIL_PERIOD[interval]))
        out = grp.agg(_AGG)
        out.index = pd.DatetimeIndex(grp.apply(lambda g: g.index.max()))
        return out.dropna(subset=["close"])
    if interval not in _RESAMPLE_RULE:
        raise ValueError(f"intervalo inválido: {interval}")
    return resample_real_dates(df, _RESAMPLE_RULE[interval], _AGG).dropna(subset=["close"])


def load_rf_series(conn) -> pd.Series:
    rows = db.load_rf(conn)
    return pd.Series([r for _, r in rows], index=pd.DatetimeIndex(pd.to_datetime([d for d, _ in rows])),
                     dtype=float)


# ---------- abrir ativo fora da watchlist ----------

OPEN_STALE_HOURS = 6


def _stale(last_refresh: str | None) -> bool:
    if not last_refresh:
        return True
    age = datetime.now(timezone.utc) - datetime.fromisoformat(last_refresh)
    return age.total_seconds() > OPEN_STALE_HOURS * 3600


_open_locks: dict[tuple[str, str], list] = {}  # (símbolo, mercado) -> [lock, nº de interessados]


async def open_asset(conn, symbol: str, market: str, settings: Settings) -> dict:
    """Garante o ativo (criando com watch=0 se preciso), atualiza se faltar dado ou estiver velho e marca a visita.

    Falha num ativo criado nesta chamada não deixa nada gravado; sem candles no fim, levanta ProviderError.
    Aberturas simultâneas do mesmo símbolo são serializadas.
    """
    symbol = normalize_symbol(symbol, market)
    entry = _open_locks.setdefault((symbol, market), [asyncio.Lock(), 0])
    entry[1] += 1
    try:
        async with entry[0]:
            return await _open_locked(conn, symbol, market, settings)
    finally:
        entry[1] -= 1
        if entry[1] == 0:
            _open_locks.pop((symbol, market), None)


async def _open_locked(conn, symbol: str, market: str, settings: Settings) -> dict:
    asset = db.find_asset(conn, symbol, market)
    created = asset is None
    if created:
        asset = db.get_asset(conn, db.add_asset(conn, symbol, market, watch=False))
    if created or _stale(asset["last_refresh"]) or not db.load_candles(conn, asset["id"]):
        try:
            await refresh_asset(conn, asset, settings)
        except BaseException:  # inclui cancelamento: não deixar o ativo recém-criado órfão
            if created:
                db.delete_asset(conn, asset["id"])
            raise
        if not db.load_candles(conn, asset["id"]):
            error = (db.get_asset(conn, asset["id"]) or {}).get("last_error")
            if created:
                db.delete_asset(conn, asset["id"])
            raise ProviderError(error or "fonte sem dados")
    db.touch_viewed(conn, asset["id"])
    fresh = db.get_asset(conn, asset["id"])
    if fresh is None:  # apagado por outra rotina no meio
        raise ProviderError("ativo removido durante a abertura")
    return fresh


# ---------- intraday sob demanda ----------

_clock = time.monotonic  # trocável nos testes
_INTRADAY_TTL = {"1m": 55, "3m": 55, "5m": 120, "10m": 120, "30m": 300, "1h": 300}
_DERIVED = {"3m": "1m", "10m": "5m"}  # intervalos montados a partir de outro quando a fonte não os entrega
_CACHE_MAX = 64
_intraday_cache: dict[tuple[int, str], tuple[float, dict]] = {}  # chave -> (expira em, resultado)
_intraday_lock = threading.Lock()


def clear_intraday_cache() -> None:
    with _intraday_lock:
        _intraday_cache.clear()


def aggregate_bars(bars: list[Bar], seconds: int) -> list[Bar]:
    """Junta barras no piso do timestamp em múltiplos de `seconds` (barras em ordem crescente)."""
    out: list[Bar] = []
    for b in bars:
        t = b.time // seconds * seconds
        if out and out[-1].time == t:
            o = out[-1]
            out[-1] = Bar(t, o.open, max(o.high, b.high), min(o.low, b.low), b.close, o.volume + b.volume)
        else:
            out.append(Bar(t, b.open, b.high, b.low, b.close, b.volume))
    return out


async def load_intraday(asset: dict, interval: str, settings: Settings, provider=None) -> dict:
    """Barras intraday (nunca gravadas em disco) com cache curto em memória por (ativo, intervalo)."""
    if interval not in INTRADAY:
        raise ValueError(f"intervalo intraday inválido: {interval}")
    key = (asset["id"], interval)
    with _intraday_lock:
        hit = _intraday_cache.get(key)
    if hit and hit[0] > _clock():
        return hit[1]
    provider = provider or get_provider(asset["market"], settings)
    native = interval in provider.NATIVE_INTRADAY
    if not native and _DERIVED.get(interval) not in provider.NATIVE_INTRADAY:
        raise ProviderError("intervalo não suportado pela fonte")
    bars, delay = await provider.fetch_intraday(asset["symbol"], asset["market"],
                                                interval if native else _DERIVED[interval])
    if not native:
        bars = aggregate_bars(bars, INTRADAY_SECONDS[interval])
    result = {"bars": bars, "delay_minutes": delay, "fetched_at": datetime.now(timezone.utc).isoformat()}
    with _intraday_lock:
        _intraday_cache.pop(key, None)
        _intraday_cache[key] = (_clock() + _INTRADAY_TTL[interval], result)
        while len(_intraday_cache) > _CACHE_MAX:
            del _intraday_cache[next(iter(_intraday_cache))]  # a mais antiga
    return result
