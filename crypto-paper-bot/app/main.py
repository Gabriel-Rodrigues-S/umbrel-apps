import asyncio
import logging
import time
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import engine, exchange
from .db import backfill_net_pnl, get_conn, init_db

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    adjusted = backfill_net_pnl(engine.FEE_RATE)
    if adjusted:
        logging.getLogger("engine").info("pnl líquido de taxa de entrada aplicado a %d trades antigos", adjusted)
    task = asyncio.create_task(engine.run_forever())
    yield
    task.cancel()


app = FastAPI(title="Crypto Paper Bot", lifespan=lifespan)


@app.middleware("http")
async def no_cache_api(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response

STRATEGIES = ["sma_crossover", "macd_crossover", "rsi_reversion", "bollinger_reversion"]


class BotCreate(BaseModel):
    symbol: str = "BTC/USDT"
    timeframe: str = "5m"
    strategy: Literal["sma_crossover", "macd_crossover", "rsi_reversion", "bollinger_reversion"] = "sma_crossover"
    starting_balance: float = 1000
    fast_period: int = 9
    slow_period: int = 21
    adx_period: int = 14
    adx_threshold: float = 25
    rsi_period: int = 14
    rsi_oversold: float = 30
    rsi_overbought: float = 70
    bb_period: int = 20
    bb_std: float = 2.0
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9
    confirm_ticks: int = 2
    confirmation_mode: Literal["ticks", "higher_timeframe", "none"] = "ticks"
    higher_timeframe: str = "1h"
    trading_mode: Literal["long", "short", "long_short"] = "long"
    nickname: str | None = None


@app.get("/api/strategies")
def api_strategies():
    return [
        {"id": "sma_crossover", "name": "SMA Crossover", "regime": "tendência",
         "description": "Compra/vende no cruzamento de médias móveis. Bom em tendência forte."},
        {"id": "macd_crossover", "name": "MACD Crossover", "regime": "tendência",
         "description": "Como o SMA crossover, mas com médias exponenciais (reage mais rápido)."},
        {"id": "rsi_reversion", "name": "RSI Reversão", "regime": "lateral",
         "description": "Compra na volta da sobrevenda, vende na volta da sobrecompra. Bom sem tendência."},
        {"id": "bollinger_reversion", "name": "Bandas de Bollinger", "regime": "lateral",
         "description": "Compra no repique da banda inferior, vende no repique da banda superior."},
    ]


@app.get("/api/symbols")
def api_symbols():
    try:
        return exchange.list_symbols()[:200]
    except Exception as e:
        raise HTTPException(502, f"falha ao consultar a exchange: {e}")


@app.post("/api/bots")
def create_bot(payload: BotCreate):
    # O filtro de timeframe maior so roda em estrategia de TENDENCIA (o engine
    # exige regime == "trend"), e trend_direction() nem sabe calcular direcao
    # para RSI/Bollinger. Aceitar essa combinacao criaria um bot cujo apelido
    # promete confirmacao em 1h mas que na pratica entra sem filtro algum.
    if payload.confirmation_mode == "higher_timeframe" and engine.STRATEGY_REGIME[payload.strategy] != "trend":
        raise HTTPException(
            422,
            "confirmação por timeframe maior só funciona em estratégias de tendência "
            f"(SMA e MACD). Para {payload.strategy}, use 'ticks' ou 'none'.",
        )
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO bots (
                   symbol, timeframe, strategy, starting_balance, cash,
                   fast_period, slow_period, adx_period, adx_threshold,
                   rsi_period, rsi_oversold, rsi_overbought,
                   bb_period, bb_std, macd_fast, macd_slow, macd_signal,
                   confirm_ticks, confirmation_mode, higher_timeframe,
                   trading_mode, nickname
               ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                payload.symbol,
                payload.timeframe,
                payload.strategy,
                payload.starting_balance,
                payload.starting_balance,
                payload.fast_period,
                payload.slow_period,
                payload.adx_period,
                payload.adx_threshold,
                payload.rsi_period,
                payload.rsi_oversold,
                payload.rsi_overbought,
                payload.bb_period,
                payload.bb_std,
                payload.macd_fast,
                payload.macd_slow,
                payload.macd_signal,
                payload.confirm_ticks,
                payload.confirmation_mode,
                payload.higher_timeframe,
                payload.trading_mode,
                payload.nickname,
            ),
        )
        return {"id": cur.lastrowid}


