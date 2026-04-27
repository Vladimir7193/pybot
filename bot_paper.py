"""
Paper Trading Bot - мониторинг сигналов без реальных сделок.
Отправляет уведомления в Telegram о потенциальных сигналах.
Ведёт виртуальный PnL по каждому сигналу (симуляция по ценам закрытия свечей).
"""
from __future__ import annotations
import os
import time
import datetime
from dataclasses import dataclass, field
from typing import Optional, Dict

from dotenv import load_dotenv

from config import (
    SYMBOLS, HTF, LTF, CTF, TRADE_HOUR_START, TRADE_HOUR_END,
    SYMBOL_PARAMS, MAX_POSITIONS, RISK_PER_TRADE, ENABLE_SMC,
    SIGNAL_DEDUPE_SEC,
)
from bybit_client import BybitClient
from indicators import compute_all
from signal_engine import SignalEngine
from notifier import TelegramNotifier
from signal_dedupe import SignalDedupe
from logger import log

load_dotenv()


DEDUPE_PATH = os.path.join(os.path.dirname(__file__), "state", "paper_dedupe.json")


# ── Virtual PnL tracker ───────────────────────────────────────────────────────

@dataclass
class PaperPosition:
    symbol:    str
    direction: str   # "Buy" | "Sell"
    entry:     float
    tp:        float
    sl:        float
    qty:       float
    rr:        float
    opened_at: str = ""

@dataclass
class PaperPortfolio:
    equity:     float = 1000.0
    positions:  Dict[str, PaperPosition] = field(default_factory=dict)
    total_pnl:  float = 0.0
    wins:       int   = 0
    losses:     int   = 0

    def open(self, sig) -> None:
        """Open a virtual position from a signal."""
        if sig.symbol in self.positions:
            return  # already in trade
        self.positions[sig.symbol] = PaperPosition(
            symbol=sig.symbol, direction=sig.direction,
            entry=sig.entry, tp=sig.tp, sl=sig.sl,
            qty=sig.qty, rr=sig.rr,
            opened_at=datetime.datetime.now(datetime.timezone.utc).strftime("%H:%M UTC"),
        )
        log.info(f"[PAPER] 📂 Opened virtual {sig.direction} {sig.symbol} @ {sig.entry:.4f}  TP={sig.tp:.4f}  SL={sig.sl:.4f}")

    def tick(self, symbol: str, price: float) -> Optional[str]:
        """Check if virtual position hit TP or SL. Returns 'tp'/'sl'/None."""
        pos = self.positions.get(symbol)
        if pos is None:
            return None
        hit = None
        if pos.direction == "Buy":
            if price >= pos.tp:
                hit = "tp"
            elif price <= pos.sl:
                hit = "sl"
        else:
            if price <= pos.tp:
                hit = "tp"
            elif price >= pos.sl:
                hit = "sl"
        if hit:
            pnl_pct = abs(pos.tp - pos.entry) / pos.entry if hit == "tp" else -abs(pos.entry - pos.sl) / pos.entry
            pnl_usd = pnl_pct * self.equity * 0.01  # 1% risk
            self.total_pnl += pnl_usd
            self.equity += pnl_usd
            if hit == "tp":
                self.wins += 1
                log.info(f"[PAPER] ✅ TP hit {symbol} | PnL: +${pnl_usd:.2f} | Equity: ${self.equity:.2f}")
            else:
                self.losses += 1
                log.info(f"[PAPER] ❌ SL hit {symbol} | PnL: ${pnl_usd:.2f} | Equity: ${self.equity:.2f}")
            del self.positions[symbol]
        return hit

    @property
    def winrate(self) -> float:
        total = self.wins + self.losses
        return self.wins / total * 100 if total else 0.0

    def summary(self) -> str:
        total = self.wins + self.losses
        return (
            f"💼 Equity: ${self.equity:.2f} | PnL: ${self.total_pnl:+.2f}\n"
            f"📊 Trades: {total} | W: {self.wins} L: {self.losses} | WR: {self.winrate:.0f}%\n"
            f"🔓 Open: {len(self.positions)}"
        )


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
    client:    BybitClient,
    notifier:  TelegramNotifier,
    engine:    SignalEngine,
    portfolio: PaperPortfolio,
    dedupe:    Optional[SignalDedupe] = None,
) -> None:
    """Single tick: scan all symbols for signals + update virtual positions."""

    open_count = len(portfolio.positions)

    for symbol in SYMBOLS:
        try:
            _process_symbol(symbol, client, notifier, engine, portfolio, open_count, dedupe=dedupe)
        except Exception as e:
            log.error(f"[{symbol}] Tick error: {e}", exc_info=True)
            notifier.error(f"[{symbol}] {e}")


