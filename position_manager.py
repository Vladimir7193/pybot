"""
Position lifecycle manager.
Tracks open positions, checks breakeven, time exit.
Syncs with Bybit open positions on startup.
"""
from __future__ import annotations
import time
from dataclasses import dataclass, field
from typing import Optional

from config import BREAKEVEN_ATR, MAX_BARS_IN_TRADE
from logger import log


@dataclass
class Position:
    symbol:          str
    side:            str    # "Buy" | "Sell"
    entry:           float
    tp:              float
    sl:              float
    qty:             float
    atr:             float
    order_id:        str    = ""
    bars_held:       int    = 0
    breakeven_moved: bool   = False
    open_ts:         float  = field(default_factory=time.time)


class PositionManager:
    def __init__(self, bybit_client, notifier):
        self._client   = bybit_client
        self._notifier = notifier
        self._positions: dict[str, Position] = {}

    @property
    def count(self) -> int:
        return len(self._positions)

    def has(self, symbol: str) -> bool:
        return symbol in self._positions

    def get(self, symbol: str) -> Optional[Position]:
        return self._positions.get(symbol)

    def open(self, symbol: str, pos: Position) -> None:
        self._positions[symbol] = pos
        log.info(f"[{symbol}] Position opened: {pos.side} qty={pos.qty} entry={pos.entry:.4f}")

    def close(self, symbol: str, reason: str, pnl: float = 0.0) -> None:
        pos = self._positions.pop(symbol, None)
        if pos:
            log.info(
                f"[{symbol}] Position CLOSED | Reason: {reason} | "
                f"PnL: {pnl:+.2f} USDT | Held: {pos.bars_held} bars"
            )
            self._notifier.closed(symbol, pos.side, pnl, reason)

    def tick(self, symbol: str, high: float, low: float, close: float) -> Optional[str]:
        """
        Called on each new candle. Returns exit reason string or None.
        Also handles breakeven logic.
        """
        pos = self._positions.get(symbol)
        if not pos:
            return None

        pos.bars_held += 1

        # ── Breakeven ────────────────────────────────────────────────────
        if not pos.breakeven_moved and pos.atr > 0:
            profit = (close - pos.entry) if pos.side == "Buy" else (pos.entry - close)
            if profit > BREAKEVEN_ATR * pos.atr:
                new_sl = pos.entry
                try:
                    self._client.set_trading_stop(symbol, sl=new_sl, tp=pos.tp)
                    pos.sl = new_sl
                    pos.breakeven_moved = True
                    log.info(f"[{symbol}] Breakeven activated → SL moved to {new_sl:.4f}")
                    self._notifier.info(f"[{symbol}] Breakeven activated @ {new_sl:.4f}")
                except Exception as e:
                    log.warning(f"[{symbol}] Breakeven set failed: {e}")

        # ── TP hit ───────────────────────────────────────────────────────
        if pos.side == "Buy" and high >= pos.tp:
            pnl = (pos.tp - pos.entry) * pos.qty
            self.close(symbol, "TP_HIT", pnl)
            return "TP_HIT"
        if pos.side == "Sell" and low <= pos.tp:
            pnl = (pos.entry - pos.tp) * pos.qty
            self.close(symbol, "TP_HIT", pnl)
            return "TP_HIT"

        # ── SL hit ───────────────────────────────────────────────────────
        if pos.side == "Buy" and low <= pos.sl:
            pnl = (pos.sl - pos.entry) * pos.qty
            self.close(symbol, "SL_HIT", pnl)
            return "SL_HIT"
        if pos.side == "Sell" and high >= pos.sl:
            pnl = (pos.entry - pos.sl) * pos.qty
            self.close(symbol, "SL_HIT", pnl)
            return "SL_HIT"

        # ── Time exit ────────────────────────────────────────────────────
        if pos.bars_held >= MAX_BARS_IN_TRADE:
            pnl = (close - pos.entry) * pos.qty if pos.side == "Buy" else (pos.entry - close) * pos.qty
            try:
                self._client.close_position(symbol, pos.side, pos.qty)
            except Exception as e:
                log.error(f"[{symbol}] TIME_EXIT close_position failed: {e}")
            self.close(symbol, "TIME_EXIT", pnl)
            return "TIME_EXIT"

        log.debug(
            f"[{symbol}] Position {pos.side} | Entry={pos.entry:.4f} | "
            f"TP={pos.tp:.4f} | SL={pos.sl:.4f} | "
            f"Price={close:.4f} | Bars={pos.bars_held}"
        )
        return None

    def sync_with_exchange(self) -> None:
        """
        On startup: fetch open positions from Bybit and populate local state.
        Prevents duplicate orders after restart.
        """
        try:
            open_pos = self._client.get_open_positions()
            for p in open_pos:
                sym  = p["symbol"]
                side = p["side"]
                size = float(p["size"])
                entry = float(p["avgPrice"])
                tp   = float(p.get("takeProfit", 0))
                sl   = float(p.get("stopLoss", 0))
                if sym not in self._positions:
                    self._positions[sym] = Position(
                        symbol=sym, side=side, entry=entry,
                        tp=tp, sl=sl, qty=size, atr=0.0,
                    )
                    log.info(f"[{sym}] Synced existing position from exchange: {side} qty={size}")
        except Exception as e:
            log.error(f"Position sync failed: {e}")
