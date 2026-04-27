"""
Generic backtest harness for the SMC SignalEngine.
Loads cached OKX data, walks through LTF bars, calls SignalEngine.analyze()
with growing slices, simulates trades, returns aggregate metrics.
"""
from __future__ import annotations
import math
import time
from dataclasses import dataclass, field
from typing import Optional

import pandas as pd

import config  # noqa: F401  -- imported so it stays a singleton
import signal_engine as se
from signal_engine import SignalEngine
from indicators import compute_all
from okx_klines import fetch_history, get_instrument


# ────────────────────────────────────────────────────────────────────────────
@dataclass
class TradeResult:
    symbol: str
    direction: str
    entry_idx: int
    entry_ts: int
    exit_idx: int
    entry_price: float
    sl_price: float
    tp_price: float
    bars_held: int
    win: bool
    profit_pct: float


@dataclass
class BacktestMetrics:
    trades: list[TradeResult] = field(default_factory=list)
    days_covered: float = 0.0

    def add(self, t: TradeResult) -> None:
        self.trades.append(t)

    @property
    def n(self) -> int:
        return len(self.trades)

    @property
    def wins(self) -> int:
        return sum(1 for t in self.trades if t.win)

    @property
    def losses(self) -> int:
        return sum(1 for t in self.trades if not t.win)

    @property
    def win_rate(self) -> float:
        return (self.wins / self.n * 100) if self.n else 0.0

    @property
    def total_profit(self) -> float:
        return sum(t.profit_pct for t in self.trades if t.profit_pct > 0)

    @property
    def total_loss(self) -> float:
        return sum(-t.profit_pct for t in self.trades if t.profit_pct < 0)

    @property
    def profit_factor(self) -> float:
        return self.total_profit / self.total_loss if self.total_loss > 0 else float("inf") if self.total_profit > 0 else 0.0

    @property
    def expectancy(self) -> float:
        return sum(t.profit_pct for t in self.trades) / self.n if self.n else 0.0

    @property
    def total_return(self) -> float:
        return sum(t.profit_pct for t in self.trades)

    @property
    def trades_per_day(self) -> float:
        return self.n / self.days_covered if self.days_covered > 0 else 0.0

    @property
    def max_drawdown(self) -> float:
        equity = 0.0
        peak = 0.0
        max_dd = 0.0
        for t in self.trades:
            equity += t.profit_pct
            if equity > peak:
                peak = equity
            dd = peak - equity
            if dd > max_dd:
                max_dd = dd
        return max_dd

    def summary(self) -> dict:
        return {
            "trades": self.n,
            "wins": self.wins,
            "losses": self.losses,
            "win_rate": round(self.win_rate, 1),
            "profit_factor": round(self.profit_factor, 2) if self.profit_factor != float("inf") else "inf",
            "expectancy_pct": round(self.expectancy, 3),
            "total_return_pct": round(self.total_return, 2),
            "max_dd_pct": round(self.max_drawdown, 2),
            "days": round(self.days_covered, 1),
            "trades_per_day": round(self.trades_per_day, 2),
        }


# ────────────────────────────────────────────────────────────────────────────
# Parameter overrides
# Most config knobs are imported by name into signal_engine, so we have to
# poke the module-level attributes directly.

_OVERRIDABLE_NAMES = {
    "ENABLE_SMC", "PURE_SMC", "SMC_MODE",
    "PREMIUM_DISCOUNT_THRESHOLD",
    "LIQUIDITY_SWEEP_LOOKBACK",
    "FVG_MIN_SIZE_ATR", "FVG_EXPIRY_CANDLES",
    "OB_IMPULSE_THRESHOLD", "OB_EXPIRY_CANDLES",
    "HOLONOMY_SENSITIVITY", "ANOMALY_THRESHOLD",
    "MIN_BARS_BETWEEN_SIGNALS", "RISK_PER_TRADE",
    "USE_SETUP_PATTERNS", "SETUP_PATTERN_CONFIDENCE_MIN",
    "USE_ORDER_FLOW", "ORDERFLOW_SEQUENCE_REQUIRED",
    "USE_KEY_LEVELS", "KEY_LEVEL_IMPORTANCE_MIN",
    "USE_FIBONACCI", "FIBONACCI_USE_OTE",
    "USE_AMD", "AMD_TIMEFRAME",
    "USE_KILL_ZONES", "KILL_ZONE_REQUIRED",
    "USE_MOMENTUM", "MOMENTUM_REQUIRED",
    "USE_RANGE_DETECTION", "RANGE_AVOID_TRADING",
}


