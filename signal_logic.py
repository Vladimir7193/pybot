"""
signal_logic.py — единый файл с полной логикой формирования сигналов.
Содержит: Signal, SymbolState, SignalEngine.
Dual-mode SMC: STRICT -> RELAXED fallback.
"""
from __future__ import annotations
import math
import time
import datetime
from collections import Counter
from dataclasses import dataclass
from typing import Optional

import pandas as pd
import config

from config import (
    SYMBOL_PARAMS,
    HOLONOMY_SENSITIVITY,
    ANOMALY_THRESHOLD,
    MIN_BARS_BETWEEN_SIGNALS,
    RISK_PER_TRADE,
    DD_WARNING, DD_DANGER,
    ENABLE_SMC, SMC_MODE, PURE_SMC,
    LIQUIDITY_SWEEP_LOOKBACK,
    FVG_MIN_SIZE_ATR, FVG_EXPIRY_CANDLES,
    OB_IMPULSE_THRESHOLD, OB_EXPIRY_CANDLES,
    PREMIUM_DISCOUNT_THRESHOLD,
    USE_SETUP_PATTERNS, SETUP_PATTERN_CONFIDENCE_MIN,
    USE_ORDER_FLOW, ORDERFLOW_SEQUENCE_REQUIRED,
    USE_KEY_LEVELS, KEY_LEVEL_IMPORTANCE_MIN,
    USE_FIBONACCI, FIBONACCI_USE_OTE,
    USE_AMD, AMD_TIMEFRAME,
    USE_KILL_ZONES, KILL_ZONE_REQUIRED,
    USE_MOMENTUM, MOMENTUM_REQUIRED,
    USE_RANGE_DETECTION, RANGE_AVOID_TRADING,
    CTF,
)
from smc_structure import StructureDetector
from smc_orderblock import OrderBlockDetector
from smc_fvg import FVGDetector
from smc_setup_patterns import SetupPatternDetector
from smc_orderflow import OrderFlowDetector
from smc_key_levels import KeyLevelsTracker
from smc_advanced import (
    AMDDetector, FibonacciCalculator, KillZoneDetector,
    RangeDetector, MomentumAnalyzer,
)
from logger import log


# ──────────────────────────────────────────────────────────────────────────────
@dataclass
class Signal:
    symbol:    str
    direction: str       # "Buy" | "Sell"
    entry:     float
    tp:        float
    sl:        float
    qty:       float
    rr:        float
    atr:       float
    sl_pct:    float
    tp_pct:    float
    reason:    str = ""
    mode:      str = "RELAXED"   # "STRICT" | "RELAXED" | "CLASSIC"


@dataclass
class SymbolState:
    symbol:            str
    bars_since_signal: int   = 999
    open_side:         str   = ""
    entry_price:       float = 0.0
    tp_price:          float = 0.0
    sl_price:          float = 0.0
    qty:               float = 0.0
    bars_held:         int   = 0
    breakeven_moved:   bool  = False
    entry_atr:         float = 0.0


