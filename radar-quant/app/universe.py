"""Mantém atualizados os papéis dos índices (IBOV, IBRA, SP500, NDX) em segundo plano, devagar."""
import asyncio
import logging
from datetime import datetime, timedelta, timezone

from app import analysis, db, screener, service
from app.providers.base import UnknownSymbol

log = logging.getLogger("radar.universe")

STALE_HOURS = 20
MAX_FAILS = 5  # falhas seguidas que abortam a passada
PURGE_DAYS = 30
WINDOW = range(5, 9)  # horas UTC (madrugada em Manaus)
META_KEY = "universe_refreshed_at"


def _utc(dt: datetime) -> datetime:
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def _member_keys(conn) -> set[tuple[str, str]]:
    return {(m["symbol"], m["market"]) for m in db.index_members(conn)}


def ensure_assets(conn) -> int:
    """Cria (watch=0) os ativos dos membros de índice que ainda não existem."""
    created = 0
    for symbol, market in sorted(_member_keys(conn)):
        if db.find_asset(conn, symbol, market) is None:
            try:
                db.add_asset(conn, symbol, market, watch=False)
                created += 1
            except db.DuplicateAsset:  # criado em paralelo por outra rotina
                pass
    return created


def universe_due(conn, now: datetime) -> bool:
    """Nunca rodou, ou última passada completa há mais de STALE_HOURS e estamos na janela da madrugada."""
    try:
        last = _utc(datetime.fromisoformat(db.get_meta(conn, META_KEY) or ""))
    except ValueError:
        return True
    now = _utc(now)
    return now - last > timedelta(hours=STALE_HOURS) and now.hour in WINDOW


def _stale(asset: dict, now: datetime) -> bool:
    try:
        last = _utc(datetime.fromisoformat(asset["last_refresh"] or ""))
    except ValueError:
        return True
    return now - last > timedelta(hours=STALE_HOURS)


async def _refresh_one(conn, asset: dict, settings) -> bool:
    """Atualiza um ativo e regrava a linha do screener; False se a fonte falhou."""
    try:
        await service.refresh_asset(conn, asset, settings)
    except UnknownSymbol:
        return False
    except Exception as e:  # noqa: BLE001 - um ativo ruim não derruba a passada
        log.warning("falha inesperada em %s: %s", asset["symbol"], e)
        db.set_refresh_status(conn, asset["id"], f"erro inesperado: {e}")
        return False
    if (db.get_asset(conn, asset["id"]) or {}).get("last_error") is not None:
        return False
    analysis.invalidate(asset["id"])
    try:
        await asyncio.to_thread(screener.store_row, conn, asset | (db.get_asset(conn, asset["id"]) or {}))
    except Exception as e:  # noqa: BLE001 - os candles já foram gravados
        log.warning("falha ao gravar a linha do screener de %s: %s", asset["symbol"], e)
    return True


async def refresh_universe(conn, settings, pace: float | None = None, limit: int | None = None,
                           sleep=asyncio.sleep) -> dict:
    """Uma passada pelos ativos de índice desatualizados. `limit` corta a passada (que então é parcial)."""
    pace = settings.universe_pace if pace is None else pace
    ensure_assets(conn)
    keys = _member_keys(conn)
    assets = [a for a in db.list_assets(conn, watch=None) if (a["symbol"], a["market"]) in keys]
    now = datetime.now(timezone.utc)
    out = {"updated": 0, "skipped": 0, "failed": 0, "aborted": False}
    log.info("passada do universo: %d ativos", len(assets))
    streak, partial, first = 0, False, True
    for asset in assets:
        if not _stale(asset, now):
            out["skipped"] += 1
            continue
        if limit is not None and out["updated"] + out["failed"] >= limit:
            partial = True
            break
        if not first:
            await sleep(pace)
        first = False
        if await _refresh_one(conn, asset, settings):
            out["updated"] += 1
            streak = 0
            continue
        out["failed"] += 1
        streak += 1
        if streak >= MAX_FAILS:
            out["aborted"] = True
            log.warning("passada do universo abortada após %d falhas seguidas", streak)
            break
    if not out["aborted"] and not partial:
        db.set_meta(conn, META_KEY, datetime.now(timezone.utc).isoformat())
    log.info("passada do universo concluída: %s%s", out, " (parcial)" if partial else "")
    return out


def purge(conn, now: datetime) -> int:
    """Apaga os visitados fora de índice sem visita nos últimos PURGE_DAYS dias."""
    keys = _member_keys(conn)
    keep = {a["id"] for a in db.list_assets(conn, watch=None) if (a["symbol"], a["market"]) in keys}
    return db.purge_viewed(conn, (_utc(now) - timedelta(days=PURGE_DAYS)).isoformat(), keep)