def apply_overrides(overrides: dict) -> dict:
    """Apply param overrides to both `config` and `signal_engine` modules.

    Returns a dict of (module, name) -> previous_value so callers can restore.
    """
    saved: dict = {}
    for k, v in overrides.items():
        if k not in _OVERRIDABLE_NAMES:
            continue
        if hasattr(config, k):
            saved[("config", k)] = getattr(config, k)
            setattr(config, k, v)
        if hasattr(se, k):
            saved[("se", k)] = getattr(se, k)
            setattr(se, k, v)
    return saved


def restore_overrides(saved: dict) -> None:
    for (mod_name, name), val in saved.items():
        target = config if mod_name == "config" else se
        setattr(target, name, val)


# ────────────────────────────────────────────────────────────────────────────
# Symbol param overrides (sl_mult / tp_mult)
def apply_symbol_params(updates: dict) -> dict:
    saved: dict = {}
    sp = config.SYMBOL_PARAMS
    for sym, params in updates.items():
        if sym not in sp:
            continue
        saved[sym] = dict(sp[sym])
        sp[sym].update(params)
    # signal_engine imports SYMBOL_PARAMS by name; mirror it
    if hasattr(se, "SYMBOL_PARAMS"):
        for sym, params in updates.items():
            if sym in se.SYMBOL_PARAMS:
                se.SYMBOL_PARAMS[sym].update(params)
    return saved


def restore_symbol_params(saved: dict) -> None:
    sp = config.SYMBOL_PARAMS
    for sym, params in saved.items():
        sp[sym] = params
    if hasattr(se, "SYMBOL_PARAMS"):
        for sym, params in saved.items():
            se.SYMBOL_PARAMS[sym] = dict(params)


# ────────────────────────────────────────────────────────────────────────────
# Trade simulation
def simulate_trade(
    direction: str,
    entry_idx: int,
    entry_price: float,
    sl_price: float,
    tp_price: float,
    df_ltf: pd.DataFrame,
    rr: float,
    max_bars: int = 100,
) -> tuple[bool, float, int]:
    """
    Walk forward bar-by-bar; SL hit first => loss, TP hit first => win.
    Returns (win, profit_pct, exit_idx).  profit_pct is in *units of risk*
    (1R win = +rr, 1R loss = -1).  Multiplied by RISK_PER_TRADE*100 by caller.
    """
    end = min(entry_idx + max_bars, len(df_ltf))
    for i in range(entry_idx + 1, end):
        candle = df_ltf.iloc[i]
        high = float(candle["high"])
        low = float(candle["low"])

        if direction == "Buy":
            sl_hit = low <= sl_price
            tp_hit = high >= tp_price
            if sl_hit and tp_hit:
                # Same-bar ambiguity: assume SL hits first (conservative).
                return False, -1.0, i
            if sl_hit:
                return False, -1.0, i
            if tp_hit:
                return True, float(rr), i
        else:
            sl_hit = high >= sl_price
            tp_hit = low <= tp_price
            if sl_hit and tp_hit:
                return False, -1.0, i
            if sl_hit:
                return False, -1.0, i
            if tp_hit:
                return True, float(rr), i

    # Time-stop: close at last bar's close
    last = df_ltf.iloc[end - 1]
    last_close = float(last["close"])
    if direction == "Buy":
        pnl_r = (last_close - entry_price) / (entry_price - sl_price)
    else:
        pnl_r = (entry_price - last_close) / (sl_price - entry_price)
    return pnl_r > 0, float(pnl_r), end - 1


