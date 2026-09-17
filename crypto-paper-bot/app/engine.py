import asyncio
import logging

from . import exchange
from .db import get_conn
from .strategy import sma_crossover_signal

logger = logging.getLogger("engine")

POLL_SECONDS = 30
FEE_RATE = 0.001  # 0.1%, taxa típica de spot da Binance, simulada


async def run_forever():
    while True:
        try:
            await tick_all_bots()
        except Exception:
            logger.exception("erro no ciclo do engine")
        await asyncio.sleep(POLL_SECONDS)


async def tick_all_bots():
    with get_conn() as conn:
        bots = conn.execute("SELECT * FROM bots WHERE status = 'running'").fetchall()

    for bot in bots:
        try:
            await tick_bot(dict(bot))
        except Exception:
            logger.exception("erro processando bot %s", bot["id"])


async def tick_bot(bot: dict):
    candles = await asyncio.to_thread(
        exchange.fetch_ohlcv, bot["symbol"], bot["timeframe"], bot["slow_period"] + 5
    )
    closes = [c[4] for c in candles]
    if not closes:
        return
    price = closes[-1]

    signal = sma_crossover_signal(closes, bot["fast_period"], bot["slow_period"])

    with get_conn() as conn:
        row = conn.execute("SELECT * FROM bots WHERE id = ?", (bot["id"],)).fetchone()
        cash = row["cash"]
        qty = row["position_qty"]
        entry_price = row["position_entry_price"]

        if signal == "buy" and qty == 0:
            spend = cash
            fee = spend * FEE_RATE
            buy_qty = (spend - fee) / price
            conn.execute(
                "UPDATE bots SET cash = 0, position_qty = ?, position_entry_price = ? WHERE id = ?",
                (buy_qty, price, bot["id"]),
            )
            conn.execute(
                "INSERT INTO trades (bot_id, side, price, qty, reason) VALUES (?,?,?,?,?)",
                (bot["id"], "buy", price, buy_qty, "sma_crossover"),
            )
            qty, cash = buy_qty, 0

        elif signal == "sell" and qty > 0:
            proceeds = qty * price
            fee = proceeds * FEE_RATE
            proceeds -= fee
            pnl = proceeds - (qty * entry_price)
            conn.execute(
                "UPDATE bots SET cash = ?, position_qty = 0, position_entry_price = NULL WHERE id = ?",
                (proceeds, bot["id"]),
            )
            conn.execute(
                "INSERT INTO trades (bot_id, side, price, qty, pnl, reason) VALUES (?,?,?,?,?,?)",
                (bot["id"], "sell", price, qty, pnl, "sma_crossover"),
            )
            qty, cash = 0, proceeds

        equity = cash + qty * price
        conn.execute(
            "INSERT INTO equity_snapshots (bot_id, equity, price) VALUES (?,?,?)",
            (bot["id"], equity, price),
        )