def _process_symbol(
    symbol:     str,
    client:     BybitClient,
    notifier:   TelegramNotifier,
    engine:     SignalEngine,
    portfolio:  PaperPortfolio,
    open_count: int,
    dedupe:     Optional[SignalDedupe] = None,
) -> None:
    params = SYMBOL_PARAMS[symbol]

    # ── Fetch candles ────────────────────────────────────────────────────
    df_htf = client.get_klines(symbol, HTF, limit=300)
    df_ltf = client.get_klines(symbol, LTF, limit=100)
    df_ctf = client.get_klines(symbol, CTF, limit=200)

    if df_htf.empty or df_ltf.empty:
        log.warning(f"[{symbol}] Empty klines")
        return

    df_htf = compute_all(df_htf)
    df_ltf = compute_all(df_ltf)
    if not df_ctf.empty:
        df_ctf = compute_all(df_ctf)
    else:
        df_ctf = None

    last_ltf = df_ltf.iloc[-2]
    close = float(last_ltf["close"])

    # ── Check virtual position ───────────────────────────────────────────
    result = portfolio.tick(symbol, close)
    if result:
        notifier.info(
            f"{'✅ TP' if result == 'tp' else '❌ SL'} hit [{symbol}] @ {close:.4f}\n"
            + portfolio.summary()
        )

    # ── Trading hours filter ─────────────────────────────────────────────
    if not is_trading_hour():
        log.debug(f"[{symbol}] Outside trading hours")
        return

    # ── Instrument info ──────────────────────────────────────────────────
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
        equity=portfolio.equity,
        drawdown=0.0,
        open_count=open_count,
        instrument=instrument,
    )

    if sig is None:
        log.debug(
            f"[{symbol}] No signal | "
            f"Price={close:.4f} | "
            f"Positions={open_count}/{MAX_POSITIONS}"
        )
        return

    # ── Cross-restart / intra-bar dedupe ──────────────────────────────────
    if dedupe is not None and not dedupe.should_emit(symbol, sig.direction, sig.entry, sig.tp, sig.sl):
        log.info(
            f"[{symbol}] Duplicate paper signal suppressed "
            f"(dir={sig.direction} entry={sig.entry:.4f} within {dedupe.window_sec}s window)"
        )
        return

    # ── Open virtual position ────────────────────────────────────────────
    portfolio.open(sig)

    # ── Notify ───────────────────────────────────────────────────────────
    mode_emoji = "🔥" if sig.mode == "STRICT" else "⚡" if sig.mode == "RELAXED" else "📊"
    log.info(f"\n{'='*60}")
    log.info(f"  📊 PAPER SIGNAL [{sig.mode}] {mode_emoji}: {symbol}")
    log.info(f"{'='*60}")

    if dedupe is not None:
        dedupe.record(symbol, sig.direction, sig.entry, sig.tp, sig.sl)

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
    log.info(f"  RocketBot PAPER TRADING  |  SMC={'ON' if ENABLE_SMC else 'OFF'}")
    log.info("=" * 60)

    client, notifier = build_clients()

    # ── Virtual portfolio ─────────────────────────────────────────────────
    portfolio = PaperPortfolio(equity=1000.0)
    log.info(f"Paper Trading Equity: ${portfolio.equity:.2f} USDT")

    msg = (
        f"🤖 <b>RocketBot Paper Trading Started</b>\n\n"
        f"💰 Virtual Equity: ${portfolio.equity:.2f} USDT\n"
        f"📊 Strategy: {'SMC' if ENABLE_SMC else 'Classic'}\n"
        f"📈 Symbols: {', '.join(SYMBOLS)}\n"
        f"⏰ Trading Hours: {TRADE_HOUR_START:02d}:00 - {TRADE_HOUR_END:02d}:00 UTC\n"
        f"⚠️ <b>NO REAL TRADES - MONITORING ONLY</b>"
    )
    notifier.info(msg)

    # ── Signal engine + persistent dedupe ─────────────────────────────────
    engine = SignalEngine(equity_fn=lambda: portfolio.equity, max_positions=MAX_POSITIONS)
    dedupe = SignalDedupe(path=DEDUPE_PATH, window_sec=SIGNAL_DEDUPE_SEC)

    # ── Main loop ─────────────────────────────────────────────────────────
    interval_sec = int(os.getenv("INTERVAL", "15")) * 60

    log.info(f"Scanning {len(SYMBOLS)} symbols every {interval_sec//60}m: {SYMBOLS}")
    log.info(f"Strategy: {'SMC' if ENABLE_SMC else 'Classic'}")

    while True:
        tick_start = time.time()
        now = datetime.datetime.now(datetime.timezone.utc)
        log.info(f"\n{'─'*60}")
        log.info(f"  📊 PAPER TICK  {now.strftime('%Y-%m-%d %H:%M:%S')} UTC")
        log.info(f"  Strategy: {'SMC' if ENABLE_SMC else 'Classic'}")
        log.info(f"{'─'*60}")

        run_tick(client, notifier, engine, portfolio, dedupe=dedupe)
        engine.log_reject_stats()
        log.info(f"[PAPER] {portfolio.summary()}")

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