# ────────────────────────────────────────────────────────────────────────────
# Core backtest loop
def backtest_symbol(
    symbol: str,
    df_ltf: pd.DataFrame,
    df_htf: pd.DataFrame,
    df_ctf: Optional[pd.DataFrame],
    *,
    warmup_ltf: int = 250,
    stride: int = 1,
    max_bars_in_trade: int = 100,
    cooldown_bars: Optional[int] = None,
) -> tuple[BacktestMetrics, int]:
    """
    Walk through LTF bars with a growing slice, query SignalEngine.analyze().
    Once a signal fires, simulate it forward and skip ahead by `cooldown_bars`
    (default = MIN_BARS_BETWEEN_SIGNALS) before resuming.
    """
    metrics = BacktestMetrics()
    instrument = get_instrument(symbol)
    engine = SignalEngine(equity_fn=lambda: 1000.0, max_positions=1)

    if cooldown_bars is None:
        cooldown_bars = max(1, int(getattr(se, "MIN_BARS_BETWEEN_SIGNALS", 3)))

    n_total = len(df_ltf)
    n_signals = 0

    # Smaller windows to speed up SMC detectors that scan the whole slice.
    LTF_WINDOW = 80
    HTF_WINDOW = 220
    CTF_WINDOW = 120

    i = warmup_ltf
    while i < n_total - 1:
        ltf_start = max(0, i + 1 - LTF_WINDOW)
        ltf_slice = df_ltf.iloc[ltf_start: i + 1]
        ts_now = int(df_ltf.iloc[i]["ts"])

        htf_end = int(df_htf["ts"].searchsorted(ts_now + 1))
        if htf_end < 210:
            i += 1
            continue
        htf_start = max(0, htf_end - HTF_WINDOW)
        htf_slice = df_htf.iloc[htf_start:htf_end]

        ctf_slice = None
        if df_ctf is not None and len(df_ctf) > 0:
            ctf_end = int(df_ctf["ts"].searchsorted(ts_now + 1))
            if ctf_end >= 50:
                ctf_start = max(0, ctf_end - CTF_WINDOW)
                ctf_slice = df_ctf.iloc[ctf_start:ctf_end]

        try:
            sig = engine.analyze(
                symbol=symbol,
                df_htf=htf_slice,
                df_ltf=ltf_slice,
                df_ctf=ctf_slice,
                equity=1000.0,
                drawdown=0.0,
                open_count=0,
                instrument=instrument,
            )
        except Exception:
            sig = None

        if sig is not None:
            n_signals += 1
            win, pnl_r, exit_idx = simulate_trade(
                direction=sig.direction,
                entry_idx=i,
                entry_price=sig.entry,
                sl_price=sig.sl,
                tp_price=sig.tp,
                df_ltf=df_ltf,
                rr=sig.rr,
                max_bars=max_bars_in_trade,
            )
            tr = TradeResult(
                symbol=symbol,
                direction=sig.direction,
                entry_idx=i,
                entry_ts=int(df_ltf.iloc[i]["ts"]),
                exit_idx=exit_idx,
                entry_price=sig.entry,
                sl_price=sig.sl,
                tp_price=sig.tp,
                bars_held=exit_idx - i,
                win=win,
                profit_pct=pnl_r,  # in R-multiples
            )
            metrics.add(tr)
            # Reset engine state so it can fire again.  Mirrors the bot which
            # would close the trade and start watching again.
            engine._states[symbol].open_side = ""
            engine._states[symbol].bars_since_signal = 0
            i = max(exit_idx, i + cooldown_bars)
        else:
            i += stride

    # Days covered
    if n_total >= 2:
        ms_span = int(df_ltf.iloc[-1]["ts"]) - int(df_ltf.iloc[warmup_ltf]["ts"])
        metrics.days_covered = ms_span / (1000 * 60 * 60 * 24)
    return metrics, n_signals


def load_data(symbol: str, ltf: str = "15", htf: str = "240", ctf: str = "D",
              ltf_count: int = 5760, htf_count: int = 720, ctf_count: int = 200) -> tuple[pd.DataFrame, pd.DataFrame, Optional[pd.DataFrame]]:
    df_ltf = fetch_history(symbol, ltf, total_candles=ltf_count, use_cache=True)
    df_htf = fetch_history(symbol, htf, total_candles=htf_count, use_cache=True)
    df_ctf = fetch_history(symbol, ctf, total_candles=ctf_count, use_cache=True)

    df_ltf = compute_all(df_ltf.copy())
    df_htf = compute_all(df_htf.copy())
    df_ctf = compute_all(df_ctf.copy()) if not df_ctf.empty else None
    return df_ltf, df_htf, df_ctf


def run_backtest(
    symbols: list[str],
    overrides: dict,
    symbol_params: dict | None = None,
    *,
    stride: int = 1,
    max_bars_in_trade: int = 100,
    quiet: bool = False,
) -> tuple[BacktestMetrics, dict]:
    """Run backtest across multiple symbols.  Returns aggregate metrics + per-symbol stats."""
    saved = apply_overrides(overrides)
    saved_sp = apply_symbol_params(symbol_params or {})

    aggregate = BacktestMetrics()
    per_symbol: dict[str, dict] = {}

    try:
        for sym in symbols:
            t0 = time.time()
            df_ltf, df_htf, df_ctf = load_data(sym)
            # Use only the last `bars` LTF candles to bound runtime.
            bars = overrides.get("_window_ltf_bars", 2880)
            warmup = overrides.get("_warmup_ltf", 250)
            if len(df_ltf) > bars + warmup:
                df_ltf = df_ltf.iloc[-(bars + warmup):].reset_index(drop=True)
            m, raw_signals = backtest_symbol(
                sym, df_ltf, df_htf, df_ctf,
                stride=stride, max_bars_in_trade=max_bars_in_trade,
                warmup_ltf=warmup,
            )
            aggregate.days_covered = max(aggregate.days_covered, m.days_covered)
            for t in m.trades:
                aggregate.add(t)
            per_symbol[sym] = m.summary() | {
                "raw_signals": raw_signals,
                "elapsed_s": round(time.time() - t0, 1),
            }
            if not quiet:
                print(f"  [{sym}] {per_symbol[sym]}")
    finally:
        restore_overrides(saved)
        restore_symbol_params(saved_sp)

    return aggregate, per_symbol
