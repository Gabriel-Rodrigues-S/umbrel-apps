import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import engine, exchange
from .db import get_conn, init_db

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    task = asyncio.create_task(engine.run_forever())
    yield
    task.cancel()


app = FastAPI(title="Crypto Paper Bot", lifespan=lifespan)


class BotCreate(BaseModel):
    symbol: str = "BTC/USDT"
    timeframe: str = "5m"
    fast_period: int = 9
    slow_period: int = 21
    starting_balance: float = 1000


@app.get("/api/symbols")
def api_symbols():
    try:
        return exchange.list_symbols()[:200]
    except Exception as e:
        raise HTTPException(502, f"falha ao consultar a exchange: {e}")


@app.post("/api/bots")
def create_bot(payload: BotCreate):
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO bots (symbol, timeframe, fast_period, slow_period,
               starting_balance, cash) VALUES (?,?,?,?,?,?)""",
            (
                payload.symbol,
                payload.timeframe,
                payload.fast_period,
                payload.slow_period,
                payload.starting_balance,
                payload.starting_balance,
            ),
        )
        return {"id": cur.lastrowid}


@app.get("/api/bots")
def list_bots():
    with get_conn() as conn:
        bots = [dict(r) for r in conn.execute("SELECT * FROM bots ORDER BY id DESC").fetchall()]
        for bot in bots:
            last_price = None
            try:
                last_price = exchange.fetch_last_price(bot["symbol"])
            except Exception:
                pass
            bot["last_price"] = last_price
            bot["equity"] = bot["cash"] + bot["position_qty"] * (last_price or bot.get("position_entry_price") or 0)
            bot["pnl"] = bot["equity"] - bot["starting_balance"]
            bot["pnl_pct"] = (bot["pnl"] / bot["starting_balance"] * 100) if bot["starting_balance"] else 0
        return bots


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
