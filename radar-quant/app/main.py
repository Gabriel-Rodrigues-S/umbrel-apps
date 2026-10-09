"""API FastAPI do Radar Quant: rotas, refresh em segundo plano e arquivos estáticos."""
import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Literal

from fastapi import FastAPI, HTTPException, Path as PathParam, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app import analysis, db, service
from app.config import MARKETS, get_settings, normalize_symbol
from app.providers.base import UnknownSymbol
from app.stats.portfolio import PortfolioError

log = logging.getLogger("radar")
STATIC = Path(__file__).parent / "static"
RETRY_SECONDS = 600  # nova tentativa quando algum ativo ficou com erro
AssetId = Annotated[int, PathParam(ge=1, le=2**63 - 1)]  # faixa do INTEGER do SQLite


class NewAsset(BaseModel):
    symbol: str
    market: str


async def refresh_everything(app: FastAPI) -> None:
    """Refresh geral; nunca roda dois ao mesmo tempo."""
    async with app.state.refresh_lock:
        await service.refresh_all(app.state.conn, app.state.settings)
        analysis.invalidate()


async def refresh_safely(app: FastAPI) -> None:
    try:
        await refresh_everything(app)
    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception("falha no refresh em segundo plano")


def sleep_seconds(app: FastAPI) -> float:
    """Espera até o próximo refresh; curta se algum ativo ficou com erro (ex.: rede fora na subida)."""
    normal = app.state.settings.refresh_hours * 3600
    failed = any(a["last_error"] for a in db.list_assets(app.state.conn))
    return min(RETRY_SECONDS, normal) if failed else normal


async def loop_refresh(app: FastAPI) -> None:
    while True:
        await refresh_safely(app)
        await asyncio.sleep(sleep_seconds(app))


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    app.state.settings = settings
    app.state.conn = db.connect(settings.data_dir / "radar.db")
    app.state.refresh_lock = asyncio.Lock()
    app.state.tasks = set()
    service.seed_watchlist(app.state.conn)
    if os.environ.get("RADAR_SKIP_BACKGROUND") != "1":
        app.state.tasks.add(asyncio.create_task(loop_refresh(app)))
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
        assets = db.list_assets(conn(request))
        refreshed = [a["last_refresh"] for a in assets if a["last_refresh"]]
        return {"status": "ok", "assets": len(assets), "last_refresh": max(refreshed, default=None)}

    @app.get("/api/assets")
    def list_assets(request: Request):
        return [analysis.asset_summary(conn(request), a) for a in db.list_assets(conn(request))]

    @app.post("/api/assets", status_code=201)
    async def add_asset(request: Request, body: NewAsset):
        _check_market(body.market)
        try:
            symbol = normalize_symbol(body.symbol, body.market)
        except ValueError as e:
            raise HTTPException(422, str(e))
        c = conn(request)
        try:
            asset_id = db.add_asset(c, symbol, body.market)
        except db.DuplicateAsset:
            raise HTTPException(409, "ativo já está na watchlist")
        try:
            await service.refresh_asset(c, db.get_asset(c, asset_id), request.app.state.settings)
        except Exception as e:  # sem refresh bem-sucedido o ativo recém-criado não fica gravado
            db.delete_asset(c, asset_id)
            analysis.invalidate(asset_id)
            if isinstance(e, UnknownSymbol):
                raise HTTPException(422, f"símbolo não encontrado em {body.market}")
            raise
        analysis.invalidate(asset_id)
        return await run_in_threadpool(analysis.asset_summary, c, db.get_asset(c, asset_id))

    @app.delete("/api/assets/{asset_id}", status_code=204)
    def delete_asset(request: Request, asset_id: AssetId):
        if not db.delete_asset(conn(request), asset_id):
            raise HTTPException(404, "ativo não encontrado")
        analysis.invalidate(asset_id)
        return Response(status_code=204)

    @app.get("/api/assets/{asset_id}/candles")
    def candles(request: Request, asset_id: AssetId, interval: Literal["1d", "1wk", "1mo"] = "1d"):
        asset_or_404(request, asset_id)
        return analysis.candles_payload(conn(request), asset_id, interval)

    @app.get("/api/assets/{asset_id}/analysis")
    def asset_analysis(request: Request, asset_id: AssetId):
        return analysis.analyze_asset(conn(request), asset_or_404(request, asset_id))

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
        task = asyncio.create_task(refresh_safely(request.app))
        request.app.state.tasks.add(task)
        task.add_done_callback(request.app.state.tasks.discard)
        return {"status": "agendado"}

    app.mount("/", StaticFiles(directory=STATIC, html=True), name="static")
    return app


app = create_app()
