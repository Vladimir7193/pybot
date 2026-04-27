"""
Main bot loop.
Runs every 15 minutes, scans all symbols, manages positions.
"""
from __future__ import annotations
import os
import time
import datetime
from typing import Optional

from dotenv import load_dotenv

from config import (
    SYMBOLS, HTF, LTF, CTF, TRADE_HOUR_START, TRADE_HOUR_END,
    SYMBOL_PARAMS, MAX_POSITIONS, RISK_PER_TRADE,
    SIGNAL_DEDUPE_SEC,
)
from bybit_client import BybitClient
from indicators   import compute_all
from signal_engine import SignalEngine, Signal
from position_manager import PositionManager, Position
from notifier import TelegramNotifier
from signal_dedupe import SignalDedupe
from logger import log

load_dotenv()


DEDUPE_PATH = os.path.join(os.path.dirname(__file__), "state", "live_dedupe.json")


def build_clients():
    api_key    = os.getenv("BYBIT_API_KEY", "")
    api_secret = os.getenv("BYBIT_API_SECRET", "")
    testnet    = os.getenv("BYBIT_TESTNET", "false").lower() == "true"
    tg_token   = os.getenv("TELEGRAM_TOKEN", "")
    tg_chat    = os.getenv("TELEGRAM_CHAT_ID", "")
    tg_proxy   = os.getenv("TELEGRAM_PROXY", "")

    client   = BybitClient(api_key, api_secret, testnet)
    notifier = TelegramNotifier(tg_token, tg_chat, tg_proxy)
    return client, notifier


def is_trading_hour() -> bool:
    h = datetime.datetime.now(datetime.timezone.utc).hour
    return TRADE_HOUR_START <= h < TRADE_HOUR_END


def run_tick(
    client:   BybitClient,
    notifier: TelegramNotifier,
    engine:   SignalEngine,
    pm:       PositionManager,
    equity:   float,
    peak_eq:  float,
    dedupe:   Optional[SignalDedupe] = None,
) -> tuple[float, float]:
    """Single tick: check exits + look for new signals. Returns (equity, peak_eq)."""

    drawdown = (peak_eq - equity) / peak_eq if peak_eq > 0 else 0.0

    for symbol in SYMBOLS:
        try:
            _process_symbol(symbol, client, notifier, engine, pm, equity, drawdown, dedupe=dedupe)
        except Exception as e:
            log.error(f"[{symbol}] Tick error: {e}", exc_info=True)
            notifier.error(f"[{symbol}] {e}")

    # Refresh equity after all orders
    try:
        equity = client.get_equity()
        if equity > peak_eq:
            peak_eq = equity
    except Exception as e:
        log.warning(f"Equity refresh failed: {e}")

    return equity, peak_eq