@app.get("/api/bots")
def list_bots():
    with get_conn() as conn:
        bots = [dict(r) for r in conn.execute("SELECT * FROM bots ORDER BY sort_order ASC, id DESC").fetchall()]
        for bot in bots:
            # preco e ADX vem do cache que o motor grava a cada tick. Antes esta
            # rota consultava a exchange 2x por bot a cada request: com 24 bots
            # eram ~48 chamadas sequenciais (~22s), e a tela pede a cada 2s.
            # Um bot pausado nao roda tick, entao o valor fica congelado no
            # ultimo tick - por isso `quote_updated_at` vai junto na resposta.
            last_price = bot.get("last_price")
            current_adx = bot.get("current_adx")
            regime = engine.STRATEGY_REGIME[bot["strategy"]]
            if current_adx is None:
                bot["trading_active"] = None
            elif regime == "trend":
                bot["trading_active"] = current_adx >= bot["adx_threshold"]
            else:
                bot["trading_active"] = current_adx < bot["adx_threshold"]
            bot["equity"] = engine.equity_for(
                bot["cash"], bot["position_qty"], bot.get("position_entry_price"),
                last_price if last_price is not None else (bot.get("position_entry_price") or 0),
            )
            bot["pnl"] = bot["equity"] - bot["starting_balance"]
            bot["pnl_pct"] = (bot["pnl"] / bot["starting_balance"] * 100) if bot["starting_balance"] else 0
        return bots


class BotOrder(BaseModel):
    ids: list[int]


@app.post("/api/bots/reorder")
def reorder_bots(payload: BotOrder):
    """Grava a ordem escolhida pelo usuario: a posicao de cada id na lista
    recebida vira o sort_order do bot. Ids desconhecidos sao ignorados; bots
    que nao vierem na lista ficam com o sort_order que ja tinham."""
    with get_conn() as conn:
        conhecidos = {r["id"] for r in conn.execute("SELECT id FROM bots")}
        for posicao, bot_id in enumerate(payload.ids):
            if bot_id in conhecidos:
                conn.execute("UPDATE bots SET sort_order = ? WHERE id = ?", (posicao, bot_id))
    return {"ok": True}


@app.get("/api/bots/{bot_id}")
def get_bot(bot_id: int):
    with get_conn() as conn:
        bot = conn.execute("SELECT * FROM bots WHERE id = ?", (bot_id,)).fetchone()
        if not bot:
            raise HTTPException(404, "bot não encontrado")
        trades = [dict(r) for r in conn.execute(
            "SELECT * FROM trades WHERE bot_id = ? ORDER BY id DESC LIMIT 200", (bot_id,)
        ).fetchall()]
        equity = [dict(r) for r in conn.execute(
            "SELECT * FROM equity_snapshots WHERE bot_id = ? ORDER BY id DESC LIMIT 500", (bot_id,)
        ).fetchall()]
        return {"bot": dict(bot), "trades": trades, "equity": list(reversed(equity))}


@app.get("/api/bots/{bot_id}/candles")
def get_bot_candles(bot_id: int):
    with get_conn() as conn:
        bot = conn.execute("SELECT * FROM bots WHERE id = ?", (bot_id,)).fetchone()
        if not bot:
            raise HTTPException(404, "bot não encontrado")
    try:
        candles = exchange.fetch_ohlcv(bot["symbol"], bot["timeframe"], 150)
        ticker = exchange.fetch_ticker_stats(bot["symbol"])
    except Exception as e:
        raise HTTPException(502, f"falha ao consultar a exchange: {e}")
    return {
        "ticker": ticker,
        "fetched_at": time.time() * 1000,
        "candles": [
            {"time": c[0], "open": c[1], "high": c[2], "low": c[3], "close": c[4]}
            for c in candles
        ],
    }


@app.post("/api/bots/{bot_id}/pause")
def pause_bot(bot_id: int):
    with get_conn() as conn:
        conn.execute("UPDATE bots SET status = 'paused' WHERE id = ?", (bot_id,))
    return {"ok": True}


@app.post("/api/bots/{bot_id}/resume")
def resume_bot(bot_id: int):
    with get_conn() as conn:
        conn.execute("UPDATE bots SET status = 'running' WHERE id = ?", (bot_id,))
    return {"ok": True}


@app.delete("/api/bots/{bot_id}")
def delete_bot(bot_id: int):
    with get_conn() as conn:
        conn.execute("DELETE FROM equity_snapshots WHERE bot_id = ?", (bot_id,))
        conn.execute("DELETE FROM trades WHERE bot_id = ?", (bot_id,))
        conn.execute("DELETE FROM bots WHERE id = ?", (bot_id,))
    return {"ok": True}


app.mount("/static", StaticFiles(directory="app/static"), name="static")


@app.get("/")
def index():
    return FileResponse("app/static/index.html")
