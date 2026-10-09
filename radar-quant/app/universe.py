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
ATTEMPT_KEY = "universe_attempt_at"  # início da última passada, completa ou não
RETRY_HOURS = 2  # espera mínima após qualquer tentativa (evita martelar a fonte depois de um aborto)


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
    """Nunca rodou, ou última passada completa há mais de STALE_HOURS e estamos na janela da madrugada.

    Nunca antes de RETRY_HOURS desde a última tentativa, qualquer que seja o resultado dela,
    e nunca sem membros de índice no catálogo (ele ainda não chegou)."""
    if not db.index_members(conn):
        return False
    now = _utc(now)
    try:
        if now - _utc(datetime.fromisoformat(db.get_meta(conn, ATTEMPT_KEY) or "")) < timedelta(hours=RETRY_HOURS):
            return False
    except ValueError:
        pass
    try:
        last = _utc(datetime.fromisoformat(db.get_meta(conn, META_KEY) or ""))
    except ValueError:
        return True
    return now - last > timedelta(hours=STALE_HOURS) and now.hour in WINDOW


def _stale(asset: dict, now: datetime) -> bool:
    try:
        last = _utc(datetime.fromisoformat(asset["last_refresh"] or ""))
    except ValueError:
        return True
    return now - last > timedelta(hours=STALE_HOURS)


def _universe_assets(conn) -> list[dict]:
    keys = _member_keys(conn)
    return [a for a in db.list_assets(conn, watch=None) if (a["symbol"], a["market"]) in keys]


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
    except Exception as e:  # noqa: BLE001
        log.warning("falha ao gravar a linha do screener de %s: %s", asset["symbol"], e)
        return False
    return True


async def refresh_universe(conn, settings, pace: float | None = None, limit: int | None = None,
                           sleep=asyncio.sleep) -> dict:
    """Uma passada pelos ativos de índice desatualizados. `limit` corta a passada (que então é parcial)."""
    pace = settings.universe_pace if pace is None else pace
    if not await asyncio.to_thread(db.index_members, conn):
        log.info("catálogo sem membros de índice: passada adiada")
        return {"updated": 0, "skipped": 0, "failed": 0, "aborted": False}
    now = datetime.now(timezone.utc)
    db.set_meta(conn, ATTEMPT_KEY, now.isoformat())
    # centenas de commits e leituras: fora do event loop
    await asyncio.to_thread(ensure_assets, conn)
    assets = await asyncio.to_thread(_universe_assets, conn)
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
    if not out["aborted"] and not partial and out["updated"] + out["skipped"] > 0:
        db.set_meta(conn, META_KEY, datetime.now(timezone.utc).isoformat())
    log.info("passada do universo concluída: %s%s", out, " (parcial)" if partial else "")
    return out


def purge(conn, now: datetime) -> int:
    """Apaga os visitados fora de índice sem visita nos últimos PURGE_DAYS dias."""
    keys = _member_keys(conn)
    if not keys:  # catálogo momentaneamente vazio não pode levar à limpeza dos ativos de índice
        return 0
    keep = {a["id"] for a in db.list_assets(conn, watch=None) if (a["symbol"], a["market"]) in keys}
    return db.purge_viewed(conn, (_utc(now) - timedelta(days=PURGE_DAYS)).isoformat(), keep)


async def purge_async(conn, now: datetime) -> int:
    """`purge` fora do event loop (para o laço assíncrono do servidor)."""
    return await asyncio.to_thread(purge, conn, now)