# ──────────────────────────────────────────────────────────────────────────────
class SignalEngine:

    @staticmethod
    def _normalize_instrument(instrument: dict) -> dict:
        """Accept both flat and nested instrument formats."""
        if instrument is None:
            raise ValueError("instrument info is required")

        if all(k in instrument for k in ("min_qty", "qty_step", "price_tick")):
            return {
                "min_qty": float(instrument["min_qty"]),
                "qty_step": float(instrument["qty_step"]),
                "price_tick": float(instrument["price_tick"]),
            }

        lot = instrument.get("lotSizeFilter") or {}
        price = instrument.get("priceFilter") or {}
        min_qty = instrument.get("min_qty", lot.get("minOrderQty", lot.get("minTradingQty")))
        qty_step = instrument.get("qty_step", lot.get("qtyStep"))
        price_tick = instrument.get("price_tick", price.get("tickSize"))

        if min_qty is None or qty_step is None or price_tick is None:
            missing = [
                name for name, value in (("min_qty", min_qty), ("qty_step", qty_step), ("price_tick", price_tick))
                if value is None
            ]
            raise ValueError(f"instrument info missing fields: {', '.join(missing)}")

        return {
            "min_qty": float(min_qty),
            "qty_step": float(qty_step),
            "price_tick": float(price_tick),
        }

    def __init__(self, equity_fn, max_positions: int = 3):
        self._equity_fn     = equity_fn
        self._max_positions = max_positions
        self._states:                  dict[str, SymbolState]        = {}
        self._structure_detectors:     dict[str, StructureDetector]  = {}
        self._ob_detectors:            dict[str, OrderBlockDetector] = {}
        self._fvg_detectors:           dict[str, FVGDetector]        = {}
        self._setup_pattern_detectors: dict[str, SetupPatternDetector] = {}
        self._orderflow_detectors:     dict[str, OrderFlowDetector]  = {}
        self._key_levels_trackers:     dict[str, KeyLevelsTracker]   = {}
        self._ctf_detectors:           dict[str, StructureDetector]  = {}

        # ── Reject statistics ─────────────────────────────────────────────────
        self.reject_stats:       Counter = Counter()   # cumulative (all time)
        self.tick_reject_stats:  Counter = Counter()   # current tick only
        self.reject_details:     dict[str, list[str]] = {}  # recent reject trail per symbol
        self._stats_reset_day:   int     = -1          # for daily reset

    # ── helpers ───────────────────────────────────────────────────────────────
    def get_state(self, symbol: str) -> SymbolState:
        if symbol not in self._states:
            self._states[symbol] = SymbolState(symbol=symbol)
        return self._states[symbol]

    def _reject(self, symbol: str, reason: str, details: str = "") -> None:
        """Record reject reason and log it."""
        self.reject_stats[reason]      += 1
        self.tick_reject_stats[reason] += 1
        msg = f"[{symbol}] REJECT {reason}"
        if details:
            msg += f": {details}"
        trail = self.reject_details.setdefault(symbol, [])
        trail.append(f"{reason}: {details}" if details else reason)
        if len(trail) > 20:
            del trail[:-20]
        log.debug(msg)

    def log_reject_stats(self) -> None:
        """Print tick + cumulative reject stats. Call after each tick."""
        # Daily reset of cumulative counter
        today = datetime.datetime.now(datetime.timezone.utc).day
        if self._stats_reset_day != today:
            self.reject_stats.clear()
            self._stats_reset_day = today

        if self.tick_reject_stats:
            tick_str = ", ".join(
                f"{k}={v}" for k, v in self.tick_reject_stats.most_common()
            )
            log.info(f"📊 Tick rejects:  {tick_str}")

        if self.reject_stats:
            day_str = ", ".join(
                f"{k}={v}" for k, v in self.reject_stats.most_common(8)
            )
            log.info(f"📊 Daily rejects: {day_str}")

        # Top blocker hint
        if self.reject_stats:
            top, count = self.reject_stats.most_common(1)[0]
            hints = {
                "reject_htf_trend":  "рынок в боковике — норма, ждём структуру",
                "reject_range":      "рынок в ренджe — норма, ждём девиацию",
                "reject_holonomy":   "нет направленного движения на HTF",
                "reject_sweep":      "lookback слишком короткий или рынок без sweep",
                "reject_pd_zone":    "порог P/D слишком жёсткий, снизить threshold",
                "reject_entry_zone": "нет OB/FVG/Breaker/Mitigation — вход не подтверждён",
                "reject_setup:no_pattern": "нет setup pattern рядом с входом",
                "reject_setup:low_confidence": "паттерн найден, но confidence слишком низкий",
                "reject_orderflow":  "advanced-фильтры перефильтровывают",
                "reject_key_level:key_swing_block":  "ключевой swing держит цену против входа",
                "reject_key_level:fake_break":  "нет истинного слома структуры",
                "reject_qty_min":    "депозит слишком мал для минимального лота",
                "reject_ltf":        "LTF не подтверждает HTF направление",
                "reject_ctf":        "Daily bias против направления сигнала",
            }
            hint = hints.get(top, "")
            if hint:
                log.info(f"💡 Топ блокировка [{top}={count}]: {hint}")

        self.tick_reject_stats.clear()

    def _detectors(self, symbol: str):
        if symbol not in self._structure_detectors:
            self._structure_detectors[symbol]     = StructureDetector()
            self._ob_detectors[symbol]            = OrderBlockDetector(OB_IMPULSE_THRESHOLD, OB_EXPIRY_CANDLES)
            self._fvg_detectors[symbol]           = FVGDetector(FVG_MIN_SIZE_ATR, FVG_EXPIRY_CANDLES)
            self._setup_pattern_detectors[symbol] = SetupPatternDetector()
            self._orderflow_detectors[symbol]     = OrderFlowDetector()
            self._key_levels_trackers[symbol]     = KeyLevelsTracker()
        return (
            self._structure_detectors[symbol],
            self._ob_detectors[symbol],
            self._fvg_detectors[symbol],
            self._setup_pattern_detectors[symbol],
            self._orderflow_detectors[symbol],
            self._key_levels_trackers[symbol],
        )

    # ── main entry point ──────────────────────────────────────────────────────
    def analyze(
        self,
        symbol:     str,
        df_htf:     pd.DataFrame,
        df_ltf:     pd.DataFrame,
        equity:     float,
        drawdown:   float,
        open_count: int,
        instrument: dict,
        df_ctf:     Optional[pd.DataFrame] = None,
    ) -> Optional[Signal]:

        state = self.get_state(symbol)
        state.bars_since_signal += 1
        params = SYMBOL_PARAMS[symbol]
        instrument = self._normalize_instrument(instrument)

        # 1. Data guard
        if len(df_htf) < 210 or len(df_ltf) < 50:
            self._reject(symbol, "reject_data", f"htf={len(df_htf)} ltf={len(df_ltf)}")
            return None

        # 2. Already in position
        if state.open_side:
            return None  # not a filter reject, just state

        # 3. Max positions
        if open_count >= self._max_positions:
            return None  # not a filter reject

        # 4. Candle values
        htf     = df_htf.iloc[-2]
        ltf     = df_ltf.iloc[-2]
        price   = float(ltf["close"])
        atr_val = float(htf["atr"])
        atr_avg = float(htf["atr_avg"]) if not pd.isna(htf["atr_avg"]) else atr_val

        log.debug(f"[{symbol}] Analyzing: price={price:.4f}, atr={atr_val:.4f}")

        # 5. Holonomy
        holonomy = float(htf["holonomy"])
        if abs(holonomy) < HOLONOMY_SENSITIVITY:
            self._reject(symbol, "reject_holonomy", f"{holonomy:.4f}")
            return None

        # 6. Anomaly
        anomaly = float(htf["anomaly"]) if not pd.isna(htf["anomaly"]) else 1.0
        if anomaly > ANOMALY_THRESHOLD:
            self._reject(symbol, "reject_anomaly", f"{anomaly:.2f}")
            return None

        # 7. Signal separation
        if state.bars_since_signal < MIN_BARS_BETWEEN_SIGNALS:
            self._reject(symbol, "reject_separation", f"{state.bars_since_signal} bars")
            return None

        # ── vol_mult before any branch ────────────────────────────────────────
        vol_mult = atr_val / atr_avg if atr_avg > 0 else 1.0

        # 8. Direction
        if ENABLE_SMC and PURE_SMC:
            sd, *_ = self._detectors(symbol)
            bias = sd.resolve_trend(df_htf, use_closed_candle=True)
            if bias == "bullish":
                direction = "Buy"
            elif bias == "bearish":
                direction = "Sell"
            else:
                self._reject(symbol, "reject_htf_trend", f"pure_smc_unresolved={bias}")
                return None
        else:
            ema20     = float(htf["ema20"])
            ema50     = float(htf["ema50"])
            sma200    = float(htf["sma200"]) if not pd.isna(htf["sma200"]) else 0.0
            rsi       = float(htf["rsi"])
            htf_price = float(htf["close"])
            bullish   = htf_price > sma200 and htf_price > ema20 > ema50 and rsi > 50
            bearish   = htf_price < sma200 and htf_price < ema20 < ema50 and rsi < 50
            if not bullish and not bearish:
                self._reject(symbol, "reject_htf_trend", f"rsi={rsi:.1f}")
                return None
            ltf_hol = float(ltf["holonomy"])
            ltf_rsi = float(ltf["rsi"])
            if bullish and (ltf_hol < 0 or ltf_rsi < 45):
                self._reject(symbol, "reject_ltf", f"hol={ltf_hol:.3f} rsi={ltf_rsi:.1f}")
                return None
            if bearish and (ltf_hol > 0 or ltf_rsi > 55):
                self._reject(symbol, "reject_ltf", f"hol={ltf_hol:.3f} rsi={ltf_rsi:.1f}")
                return None
            direction = "Buy" if bullish else "Sell"

        # 9. SMC dual-mode filters
        reason      = ""
        signal_mode = "CLASSIC"

        if ENABLE_SMC:
            current_mode = str(config.SMC_MODE).upper()
            mode_order = ["STRICT", "RELAXED"] if current_mode == "STRICT" else ["RELAXED", "STRICT"]
            selected_result = None
            selected_mode = None
            for mode in mode_order:
                result = self._apply_smc_filters(
                    symbol, df_htf, df_ltf, df_ctf, price, direction, atr_val, mode)
                if result is not None:
                    selected_result = result
                    selected_mode = mode
                    break
            if selected_result is None or selected_mode is None:
                return None
            reason, signal_mode = selected_result, selected_mode
        else:
            # CLASSIC — vol_mult already defined above (bug #5 fix)
            reason = (
                f"HTF {'bullish' if direction=='Buy' else 'bearish'} | "
                f"Hol={holonomy:.3f} | ATR={atr_val:.4f} | VolMult={vol_mult:.2f}"
            )
            signal_mode = "CLASSIC"

        # 10. TP/SL sizing
        sl_mult = params["sl_mult"]
        tp_mult = params["tp_mult"]
        if vol_mult > 1.3:
            tp_mult *= 0.85
        elif vol_mult < 0.7:
            tp_mult *= 1.15

        sl_dist = atr_val * sl_mult
        tp_dist = atr_val * tp_mult

        if direction == "Buy":
            sl_price = price - sl_dist
            tp_price = price + tp_dist
        else:
            sl_price = price + sl_dist
            tp_price = price - tp_dist

        rr = tp_dist / sl_dist

        # 11. Position sizing
        risk_mult = 1.0
        if drawdown > DD_DANGER:
            risk_mult = 0.5
        elif drawdown > DD_WARNING:
            risk_mult = 0.75

        effective_risk = RISK_PER_TRADE * risk_mult
        risk_usdt      = equity * effective_risk
        qty_raw        = risk_usdt / sl_dist

        qty_step = instrument["qty_step"]
        min_qty  = instrument["min_qty"]
        qty      = math.floor(qty_raw / qty_step) * qty_step
        qty      = round(qty, 8)

        if qty < min_qty:
            self._reject(symbol, "reject_qty_min",
                         f"qty={qty_raw:.4f} min={min_qty} equity={equity:.2f}")
            return None

        sl_pct = abs(price - sl_price) / price * 100
        tp_pct = abs(tp_price - price) / price * 100
        state.bars_since_signal = 0

        sig = Signal(
            symbol=symbol, direction=direction,
            entry=price, tp=tp_price, sl=sl_price,
            qty=qty, rr=rr, atr=atr_val,
            sl_pct=sl_pct, tp_pct=tp_pct,
            reason=reason, mode=signal_mode,
        )

        mode_emoji = "🔥" if signal_mode == "STRICT" else "⚡" if signal_mode == "RELAXED" else "📊"
        log.info(
            f"\n{'='*60}\n"
            f"  🚀 SIGNAL [{signal_mode}] {mode_emoji}  {symbol}  "
            f"{'LONG 🟢' if direction=='Buy' else 'SHORT 🔴'}\n"
            f"{'='*60}\n"
            f"  Mode:       {signal_mode} {mode_emoji}\n"
            f"  Entry:      {price:.4f}\n"
            f"  TP:         {tp_price:.4f}  (+{tp_pct:.2f}%)\n"
            f"  SL:         {sl_price:.4f}  (-{sl_pct:.2f}%)\n"
            f"  RR:         1:{rr:.2f}\n"
            f"  Qty:        {qty}\n"
            f"  ATR(4h):    {atr_val:.4f}  (avg={atr_avg:.4f}, mult={vol_mult:.2f})\n"
            f"  Reason:     {reason}\n"
            f"  Risk:       {risk_usdt:.2f} USDT ({effective_risk*100:.1f}% × {risk_mult})\n"
            f"{'='*60}"
        )
        return sig

    # ── SMC filters ───────────────────────────────────────────────────────────
    def _apply_smc_filters(
        self,
        symbol:     str,
        df_htf:     pd.DataFrame,
        df_ltf:     pd.DataFrame,
        df_ctf:     Optional[pd.DataFrame],
        price:      float,
        direction:  str,
        atr_val:    float,
        force_mode: str = "STRICT",
    ) -> Optional[str]:
        """
        Returns reason string if all required filters pass, else None.
        BUG #2 FIX: bos is always a StructureBreak object (or None), never a list.
        BUG #3 FIX: PREMIUM_DISCOUNT_THRESHOLD = 0.45 (relaxed from 0.5).
        BUG #4 FIX: KEY_LEVEL_IMPORTANCE_MIN = 0.9 (less aggressive blocking).
        """
        t0 = time.time()

        struct_det, ob_det, fvg_det, setup_det, orderflow_det, key_levels = \
            self._detectors(symbol)

        n_htf = len(df_htf) - 1
        n_ltf = len(df_ltf) - 1
        checks: list[str] = []
        is_strict = (force_mode == "STRICT")
        is_relaxed = (force_mode == "RELAXED")

        # ── CTF (Daily) bias ──────────────────────────────────────────────────
        ctf_zones: list = []
        if df_ctf is not None and len(df_ctf) >= 50:
            if symbol not in self._ctf_detectors:
                self._ctf_detectors[symbol] = StructureDetector()
            ctf_sd = self._ctf_detectors[symbol]
            ctf_bias = ctf_sd.resolve_trend(df_ctf, use_closed_candle=True)

            ctf_fvg = FVGDetector(min_size_atr=0.3, expiry_candles=200)
            ctf_fvg.detect_fvgs(df_ctf)
            ctf_fvg.update_fill_status(df_ctf)
            for fvg in ctf_fvg.fvgs:
                if fvg.fill_percentage < 0.5:
                    ctf_zones.append({"high": fvg.high, "low": fvg.low,
                                      "type": "fvg", "tf": "D"})

            if ctf_bias and ctf_bias != "ranging":
                match = (direction == "Buy"  and ctf_bias == "bullish") or \
                        (direction == "Sell" and ctf_bias == "bearish")
                checks.append(f"CTF✓({ctf_bias})" if match else f"CTF✗({ctf_bias})")
                if not match and is_strict:
                    self._reject(symbol, "reject_ctf", f"bias={ctf_bias} dir={direction}")
                    return None
            else:
                checks.append("CTF~")

        # ── Range detection ───────────────────────────────────────────────────
        if USE_RANGE_DETECTION:
            rng = RangeDetector.detect_range(df_htf, max(0, n_htf - 40), lookback=40)
            if rng is not None:
                dev = RangeDetector.detect_deviation(df_htf, rng, n_htf)
                if dev and dev["returned_to_range"]:
                    expected = "Buy" if dev["direction"] == "below" else "Sell"
                    if direction == expected:
                        checks.append(f"RngDev✓({dev['direction']})")
                    else:
                        checks.append("RngDev✗")
                        if is_strict:
                            self._reject(symbol, "reject_range:deviation_mismatch", "deviation direction mismatch")
                            return None
                elif RANGE_AVOID_TRADING:
                    if is_strict:
                        self._reject(symbol, "reject_range:inside_range", "inside range, no deviation")
                        return None
                    checks.append("Range~")

        # ── Kill Zone ─────────────────────────────────────────────────────────
        if USE_KILL_ZONES:
            ts = int(df_ltf.iloc[-1]["ts"])
            kz = KillZoneDetector.get_current_kill_zone(ts)
            if kz:
                checks.append(f"KZ:{kz}")
            elif KILL_ZONE_REQUIRED:
                self._reject(symbol, "reject_killzone", "outside kill zone")
                return None
            else:
                checks.append("KZ✗")

        # ── CHECK 1: BOS / CHoCH ──────────────────────────────────────────────
        struct_det.detect_swings(df_htf)
        # BUG #2 FIX: detect_bos returns StructureBreak | None (not a list)
        bos: Optional[object] = struct_det.detect_bos(df_htf)

        trend_ok = (direction == "Buy"  and struct_det.trend == "bullish") or \
                   (direction == "Sell" and struct_det.trend == "bearish")
        if trend_ok:
            bos_label = bos.type if bos else "BOS"   # type: ignore[union-attr]
            checks.append(f"{bos_label}✓")
        else:
            checks.append(f"BOS✗({struct_det.trend})")
            if is_strict:
                self._reject(symbol, "reject_htf_trend", f"trend={struct_det.trend} dir={direction}")
                return None

        # ── CHECK 2: Liquidity Sweep ──────────────────────────────────────────
        sweep = struct_det.check_liquidity_sweep(df_htf, lookback=LIQUIDITY_SWEEP_LOOKBACK)
        sweep_ok = (direction == "Buy"  and sweep == "bullish_sweep") or \
                   (direction == "Sell" and sweep == "bearish_sweep")
        checks.append("Sweep✓" if sweep_ok else "Sweep✗")
        if not sweep_ok and is_strict:
            self._reject(symbol, "reject_sweep", f"sweep={sweep}")
            return None

        # ── CHECK 3: Premium / Discount (always required) ─────────────────────
        # BUG #3 FIX: use actual config value (0.45 in config.py)
        pd_ratio = struct_det.get_premium_discount_ratio(price, df_htf)
        if direction == "Buy":
            if pd_ratio < PREMIUM_DISCOUNT_THRESHOLD:
                checks.append(f"Discount✓({pd_ratio:.2f})")
            else:
                self._reject(symbol, "reject_pd_zone", f"pd_ratio={pd_ratio:.2f} need<{PREMIUM_DISCOUNT_THRESHOLD}")
                return None
        else:
            if pd_ratio > (1.0 - PREMIUM_DISCOUNT_THRESHOLD):
                checks.append(f"Premium✓({pd_ratio:.2f})")
            else:
                self._reject(symbol, "reject_pd_zone", f"pd_ratio={pd_ratio:.2f} need>{1.0-PREMIUM_DISCOUNT_THRESHOLD:.2f}")
                return None

        range_high = struct_det.get_range_high(df_htf)
        range_low  = struct_det.get_range_low(df_htf)

        # ── Fibonacci OTE ─────────────────────────────────────────────────────
        if USE_FIBONACCI and FIBONACCI_USE_OTE:
            fib = FibonacciCalculator.calculate_levels(range_high, range_low)
            if FibonacciCalculator.is_in_ote_zone(price, fib):
                checks.append("OTE✓")
            else:
                self._reject(symbol, "reject_fibonacci", f"price={price:.4f} not in OTE")
                return None

        # ── AMD ───────────────────────────────────────────────────────────────
        if USE_AMD:
            amd = AMDDetector.detect_amd_on_candle(df_htf, n_htf, AMD_TIMEFRAME)
            if amd and amd.distribution_direction == direction.lower():
                checks.append("AMD✓")
            elif amd:
                checks.append("AMD✗")
                if is_strict:
                    self._reject(symbol, "reject_amd", f"amd_dir={amd.distribution_direction}")
                    return None
            else:
                checks.append("AMD~")

        # ── Momentum ──────────────────────────────────────────────────────────
        if USE_MOMENTUM:
            imp_mom  = MomentumAnalyzer.calculate_momentum(df_htf, max(0, n_htf - 10), n_htf)
            corr_mom = MomentumAnalyzer.calculate_momentum(df_htf, max(0, n_htf - 20), max(0, n_htf - 10))
            mom_res  = MomentumAnalyzer.compare_impulse_vs_correction(imp_mom, corr_mom)
            if direction.lower() in mom_res:
                checks.append("Mom✓")
            elif MOMENTUM_REQUIRED:
                self._reject(symbol, "reject_momentum", f"mom={mom_res}")
                return None
            else:
                checks.append("Mom✗")

        # ── Prepare shared data ───────────────────────────────────────────────
        liq_sweeps: list = []
        for i in range(max(0, n_ltf - 20), n_ltf + 1):
            liq_sweeps.extend(orderflow_det.track_liquidity_sweeps(df_ltf, i))

        zones: list = list(ctf_zones)
        for fvg in fvg_det.fvgs:
            if fvg.fill_percentage < 0.5:
                zones.append({"high": fvg.high, "low": fvg.low,
                               "index": fvg.index, "type": "fvg"})

        # BUG #2 FIX: bos is StructureBreak object, build list correctly
        sb_list: list = []
        if bos is not None:
            sb_list.append({
                "index":     bos.index,      # type: ignore[union-attr]
                "price":     bos.price,      # type: ignore[union-attr]
                "direction": bos.direction,  # type: ignore[union-attr]
                "type":      bos.type,       # type: ignore[union-attr]
            })

        # ── CHECK 4: Entry Zone ───────────────────────────────────────────────
        ob_det.detect_order_blocks(df_ltf,
            liquidity_sweeps=liq_sweeps,
            zones_of_interest=zones,
            structure_breaks=sb_list)
        breakers = ob_det.detect_breaker_blocks(df_ltf)

        sd_ltf = StructureDetector()
        sd_ltf.detect_swings(df_ltf)
        mitigations = ob_det.detect_mitigation_blocks(
            df_ltf, sd_ltf.swings_high, sd_ltf.swings_low)
        ob_det.cleanup_expired(n_ltf)

        breaker    = ob_det.is_price_in_breaker(price, direction.lower(), n_ltf)
        mitigation = ob_det.is_price_in_mitigation(price, direction.lower(), n_ltf)
        ob         = ob_det.is_price_in_order_block(price, direction.lower(), n_ltf)

        fvg_det.detect_fvgs(df_ltf, liquidity_sweep_indices=[])
        fvg_det.update_fill_status(df_ltf)
        fvg_det.cleanup_expired(n_ltf)
        fvg = fvg_det.is_price_in_fvg(price, direction.lower(), n_ltf)

        if breaker:
            checks.append("Breaker✓")
        elif mitigation:
            checks.append("Mitigation✓")
        elif ob:
            checks.append("OB✓")
        elif fvg:
            checks.append("FVG✓")
        else:
            checks.append("NoZone")
            if is_strict:
                self._reject(symbol, "reject_entry_zone:no_zone", "no Breaker/Mitigation/OB/FVG")
                return None

        # ── Setup Patterns ────────────────────────────────────────────────────
        pat = None
        if USE_SETUP_PATTERNS:
            setup_det.detect_all_patterns(df_ltf,
                liquidity_sweeps=liq_sweeps,
                zones_of_interest=zones,
                structure_breaks=sb_list)
            pat = setup_det.get_latest_pattern(n_ltf, lookback=5)
            if pat:
                if pat.confidence >= SETUP_PATTERN_CONFIDENCE_MIN:
                    checks.append(f"{pat.pattern_type}✓")
                else:
                    checks.append(f"{pat.pattern_type}✗")
                    if is_strict:
                        self._reject(symbol, "reject_setup:low_confidence", f"conf={pat.confidence:.2f}<{SETUP_PATTERN_CONFIDENCE_MIN}")
                        return None
            else:
                checks.append("NoSetup")
                if is_strict:
                    self._reject(symbol, "reject_setup:no_pattern", "no pattern found")
                    return None

        # ── Order Flow ────────────────────────────────────────────────────────
        if USE_ORDER_FLOW:
            orderflow_det.detect_liquidity_pools(df_ltf,
                swings_high=sd_ltf.swings_high,
                swings_low=sd_ltf.swings_low,
                trading_range_high=range_high,
                trading_range_low=range_low)
            orderflow_det.detect_order_flow_sequence(df_ltf, sb_list)
            valid_flow = orderflow_det.is_valid_order_flow(n_ltf, direction.lower())
            if valid_flow:
                checks.append("Flow✓")
            elif ORDERFLOW_SEQUENCE_REQUIRED:
                self._reject(symbol, "reject_orderflow", "sequence required but not found")
                return None
            else:
                checks.append("Flow✗")

        # ── Key Levels ("что держит цену") ────────────────────────────────────
        # BUG #4 FIX: KEY_LEVEL_IMPORTANCE_MIN = 0.9 in config (less blocking)
        true_break_ok = False
        if USE_KEY_LEVELS:
            key_levels.update_all_levels(df_ltf,
                swings_high=sd_ltf.swings_high,
                swings_low=sd_ltf.swings_low,
                structure_breaks=sb_list,
                order_blocks=ob_det.order_blocks,
                fvgs=fvg_det.fvgs,
                breakers=breakers,
                mitigations=mitigations,
                equal_highs=struct_det.get_equal_highs(),
                equal_lows=struct_det.get_equal_lows())
            key_levels.mark_tested(df_ltf, n_ltf)

            holding = key_levels.what_holds_price(price, direction.lower())
            if (holding and holding.importance >= KEY_LEVEL_IMPORTANCE_MIN
                    and holding.level_type == "key_swing"):
                self._reject(symbol, "reject_key_level:key_swing_block",
                             f"{holding.level_type}@{holding.price:.4f} imp={holding.importance:.2f}")
                return None

            true_break_ok = key_levels.is_true_structure_break(price, direction.lower())
            if true_break_ok:
                checks.append("TrueBreak✓")
            else:
                checks.append("FakeBreak✗")
                if is_strict:
                    self._reject(symbol, "reject_key_level:fake_break", "fake structure break")
                    return None

        # ── RELAXED minimum SMC core ─────────────────────────────────────────
        if is_relaxed:
            zone_ok = any((breaker, mitigation, ob, fvg))
            setup_ok = False
            if USE_SETUP_PATTERNS:
                setup_ok = pat is not None and pat.confidence >= SETUP_PATTERN_CONFIDENCE_MIN
            confirmation_ok = bool(sweep_ok or setup_ok or true_break_ok)

            if not trend_ok:
                self._reject(symbol, "reject_relaxed:trend", f"trend={struct_det.trend} dir={direction}")
                return None
            if not zone_ok:
                self._reject(symbol, "reject_relaxed:zone", "relaxed mode still requires entry zone")
                return None
            if not confirmation_ok:
                self._reject(symbol, "reject_relaxed:confirmation", "need sweep/setup/true_break")
                return None

        # ── Done ──────────────────────────────────────────────────────────────
        elapsed = time.time() - t0
        if elapsed > 1.0:
            log.warning(f"[{symbol}] SMC filters slow: {elapsed:.2f}s")

        status = " ".join(checks)
        reason = f"SMC-{force_mode} {direction} | {status} | ATR={atr_val:.4f}"
        log.info(f"[{symbol}] SMC {force_mode}: {status} ({elapsed*1000:.0f}ms)")
        return reason
