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
    trend_direction,
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


def equity_for(cash: float, qty: float, entry_price: float | None, price: float) -> float:
    if qty > 0:
        return cash + qty * price
    if qty < 0:
        return cash + (entry_price - price) * abs(qty)
    return cash


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
    trading_mode = bot["trading_mode"]  # 'long', 'short' ou 'long_short'
    qty_snapshot = bot["position_qty"]

    # descarta sinais de entrada que o modo do bot não permite: 'buy' com
    # posição zerada só abre LONG se o modo permitir; 'sell' com posição
    # zerada só abre SHORT se o modo permitir. Sinais de SAÍDA (fechar uma
    # posição já aberta) nunca são afetados por isso.
    if signal == "buy" and qty_snapshot == 0 and trading_mode not in ("long", "long_short"):
        signal = None
    if signal == "sell" and qty_snapshot == 0 and trading_mode not in ("short", "long_short"):
        signal = None

    is_new_entry = (signal == "buy" and qty_snapshot == 0) or (signal == "sell" and qty_snapshot == 0)

    # filtro de ADX: só bloqueia NOVAS ENTRADAS fora do regime certo pra cada
    # estratégia (tendência precisa de ADX alto, reversão precisa de ADX baixo).
    # Nunca bloqueia uma saída que fecharia uma posição já aberta — senão o bot
    # pode ficar preso numa posição perdedora se o regime de mercado mudar
    # antes do sinal de saída aparecer.
    if is_new_entry:
        if adx_value is None:
            signal = None
        elif regime == "trend" and adx_value < bot["adx_threshold"]:
            signal = None
        elif regime == "range" and adx_value >= bot["adx_threshold"]:
            signal = None

    # confirmação multi-timeframe: só entra se um timeframe maior concordar
    # com a direção do sinal (alta pra long, baixa pra short) — filtro mais
    # forte que a persistência, mas o bot vai operar com bem menos frequência.
    # Só se aplica a novas entradas de estratégias de tendência.
    if is_new_entry and signal is not None and bot["confirmation_mode"] == "higher_timeframe" and regime == "trend":
        higher_candles = await asyncio.to_thread(
            exchange.fetch_ohlcv, bot["symbol"], bot["higher_timeframe"], required_candles(bot)
        )
        higher_closes = [c[4] for c in higher_candles]
        wanted_direction = "up" if signal == "buy" else "down"
        if trend_direction(bot["strategy"], higher_closes, bot) != wanted_direction:
            signal = None

    if not is_new_entry:
        # saída (ou nenhum sinal de entrada): passa direto, sem gate nem
        # persistência, e não mexe no estado de confirmação pendente
        confirmed_signal = signal
        pending_signal, pending_count = bot["pending_signal"], bot["pending_signal_count"]
    elif bot["confirmation_mode"] == "higher_timeframe":
        confirmed_signal = signal
        pending_signal, pending_count = None, 0
    else:
        # confirmação por persistência: só executa quando o mesmo sinal aparece
        # em `confirm_ticks` checagens seguidas, filtrando reversões relâmpago
        # (whipsaw) que surgem e somem em segundos.
        if signal is None:
            pending_signal, pending_count = None, 0
            confirmed_signal = None
        else:
            if bot["pending_signal"] == signal:
                pending_count = bot["pending_signal_count"] + 1
            else:
                pending_count = 1
            pending_signal = signal
            if pending_count >= bot["confirm_ticks"]:
                confirmed_signal = signal
                pending_signal, pending_count = None, 0
            else:
                confirmed_signal = None

    with get_conn() as conn:
        conn.execute(
            "UPDATE bots SET pending_signal = ?, pending_signal_count = ? WHERE id = ?",
            (pending_signal, pending_count, bot["id"]),
        )
        row = conn.execute("SELECT * FROM bots WHERE id = ?", (bot["id"],)).fetchone()
        cash = row["cash"]
        qty = row["position_qty"]
        entry_price = row["position_entry_price"]
        signal = confirmed_signal

        if signal == "buy" and qty == 0:
            # abre LONG: gasta todo o caixa disponível
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
            qty, cash, entry_price = buy_qty, 0, price

        elif signal == "sell" and qty > 0:
            # fecha LONG
            proceeds = qty * price
            fee = proceeds * FEE_RATE
            proceeds -= fee
            # pnl do ciclo líquido das duas taxas: a compra gastou
            # qty*entrada/(1-FEE) do caixa (a taxa de entrada saiu ali)
            pnl = proceeds - qty * entry_price / (1 - FEE_RATE)
            conn.execute(
                "UPDATE bots SET cash = ?, position_qty = 0, position_entry_price = NULL WHERE id = ?",
                (proceeds, bot["id"]),
            )
            conn.execute(
                "INSERT INTO trades (bot_id, side, price, qty, pnl, reason) VALUES (?,?,?,?,?,?)",
                (bot["id"], "sell", price, qty, pnl, bot["strategy"]),
            )
            qty, cash = 0, proceeds

        elif signal == "sell" and qty == 0:
            # abre SHORT: "vende" uma quantidade emprestada equivalente a todo
            # o caixa disponível, recebendo o valor da venda. Fica devendo
            # essa quantidade (position_qty negativo) até recomprar.
            qty_abs = cash / price
            fee = (qty_abs * price) * FEE_RATE
            new_cash = cash - fee
            conn.execute(
                "UPDATE bots SET cash = ?, position_qty = ?, position_entry_price = ? WHERE id = ?",
                (new_cash, -qty_abs, price, bot["id"]),
            )
            conn.execute(
                "INSERT INTO trades (bot_id, side, price, qty, reason) VALUES (?,?,?,?,?)",
                (bot["id"], "sell", price, qty_abs, bot["strategy"]),
            )
            qty, cash, entry_price = -qty_abs, new_cash, price

        elif signal == "buy" and qty < 0:
            # fecha SHORT: recompra a quantidade devida; lucra se o preço
            # de recompra for menor que o preço de entrada da venda
            qty_abs = abs(qty)
            fee = (qty_abs * price) * FEE_RATE
            exit_pnl = (entry_price - price) * qty_abs - fee
            new_cash = cash + exit_pnl  # a taxa de entrada já saiu do caixa ao abrir
            pnl = exit_pnl - qty_abs * entry_price * FEE_RATE  # pnl do ciclo, líquido das duas taxas
            conn.execute(
                "UPDATE bots SET cash = ?, position_qty = 0, position_entry_price = NULL WHERE id = ?",
                (new_cash, bot["id"]),
            )
            conn.execute(
                "INSERT INTO trades (bot_id, side, price, qty, pnl, reason) VALUES (?,?,?,?,?,?)",
                (bot["id"], "buy", price, qty_abs, pnl, bot["strategy"]),
            )
            qty, cash = 0, new_cash

        equity = equity_for(cash, qty, entry_price, price)
        conn.execute(
            "INSERT INTO equity_snapshots (bot_id, equity, price) VALUES (?,?,?)",
            (bot["id"], equity, price),
        )
