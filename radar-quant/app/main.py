"""API FastAPI do Radar Quant: rotas, refresh em segundo plano e arquivos estáticos."""
import asyncio
import logging
import os
from datetime import datetime, timezone
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Literal

from fastapi import FastAPI, HTTPException, Path as PathParam, Query, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app import analysis, catalog, db, names, news, screener, search, service, universe
from app.config import INTERVALS, INTRADAY, MARKETS, get_settings, normalize_symbol
from app.providers.base import ProviderError, UnknownSymbol
from app.stats.portfolio import PortfolioError

log = logging.getLogger("radar")
STATIC = Path(__file__).parent / "static"
RETRY_SECONDS = 600  # nova tentativa quando algum ativo ficou com erro
MAX_SHORT_RETRIES = 3  # esperas curtas seguidas; depois volta ao intervalo normal
UNIVERSE_CHECK_SECONDS = 600  # de quanto em quanto tempo o laço do universo olha se há passada devida
UNIVERSE_WAIT_SECONDS = 60  # idem, enquanto o catálogo ainda não tem membros de índice
AssetId = Annotated[int, PathParam(ge=1, le=2**63 - 1)]  # faixa do INTEGER do SQLite
Interval = Literal[INTERVALS]  # os doze intervalos do gráfico
Short = Annotated[str, Query(max_length=32)]  # filtros de texto do screener


class NewAsset(BaseModel):
    symbol: str = Field(max_length=32)
    market: str = Field(max_length=8)


def store_rows(conn, assets: list[dict]) -> None:
    """Grava a linha do screener de cada ativo; um ativo ruim não impede os demais."""
    for a in assets:
        try:
            screener.store_row(conn, a)
        except Exception:
            log.exception("falha ao gravar a linha do screener de %s", a["symbol"])


async def refresh_everything(app: FastAPI) -> None:
    """Refresh geral; nunca roda dois ao mesmo tempo."""
    async with app.state.refresh_lock:
        await service.refresh_all(app.state.conn, app.state.settings)
        analysis.invalidate()
        await asyncio.to_thread(store_rows, app.state.conn, db.list_assets(app.state.conn))


async def refresh_catalog_safely(app: FastAPI) -> None:
    """Atualiza o catálogo se estiver velho; erros são só registrados."""
    try:
        if catalog.catalog_is_stale(app.state.conn):
            result = await catalog.refresh_catalog(app.state.conn, app.state.settings)
            if result["errors"]:
                log.warning("catálogo atualizado com falhas: %s", result["errors"])
    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception("falha ao atualizar o catálogo")


async def refresh_safely(app: FastAPI) -> None:
    try:
        await refresh_everything(app)
    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception("falha no refresh em segundo plano")


async def learn_names_safely(app: FastAPI, symbols: list[str]) -> None:
    """Aprende o nome completo dos papéis da B3 ainda sem alias; pulado no modo sintético, erros só registrados."""
    if app.state.settings.provider == "synthetic" or not symbols:
        return
    try:
        await names.learn_names(app.state.conn, "B3", symbols)
    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception("falha ao aprender nomes de papéis")


def spawn(app: FastAPI, coro) -> None:
    """Tarefa em segundo plano, cancelada no encerramento junto com as demais."""
    task = asyncio.create_task(coro)
    app.state.tasks.add(task)
    task.add_done_callback(app.state.tasks.discard)


def next_sleep(has_errors: bool, short_retries: int, refresh_hours: float) -> tuple[float, int]:
    """(espera em segundos, novo contador de esperas curtas).

    Com ativo em erro (ex.: rede fora na subida) a espera é curta, mas só por
    MAX_SHORT_RETRIES vezes seguidas: um ticker morto não pode fazer a watchlist
    inteira ser buscada a cada 10 minutos para sempre. Refresh sem erro zera o contador.
    """
    normal = refresh_hours * 3600
    if not has_errors:
        return normal, 0
    if short_retries >= MAX_SHORT_RETRIES:
        return normal, short_retries
    return min(RETRY_SECONDS, normal), short_retries + 1


async def loop_refresh(app: FastAPI) -> None:
    short_retries = 0
    while True:
        await refresh_safely(app)
        await refresh_catalog_safely(app)
        assets = await asyncio.to_thread(db.list_assets, app.state.conn)
        await learn_names_safely(app, [a["symbol"] for a in assets if a["market"] == "B3"])
        has_errors = any(a["last_error"] for a in assets)
        seconds, short_retries = next_sleep(has_errors, short_retries, app.state.settings.refresh_hours)
        await asyncio.sleep(seconds)


