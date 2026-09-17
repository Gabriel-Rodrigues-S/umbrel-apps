import asyncio
import logging

from . import exchange
from .db import get_conn
from .strategy import (
    adx,
    bollinger_reversion_signal,
    macd_crossover_signal,
    rsi_signal,
    sma_crossover_signal,
)

logger = logging.getLogger("engine")

POLL_SECONDS = 10
FEE_RATE = 0.001  # 0.1%, taxa típica de spot da Binance, simulada

# regime em que cada estratégia funciona bem: 'trend' (segue tendência,
# só deve operar quando o ADX indica tendência forte) ou 'range' (reversão
# à média, só deve operar quando o ADX indica mercado lateral)
STRATEGY_REGIME = {
    "sma_crossover": "trend",
    "macd_crossover": "trend",
    "rsi_reversion": "range",
    "bollinger_reversion": "range",
}


def compute_signal(bot: dict, closes: list[float]) -> str | None:
    strategy = bot["strategy"]
    if strategy == "sma_crossover":
        return sma_crossover_signal(closes, bot["fast_period"], bot["slow_period"])
    if strategy == "macd_crossover":
        return macd_crossover_signal(closes, bot["macd_fast"], bot["macd_slow"], bot["macd_signal"])
    if strategy == "rsi_reversion":
        return rsi_signal(closes, bot["rsi_period"], bot["rsi_oversold"], bot["rsi_overbought"])
    if strategy == "bollinger_reversion":
        return bollinger_reversion_signal(closes, bot["bb_period"], bot["bb_std"])
    raise ValueError(f"estratégia desconhecida: {strategy}")


def required_candles(bot: dict) -> int:
    strategy_needs = {
        "sma_crossover": bot["slow_period"] + 1,
        "macd_crossover": bot["macd_slow"] + bot["macd_signal"] + 5,
        "rsi_reversion": bot["rsi_period"] + 5,
        "bollinger_reversion": bot["bb_period"] + 2,
    }
    return max(strategy_needs[bot["strategy"]], bot["adx_period"] * 2 + 5) + 5


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
        exchange.fetch_ohlcv, bot["symbol"], bot["timeframe"], required_candles(bot)
    )
    closes = [c[4] for c in candles]
    highs = [c[2] for c in candles]
    lows = [c[3] for c in candles]
    if not closes:
        return
    price = closes[-1]

    signal = compute_signal(bot, closes)
    adx_value = adx(highs, lows, closes, bot["adx_period"])
    regime = STRATEGY_REGIME[bot["strategy"]]

    # filtro de ADX: só bloqueia NOVAS ENTRADAS fora do regime certo pra cada
    # estratégia (tendência precisa de ADX alto, reversão precisa de ADX baixo).
    # Nunca bloqueia uma venda que fecharia uma posição já aberta — senão o bot
    # pode ficar preso numa posição perdedora se o regime de mercado mudar
    # antes do sinal de saída aparecer.
    if signal == "buy":
        if adx_value is None:
            signal = None
        elif regime == "trend" and adx_value < bot["adx_threshold"]:
            signal = None
        elif regime == "range" and adx_value >= bot["adx_threshold"]:
            signal = None

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
                (bot["id"], "buy", price, buy_qty, bot["strategy"]),
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
                (bot["id"], "sell", price, qty, pnl, bot["strategy"]),
            )
            qty, cash = 0, proceeds

        equity = cash + qty * price
        conn.execute(
            "INSERT INTO equity_snapshots (bot_id, equity, price) VALUES (?,?,?)",
            (bot["id"], equity, price),
        )