def _process_symbol(
    symbol:   str,
    client:   BybitClient,
    notifier: TelegramNotifier,
    engine:   SignalEngine,
    pm:       PositionManager,
    equity:   float,
    drawdown: float,
    dedupe:   Optional[SignalDedupe] = None,
) -> None:
    params = SYMBOL_PARAMS[symbol]

    # ── Fetch candles ────────────────────────────────────────────────────
    df_htf = client.get_klines(symbol, HTF, limit=300)
    df_ltf = client.get_klines(symbol, LTF, limit=100)
    df_ctf = client.get_klines(symbol, CTF, limit=200)  # Daily — старший контекст

    if df_htf.empty or df_ltf.empty:
        log.warning(f"[{symbol}] Empty klines")
        return

    df_htf = compute_all(df_htf)
    df_ltf = compute_all(df_ltf)
    df_ctf = compute_all(df_ctf) if not df_ctf.empty else None

    last_ltf = df_ltf.iloc[-2]   # last closed candle
    high  = float(last_ltf["high"])
    low   = float(last_ltf["low"])
    close = float(last_ltf["close"])

    # ── Check open position exit ─────────────────────────────────────────
    if pm.has(symbol):
        pm.tick(symbol, high, low, close)
        return   # don't look for new signal while in position

    # ── Trading hours filter ─────────────────────────────────────────────
    if not is_trading_hour():
        log.debug(f"[{symbol}] Outside trading hours")
        return

    # ── Instrument info (cached per run is fine) ─────────────────────────
    try:
        instrument = client.get_instrument_info(symbol)
    except Exception as e:
        log.warning(f"[{symbol}] Instrument info failed: {e}")
        return

    # ── Signal generation ────────────────────────────────────────────────
    sig = engine.analyze(
        symbol=symbol,
        df_htf=df_htf,
        df_ltf=df_ltf,
        df_ctf=df_ctf,
        equity=equity,
        drawdown=drawdown,
        open_count=pm.count,
        instrument=instrument,
    )

    if sig is None:
        log.info(
            f"[{symbol}] No signal | "
            f"Price={close:.4f} | "
            f"DD={drawdown*100:.1f}% | "
            f"Positions={pm.count}/{MAX_POSITIONS}"
        )
        return

    # ── Cross-restart / intra-bar dedupe ──────────────────────────────────
    if dedupe is not None and not dedupe.should_emit(symbol, sig.direction, sig.entry, sig.tp, sig.sl):
        log.info(
            f"[{symbol}] Duplicate signal suppressed "
            f"(dir={sig.direction} entry={sig.entry:.4f} within {dedupe.window_sec}s window)"
        )
        return

    # ── Place order ───────────────────────────────────────────────────────
    try:
        order_id = client.place_order(
            symbol=symbol,
            side=sig.direction,
            qty=sig.qty,
            tp_price=sig.tp,
            sl_price=sig.sl,
            price_tick=instrument["price_tick"],
        )
    except Exception as e:
        log.error(f"[{symbol}] Order placement failed: {e}")
        notifier.error(f"[{symbol}] Order failed: {e}")
        return

    # Record the signal only AFTER a successful order placement so that
    # failed orders can be retried on the next tick.
    if dedupe is not None:
        dedupe.record(symbol, sig.direction, sig.entry, sig.tp, sig.sl)

    # ── Register position ─────────────────────────────────────────────────
    pos = Position(
        symbol=symbol,
        side=sig.direction,
        entry=sig.entry,
        tp=sig.tp,
        sl=sig.sl,
        qty=sig.qty,
        atr=sig.atr,
        order_id=order_id,
    )
    pm.open(symbol, pos)

    # ── Notify ────────────────────────────────────────────────────────────
    notifier.signal(
        symbol=symbol,
        direction=sig.direction,
        entry=sig.entry,
        tp=sig.tp,
        sl=sig.sl,
        qty=sig.qty,
        rr=sig.rr,
        atr=sig.atr,
        reason=sig.reason,
        mode=sig.mode,
    )


def main():
    log.info("=" * 60)
    log.info("  RocketBot Python v1.0  |  Smart Money Concept")
    log.info("=" * 60)

    client, notifier = build_clients()

    # ── Equity ────────────────────────────────────────────────────────────
    equity = client.get_equity()
    peak_eq = equity
    log.info(f"Equity: ${equity:.2f} USDT")
    notifier.info(f"🤖 RocketBot started | Equity: ${equity:.2f} USDT")

    # ── Set leverage for all symbols ──────────────────────────────────────
    leverage = int(os.getenv("LEVERAGE", "10"))
    for sym in SYMBOLS:
        try:
            client.set_leverage(sym, leverage)
        except Exception as e:
            log.warning(f"[{sym}] Set leverage failed: {e}")

    # ── Position manager ──────────────────────────────────────────────────
    pm = PositionManager(client, notifier)
    pm.sync_with_exchange()

    # ── Signal engine + persistent dedupe ─────────────────────────────────
    engine = SignalEngine(equity_fn=lambda: equity, max_positions=MAX_POSITIONS)
    dedupe = SignalDedupe(path=DEDUPE_PATH, window_sec=SIGNAL_DEDUPE_SEC)

    # ── Main loop ─────────────────────────────────────────────────────────
    interval_sec = int(os.getenv("INTERVAL", "15")) * 60

    log.info(f"Scanning {len(SYMBOLS)} symbols every {interval_sec//60}m: {SYMBOLS}")

    while True:
        tick_start = time.time()
        log.info(f"\n{'─'*60}")
        log.info(f"  TICK  {datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC")
        log.info(f"  Equity: ${equity:.2f} | DD: {(peak_eq-equity)/peak_eq*100:.1f}% | Positions: {pm.count}")
        log.info(f"{'─'*60}")

        equity, peak_eq = run_tick(client, notifier, engine, pm, equity, peak_eq, dedupe=dedupe)
        engine.log_reject_stats()

        elapsed = time.time() - tick_start
        sleep_for = max(0, interval_sec - elapsed)

        log.info(f"Tick done in {elapsed:.1f}s | Sleeping {sleep_for:.0f}s")
        time.sleep(sleep_for)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log.info("Shutdown by user")
    except Exception as e:
        log.exception(f"Fatal error: {e}")
        raise