async def loop_universe(app: FastAPI) -> None:
    """Passada diária pelos papéis dos índices; nunca derruba o app nem gira em falso."""
    while True:
        try:
            if await asyncio.to_thread(universe.universe_due, app.state.conn, datetime.now(timezone.utc)):
                await universe.refresh_universe(app.state.conn, app.state.settings)
                await universe.purge_async(app.state.conn, datetime.now(timezone.utc))  # agora, não o de antes da passada
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("falha na passada do universo")
        try:
            members = await asyncio.to_thread(db.index_members, app.state.conn)
        except Exception:
            members = []
        # a cada verificação (mesmo sem passada devida): 40 nomes por vez até não faltar nenhum
        await learn_names_safely(app, [m["symbol"] for m in members if m["market"] == "B3"])
        await asyncio.sleep(UNIVERSE_CHECK_SECONDS if members else UNIVERSE_WAIT_SECONDS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    app.state.settings = settings
    app.state.conn = db.connect(settings.data_dir / "radar.db")
    app.state.refresh_lock = asyncio.Lock()
    app.state.tasks = set()
    service.seed_watchlist(app.state.conn)
    if settings.provider == "synthetic" and db.catalog_count(app.state.conn) == 0:
        await catalog.refresh_catalog(app.state.conn, settings)  # testes e E2E; no modo live o laço busca
    if os.environ.get("RADAR_SKIP_BACKGROUND") != "1":
        app.state.tasks.add(asyncio.create_task(loop_refresh(app)))
        if settings.universe:
            app.state.tasks.add(asyncio.create_task(loop_universe(app)))
    try:
        yield
    finally:
        for t in list(app.state.tasks):
            t.cancel()
        await asyncio.gather(*app.state.tasks, return_exceptions=True)
        app.state.conn.close()


def _check_market(market: str | None) -> None:
    if market is not None and market not in MARKETS:
        raise HTTPException(422, f"mercado inválido: {market}")


def create_app() -> FastAPI:
    app = FastAPI(title="Radar Quant", lifespan=lifespan)

    @app.middleware("http")
    async def no_store(request: Request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        else:  # estáticos: revalidar sempre, para index.html e app.js nunca ficarem de versões diferentes
            response.headers.setdefault("Cache-Control", "no-cache")
        return response

    def conn(request: Request):
        return request.app.state.conn

    def asset_or_404(request: Request, asset_id: int) -> dict:
        asset = db.get_asset(conn(request), asset_id)
        if asset is None:
            raise HTTPException(404, "ativo não encontrado")
        return asset

    @app.get("/api/health")
    def health(request: Request):
        c = conn(request)
        assets = db.list_assets(c)
        refreshed = [a["last_refresh"] for a in assets if a["last_refresh"]]
        members = {(m["symbol"], m["market"]) for m in db.index_members(c)}
        ready = {(a["symbol"], a["market"]) for a in db.list_assets(c, None)
                 if a["last_refresh"] and not a["last_error"]} & members
        return {"status": "ok", "assets": len(assets), "last_refresh": max(refreshed, default=None),
                "catalog": db.catalog_count(c),
                "universe": {"total": len(members), "ready": len(ready)}}

    @app.get("/api/search")
    async def search_assets(request: Request, response: Response, q: Annotated[str, Query(max_length=64)] = "",
                            limit: Annotated[int, Query(ge=1, le=25)] = 12, remote: bool = True):
        """`remote=0` (a cada tecla): só o catálogo, sem rede. O cabeçalho diz se a fonte on-line foi consultada."""
        results, consulted = await search.search_detail(conn(request), q, limit, request.app.state.settings,
                                                        remote=remote)
        response.headers["X-Search-Remote"] = "1" if consulted else "0"
        return results

    @app.get("/api/assets")
    def list_assets(request: Request):
        return [analysis.asset_summary(conn(request), a) for a in db.list_assets(conn(request))]

    async def open_or_fail(request: Request, body: NewAsset) -> tuple[dict, bool]:
        """Abre o ativo (criando-o se preciso); erros da fonte viram 422/502 sem deixar nada gravado.

        Devolve também se houve refresh de fato (ativo novo ou `last_refresh` mudou)."""
        _check_market(body.market)
        c = conn(request)
        try:
            before = db.find_asset(c, normalize_symbol(body.symbol, body.market), body.market)
            asset = await service.open_asset(c, body.symbol, body.market, request.app.state.settings)
            if (asset["market"] == "B3" and request.app.state.settings.provider != "synthetic"
                    and await asyncio.to_thread(db.missing_alias, c, "B3", [asset["symbol"]])):
                spawn(request.app, learn_names_safely(request.app, [asset["symbol"]]))  # não bloqueia a resposta
            return asset, before is None or before["last_refresh"] != asset["last_refresh"]
        except UnknownSymbol:
            raise HTTPException(422, f"símbolo não encontrado em {body.market}")
        except ProviderError:
            raise HTTPException(502, "fonte de dados indisponível agora")
        except ValueError as e:
            raise HTTPException(422, str(e))

    async def summary_after_open(request: Request, asset_id: int, refreshed: bool) -> dict:
        """Resumo do ativo; só recalcula a análise e a linha do screener se houve refresh ou falta linha válida."""
        c = conn(request)
        asset = db.get_asset(c, asset_id)
        if asset is None:  # apagado por outra rotina entre abrir e resumir
            raise HTTPException(502, "ativo removido durante a abertura")
        rows = db.load_screener(c, [asset_id])
        if refreshed or not rows or rows[0]["payload"].get("status") == "insuficiente":
            analysis.invalidate(asset_id)
            await run_in_threadpool(store_rows, c, [asset])
        return await run_in_threadpool(analysis.asset_summary, c, asset)

    @app.post("/api/assets/open")
    async def open_asset(request: Request, body: NewAsset):
        asset, refreshed = await open_or_fail(request, body)
        return await summary_after_open(request, asset["id"], refreshed)

    @app.post("/api/assets", status_code=201)
    async def add_asset(request: Request, body: NewAsset):
        _check_market(body.market)
        try:
            existing = db.find_asset(conn(request), normalize_symbol(body.symbol, body.market), body.market)
        except ValueError as e:
            raise HTTPException(422, str(e))
        if existing and existing["watch"]:
            raise HTTPException(409, "ativo já está na watchlist")
        asset, refreshed = await open_or_fail(request, body)
        db.set_watch(conn(request), asset["id"], True)
        return await summary_after_open(request, asset["id"], refreshed)

    @app.delete("/api/assets/{asset_id}", status_code=204)
    def delete_asset(request: Request, asset_id: AssetId):
        asset = asset_or_404(request, asset_id)
        entry = db.catalog_entry(conn(request), asset["symbol"], asset["market"])
        if entry and entry["indices"]:  # membro de índice: sai da watchlist mas continua no screener
            db.set_watch(conn(request), asset_id, False)
        else:
            db.delete_asset(conn(request), asset_id)
            analysis.invalidate(asset_id)
        return Response(status_code=204)

    @app.get("/api/assets/{asset_id}/candles")
    async def candles(request: Request, asset_id: AssetId, interval: Interval = "1d"):
        asset = asset_or_404(request, asset_id)
        if interval not in INTRADAY:
            return await run_in_threadpool(analysis.candles_payload, conn(request), asset_id, interval)
        try:
            data = await service.load_intraday(asset, interval, request.app.state.settings)
        except ProviderError:  # inclui UnknownSymbol
            raise HTTPException(422, "intraday indisponível para este ativo agora")
        return await run_in_threadpool(analysis.intraday_payload, data["bars"], interval, data["delay_minutes"])

    @app.get("/api/assets/{asset_id}/news")
    async def asset_news(request: Request, asset_id: AssetId):
        return await news.get_news(conn(request), asset_or_404(request, asset_id), request.app.state.settings)

    @app.get("/api/assets/{asset_id}/analysis")
    def asset_analysis(request: Request, asset_id: AssetId):
        return analysis.analyze_asset(conn(request), asset_or_404(request, asset_id))

    def screener_call(fn, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except screener.ScreenerError as e:
            raise HTTPException(422, str(e))

    @app.get("/api/screener")
    def screener_query(request: Request, scope: Short = "watchlist", market: Short | None = None,
                       verdict: Short | None = None, evidence: Short | None = None, setup: Short | None = None,
                       sort: Short = "score", order: Short = "desc", page: int = 1, page_size: int = 50):
        return screener_call(screener.query, conn(request), scope, market, verdict, evidence, setup,
                             sort, order, page, page_size)

    @app.get("/api/screener/summary")
    def screener_summary(request: Request, scope: Short = "watchlist"):
        return screener_call(screener.summary, conn(request), scope)

    @app.get("/api/screener/progress")
    def screener_progress(request: Request, scope: Short = "watchlist"):
        return screener_call(screener.progress, conn(request), scope)

    @app.get("/api/ranking")
    def ranking(request: Request, market: str | None = None):
        _check_market(market)
        return analysis.ranking(conn(request), market)

    @app.get("/api/portfolio")
    def portfolio(request: Request, method: str = "risk_parity", market: str | None = None):
        _check_market(market)
        try:
            return analysis.portfolio(conn(request), method, market)
        except PortfolioError as e:
            raise HTTPException(422, str(e))

    @app.post("/api/refresh", status_code=202)
    async def refresh(request: Request):
        if request.app.state.refresh_lock.locked():
            return {"status": "em andamento"}
        spawn(request.app, refresh_safely(request.app))
        return {"status": "agendado"}

    app.mount("/", StaticFiles(directory=STATIC, html=True), name="static")
    return app


app = create_app()
