"""
Fast SMC backtester.  Mirrors the production SignalEngine logic but does
heavy work (swing/structure/FVG detection) ONCE on the full series and uses
cheap O(1) lookups per LTF bar.

This is an approximation of the production code path used purely for
parameter optimization.  Top candidates should be re-validated against the
slow `signal_engine.SignalEngine` on a small sample to make sure the gain
is real.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

import config
from indicators import compute_all
from okx_klines import fetch_history


# ────────────────────────────────────────────────────────────────────────────
@dataclass
class Trade:
    symbol: str
    direction: str
    entry_idx: int
    entry_ts: int
    entry: float
    sl: float
    tp: float
    exit_idx: int
    bars_held: int
    win: bool
    pnl_r: float                      # P&L in R-multiples (1R = SL distance)


@dataclass
class Stats:
    trades: list[Trade] = field(default_factory=list)
    days_covered: float = 0.0
    rejects: dict[str, int] = field(default_factory=dict)
    raw_signals: int = 0

    def add(self, t: Trade) -> None:
        self.trades.append(t)

    @property
    def n(self) -> int:
        return len(self.trades)

    @property
    def wins(self) -> int:
        return sum(1 for t in self.trades if t.win)

    @property
    def win_rate(self) -> float:
        return (self.wins / self.n * 100) if self.n else 0.0

    @property
    def total_r(self) -> float:
        return sum(t.pnl_r for t in self.trades)

    @property
    def total_profit_r(self) -> float:
        return sum(t.pnl_r for t in self.trades if t.pnl_r > 0)

    @property
    def total_loss_r(self) -> float:
        return sum(-t.pnl_r for t in self.trades if t.pnl_r < 0)

    @property
    def profit_factor(self) -> float:
        if self.total_loss_r > 0:
            return self.total_profit_r / self.total_loss_r
        return float("inf") if self.total_profit_r > 0 else 0.0

    @property
    def expectancy_r(self) -> float:
        return self.total_r / self.n if self.n else 0.0

    @property
    def trades_per_day(self) -> float:
        return self.n / self.days_covered if self.days_covered > 0 else 0.0

    @property
    def max_dd_r(self) -> float:
        eq = 0.0
        peak = 0.0
        worst = 0.0
        for t in self.trades:
            eq += t.pnl_r
            peak = max(peak, eq)
            worst = max(worst, peak - eq)
        return worst

    def summary(self) -> dict:
        pf = self.profit_factor
        return {
            "trades": self.n,
            "wins": self.wins,
            "win_rate_%": round(self.win_rate, 1),
            "profit_factor": "inf" if pf == float("inf") else round(pf, 2),
            "expectancy_R": round(self.expectancy_r, 3),
            "total_R": round(self.total_r, 2),
            "max_dd_R": round(self.max_dd_r, 2),
            "days": round(self.days_covered, 1),
            "trades_per_day": round(self.trades_per_day, 2),
        }


# ────────────────────────────────────────────────────────────────────────────
# Pre-computation
def _detect_swings_fast(high: np.ndarray, low: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """5-candle swing high/low pattern.  Returns boolean masks aligned with `high`/`low`."""
    n = len(high)
    sh = np.zeros(n, dtype=bool)
    sl = np.zeros(n, dtype=bool)
    for i in range(2, n - 2):
        if (high[i] > high[i - 1] and high[i] > high[i - 2]
                and high[i] > high[i + 1] and high[i] > high[i + 2]):
            sh[i] = True
        if (low[i] < low[i - 1] and low[i] < low[i - 2]
                and low[i] < low[i + 1] and low[i] < low[i + 2]):
            sl[i] = True
    return sh, sl


def _detect_fvgs_fast(prev_high: np.ndarray, prev_low: np.ndarray,
                      next_high: np.ndarray, next_low: np.ndarray,
                      atr: np.ndarray, min_size_atr: float) -> tuple[list, list]:
    """
    Returns (bull_fvgs, bear_fvgs); each is a list of dicts:
      {'idx': int, 'high': float, 'low': float}
    """
    n = len(prev_high)
    bull = []
    bear = []
    for i in range(1, n - 1):
        a = atr[i]
        if a <= 0 or np.isnan(a):
            continue
        # Bullish: prev.high < next.low
        if prev_high[i - 1] < next_low[i + 1]:
            sz = float(next_low[i + 1] - prev_high[i - 1])
            if sz >= min_size_atr * a:
                bull.append({"idx": i, "high": float(next_low[i + 1]),
                             "low": float(prev_high[i - 1])})
        # Bearish: prev.low > next.high
        if prev_low[i - 1] > next_high[i + 1]:
            sz = float(prev_low[i - 1] - next_high[i + 1])
            if sz >= min_size_atr * a:
                bear.append({"idx": i, "high": float(prev_low[i - 1]),
                             "low": float(next_high[i + 1])})
    return bull, bear


def _detect_obs_fast(o: np.ndarray, h: np.ndarray, l: np.ndarray, c: np.ndarray,
                     atr: np.ndarray, impulse_threshold: float) -> tuple[list, list]:
    """
    Lightweight Order Block detection:
      - Bullish OB: last bearish candle (close<open) immediately before a
        sequence of K bullish candles whose total range >= impulse_threshold * ATR.
      - Bearish OB: mirror.
    Returns (bull_obs, bear_obs) as lists of {'idx', 'high', 'low'}.
    """
    n = len(o)
    bull = []
    bear = []
    K = 3  # look at next 3 candles for impulse
    for i in range(1, n - K - 1):
        a = atr[i]
        if a <= 0 or np.isnan(a):
            continue
        # Bullish impulse over next K candles
        impulse_up = c[i + K] - o[i + 1]
        impulse_dn = o[i + 1] - c[i + K]
        # bearish candle at i?
        if c[i] < o[i] and impulse_up >= impulse_threshold * a:
            bull.append({"idx": i, "high": float(h[i]), "low": float(l[i])})
        if c[i] > o[i] and impulse_dn >= impulse_threshold * a:
            bear.append({"idx": i, "high": float(h[i]), "low": float(l[i])})
    return bull, bear


def _trend_series_from_swings(sh_idx: list[int], sh_price: list[float],
                              sl_idx: list[int], sl_price: list[float],
                              n_bars: int) -> np.ndarray:
    """
    Build a trend label per HTF bar from confirmed swings.

    Trend at bar i:
      * Look at swings with index <= i - 2 (5-bar pattern is 2 bars late).
      * Use latest 2 highs and 2 lows.
      * bullish if HH+HL, bearish if LL+LH, else carry previous trend.
    Trend states: 0=ranging, 1=bullish, -1=bearish.
    """
    trend = np.zeros(n_bars, dtype=np.int8)
    cur = 0
    h_ptr = 0
    l_ptr = 0
    sh_idx_arr = np.asarray(sh_idx)
    sl_idx_arr = np.asarray(sl_idx)
    for i in range(n_bars):
        cutoff = i - 2
        # advance pointers
        while h_ptr < len(sh_idx_arr) and sh_idx_arr[h_ptr] <= cutoff:
            h_ptr += 1
        while l_ptr < len(sl_idx_arr) and sl_idx_arr[l_ptr] <= cutoff:
            l_ptr += 1
        # latest two of each
        if h_ptr >= 2 and l_ptr >= 2:
            last_h = sh_price[h_ptr - 1]
            prev_h = sh_price[h_ptr - 2]
            last_l = sl_price[l_ptr - 1]
            prev_l = sl_price[l_ptr - 2]
            if last_h > prev_h and last_l > prev_l:
                cur = 1
            elif last_h < prev_h and last_l < prev_l:
                cur = -1
        trend[i] = cur
    return trend


@dataclass
class PrecomputedSymbol:
    symbol: str
    df_ltf: pd.DataFrame
    df_htf: pd.DataFrame
    htf_to_ltf_idx: np.ndarray   # HTF[i] active for LTF bars [htf_to_ltf_idx[i]:htf_to_ltf_idx[i+1])
    ltf_to_htf_idx: np.ndarray   # ltf_to_htf_idx[j] = HTF index whose closed candle covers LTF[j]
    htf_trend: np.ndarray        # 1/-1/0 per HTF bar
    htf_range_high: np.ndarray   # rolling max swing high (last K) per HTF bar
    htf_range_low:  np.ndarray
    htf_recent_high: np.ndarray  # rolling max(high) over last sweep_lookback HTF bars
    htf_recent_low:  np.ndarray
    htf_eq_high: np.ndarray      # last equal-highs price (~same level seen twice)
    htf_eq_low:  np.ndarray
    bull_fvgs: list              # list of dicts with idx,high,low
    bear_fvgs: list
    bull_obs:  list
    bear_obs:  list


def precompute_symbol(symbol: str,
                      ltf_count: int = 5760, htf_count: int = 720,
                      fvg_min_size_atr: float = 0.3,
                      ob_impulse_threshold: float = 2.0) -> PrecomputedSymbol:
    df_ltf = fetch_history(symbol, "15", total_candles=ltf_count, use_cache=True)
    df_htf = fetch_history(symbol, "240", total_candles=htf_count, use_cache=True)
    df_ltf = compute_all(df_ltf.copy())
    df_htf = compute_all(df_htf.copy())

    # ── Map LTF bars → HTF bar (last closed HTF bar that covers the LTF bar)
    htf_ts = df_htf["ts"].to_numpy()
    ltf_ts = df_ltf["ts"].to_numpy()
    # Each HTF bar at htf_ts[i] starts at htf_ts[i] and ends at htf_ts[i] + 4h.
    # An LTF bar at time t belongs to the HTF bar with the largest start <= t.
    ltf_to_htf = np.searchsorted(htf_ts, ltf_ts, side="right") - 1
    ltf_to_htf = np.clip(ltf_to_htf, 0, len(htf_ts) - 1)

    # ── HTF swings
    h = df_htf["high"].to_numpy()
    l = df_htf["low"].to_numpy()
    c = df_htf["close"].to_numpy()

    sh_mask, sl_mask = _detect_swings_fast(h, l)
    sh_idx = np.where(sh_mask)[0].tolist()
    sl_idx = np.where(sl_mask)[0].tolist()
    sh_price = [float(h[i]) for i in sh_idx]
    sl_price = [float(l[i]) for i in sl_idx]

    htf_trend = _trend_series_from_swings(
        sh_idx, sh_price, sl_idx, sl_price, len(df_htf))

    # ── HTF trading range = max of last K swing highs / min of last K swing lows.
    # K=4 keeps it stable but adaptive.
    K = 4
    range_high = np.full(len(df_htf), np.nan)
    range_low = np.full(len(df_htf), np.nan)
    for i in range(len(df_htf)):
        cutoff = i - 2
        h_visible = [p for j, p in zip(sh_idx, sh_price) if j <= cutoff]
        l_visible = [p for j, p in zip(sl_idx, sl_price) if j <= cutoff]
        if len(h_visible) >= 1 and len(l_visible) >= 1:
            range_high[i] = max(h_visible[-K:])
            range_low[i] = min(l_visible[-K:])

    # ── HTF rolling high/low for sweep detection
    sweep_lb = int(getattr(config, "LIQUIDITY_SWEEP_LOOKBACK", 10))
    h_series = df_htf["high"]
    l_series = df_htf["low"]
    htf_recent_high = h_series.rolling(sweep_lb, min_periods=1).max().to_numpy()
    htf_recent_low = l_series.rolling(sweep_lb, min_periods=1).min().to_numpy()

    # ── Equal highs / lows: take all swing pairs within tolerance and store
    # the latest such level visible at each HTF bar.
    tol = 0.002
    eq_high = np.full(len(df_htf), np.nan)
    eq_low = np.full(len(df_htf), np.nan)
    # Identify pairs: for each new swing high, check if any earlier swing high
    # is within tol; if so, the level becomes an equal-high.
    last_eq_h = np.nan
    sh_arr_idx = sh_idx
    sh_arr_pr = sh_price
    for k, idx in enumerate(sh_arr_idx):
        for j in range(k):
            if abs(sh_arr_pr[k] - sh_arr_pr[j]) / max(sh_arr_pr[j], 1e-9) < tol:
                last_eq_h = max(sh_arr_pr[k], sh_arr_pr[j])
                break
        # All HTF bars from idx+2 (when we 'see' the new swing) onward inherit
        # `last_eq_h` until a new equal-high appears.
        if not np.isnan(last_eq_h):
            for b in range(idx + 2, len(df_htf)):
                if np.isnan(eq_high[b]) or eq_high[b] != last_eq_h:
                    eq_high[b] = last_eq_h

    last_eq_l = np.nan
    for k, idx in enumerate(sl_idx):
        for j in range(k):
            if abs(sl_price[k] - sl_price[j]) / max(sl_price[j], 1e-9) < tol:
                last_eq_l = min(sl_price[k], sl_price[j])
                break
        if not np.isnan(last_eq_l):
            for b in range(idx + 2, len(df_htf)):
                if np.isnan(eq_low[b]) or eq_low[b] != last_eq_l:
                    eq_low[b] = last_eq_l

    # ── LTF FVGs and OBs (one-shot detection on full series)
    ltf_o = df_ltf["open"].to_numpy()
    ltf_h = df_ltf["high"].to_numpy()
    ltf_l = df_ltf["low"].to_numpy()
    ltf_c = df_ltf["close"].to_numpy()
    ltf_atr = df_ltf["atr"].to_numpy()

    bull_fvgs, bear_fvgs = _detect_fvgs_fast(
        ltf_h, ltf_l, ltf_h, ltf_l, ltf_atr, fvg_min_size_atr
    )
    bull_obs, bear_obs = _detect_obs_fast(
        ltf_o, ltf_h, ltf_l, ltf_c, ltf_atr, ob_impulse_threshold
    )

    # htf_to_ltf_idx[i] = first LTF index that maps to HTF[i]
    htf_to_ltf_first = np.searchsorted(ltf_to_htf, np.arange(len(df_htf)), side="left")

    return PrecomputedSymbol(
        symbol=symbol, df_ltf=df_ltf, df_htf=df_htf,
        htf_to_ltf_idx=htf_to_ltf_first,
        ltf_to_htf_idx=ltf_to_htf,
        htf_trend=htf_trend,
        htf_range_high=range_high, htf_range_low=range_low,
        htf_recent_high=htf_recent_high, htf_recent_low=htf_recent_low,
        htf_eq_high=eq_high, htf_eq_low=eq_low,
        bull_fvgs=bull_fvgs, bear_fvgs=bear_fvgs,
        bull_obs=bull_obs, bear_obs=bear_obs,
    )


# ────────────────────────────────────────────────────────────────────────────
# Trade simulation helpers
def _simulate(direction: str, entry_idx: int, entry: float, sl: float, tp: float,
              ltf_h: np.ndarray, ltf_l: np.ndarray, ltf_c: np.ndarray,
              max_bars: int) -> tuple[bool, float, int]:
    end = min(entry_idx + max_bars, len(ltf_h))
    rr = abs(tp - entry) / max(abs(entry - sl), 1e-9)
    for j in range(entry_idx + 1, end):
        if direction == "Buy":
            sl_hit = ltf_l[j] <= sl
            tp_hit = ltf_h[j] >= tp
            if sl_hit and tp_hit:
                return False, -1.0, j
            if sl_hit:
                return False, -1.0, j
            if tp_hit:
                return True, rr, j
        else:
            sl_hit = ltf_h[j] >= sl
            tp_hit = ltf_l[j] <= tp
            if sl_hit and tp_hit:
                return False, -1.0, j
            if sl_hit:
                return False, -1.0, j
            if tp_hit:
                return True, rr, j
    # Time-stop: close at last bar's close
    last_close = ltf_c[end - 1]
    if direction == "Buy":
        pnl = (last_close - entry) / max(abs(entry - sl), 1e-9)
    else:
        pnl = (entry - last_close) / max(abs(entry - sl), 1e-9)
    return pnl > 0, float(pnl), end - 1


# ────────────────────────────────────────────────────────────────────────────
def backtest(
    pre: PrecomputedSymbol,
    *,
    sl_mult: float,
    tp_mult: float,
    pd_threshold: float,
    sweep_lookback: int,
    holonomy_sensitivity: float,
    min_bars_between_signals: int,
    require_entry_zone: bool = True,
    require_sweep: bool = False,
    require_pd_zone: bool = True,
    use_classic_filters: bool = False,    # if True, use HTF EMA/RSI alignment instead of swing-based
    use_ctf_filter: bool = False,         # require CTF (daily) bias confirmation - approximated
    max_bars_in_trade: int = 100,
    warmup_ltf: int = 250,
) -> Stats:
    """Run backtest over precomputed data with given params."""
    df_htf = pre.df_htf
    df_ltf = pre.df_ltf
    ltf_o = df_ltf["open"].to_numpy()
    ltf_h = df_ltf["high"].to_numpy()
    ltf_l = df_ltf["low"].to_numpy()
    ltf_c = df_ltf["close"].to_numpy()
    ltf_atr = df_ltf["atr"].to_numpy()
    ltf_hol = df_ltf["holonomy"].to_numpy()
    ltf_rsi = df_ltf["rsi"].to_numpy()

    htf_atr = df_htf["atr"].to_numpy()
    htf_hol = df_htf["holonomy"].to_numpy()
    htf_close = df_htf["close"].to_numpy()
    htf_high = df_htf["high"].to_numpy()
    htf_low = df_htf["low"].to_numpy()
    htf_ema20 = df_htf["ema20"].to_numpy()
    htf_ema50 = df_htf["ema50"].to_numpy()
    htf_sma200 = df_htf["sma200"].to_numpy()
    htf_rsi = df_htf["rsi"].to_numpy()

    # Re-build sweep rolling at requested lookback (override pre.htf_recent_*)
    if sweep_lookback != int(getattr(config, "LIQUIDITY_SWEEP_LOOKBACK", 10)):
        ser_h = pd.Series(htf_high)
        ser_l = pd.Series(htf_low)
        recent_high = ser_h.rolling(sweep_lookback, min_periods=1).max().to_numpy()
        recent_low = ser_l.rolling(sweep_lookback, min_periods=1).min().to_numpy()
    else:
        recent_high = pre.htf_recent_high
        recent_low = pre.htf_recent_low

    # Bucket FVGs / OBs by formation idx for fast lookup
    bull_fvgs = sorted(pre.bull_fvgs, key=lambda d: d["idx"])
    bear_fvgs = sorted(pre.bear_fvgs, key=lambda d: d["idx"])
    bull_obs = sorted(pre.bull_obs, key=lambda d: d["idx"])
    bear_obs = sorted(pre.bear_obs, key=lambda d: d["idx"])

    bull_fvg_idx = np.array([d["idx"] for d in bull_fvgs], dtype=np.int64)
    bear_fvg_idx = np.array([d["idx"] for d in bear_fvgs], dtype=np.int64)
    bull_ob_idx = np.array([d["idx"] for d in bull_obs], dtype=np.int64)
    bear_ob_idx = np.array([d["idx"] for d in bear_obs], dtype=np.int64)

    def _in_active_zone(price: float, side: str, ltf_i: int) -> bool:
        """Check if price sits inside any FVG/OB of correct side formed before ltf_i,
        using a 50-bar look-back and not yet fully traversed."""
        max_age = 100
        if side == "Buy":
            # bullish entry → bullish FVG/OB
            n = np.searchsorted(bull_fvg_idx, ltf_i, side="left")
            for k in range(n - 1, max(-1, n - 1 - max_age), -1):
                d = bull_fvgs[k]
                if d["low"] <= price <= d["high"]:
                    return True
            n = np.searchsorted(bull_ob_idx, ltf_i, side="left")
            for k in range(n - 1, max(-1, n - 1 - max_age), -1):
                d = bull_obs[k]
                if d["low"] <= price <= d["high"]:
                    return True
        else:
            n = np.searchsorted(bear_fvg_idx, ltf_i, side="left")
            for k in range(n - 1, max(-1, n - 1 - max_age), -1):
                d = bear_fvgs[k]
                if d["low"] <= price <= d["high"]:
                    return True
            n = np.searchsorted(bear_ob_idx, ltf_i, side="left")
            for k in range(n - 1, max(-1, n - 1 - max_age), -1):
                d = bear_obs[k]
                if d["low"] <= price <= d["high"]:
                    return True
        return False

    rejects: dict[str, int] = {}
    def _rej(reason: str):
        rejects[reason] = rejects.get(reason, 0) + 1

    stats = Stats()
    stats.rejects = rejects

    n = len(ltf_c)
    raw_signals = 0
    last_signal_bar = -10**9

    j = warmup_ltf
    while j < n - 1:
        # Use the LAST CLOSED LTF bar (j-1) for entry decisions, simulate from j.
        if j - 1 < warmup_ltf:
            j += 1
            continue
        bar = j - 1
        price = float(ltf_c[bar])

        if bar - last_signal_bar < min_bars_between_signals:
            j += 1
            continue

        # 1) Holonomy on HTF (last closed HTF bar)
        htf_i = int(pre.ltf_to_htf_idx[bar])
        if htf_i < 1:
            j += 1
            continue
        # use closed HTF bar = htf_i - 1 if current LTF has not closed HTF; for simplicity use htf_i
        hbar = htf_i
        if hbar < 2:
            j += 1; continue

        if abs(htf_hol[hbar]) < holonomy_sensitivity:
            _rej("reject_holonomy")
            j += 1; continue

        atr_h = float(htf_atr[hbar])
        if atr_h <= 0 or np.isnan(atr_h):
            j += 1; continue

        # 2) Direction (HTF trend or classic filters)
        if use_classic_filters:
            ema20 = htf_ema20[hbar]
            ema50 = htf_ema50[hbar]
            sma200 = htf_sma200[hbar] if not np.isnan(htf_sma200[hbar]) else 0.0
            rsi_h = htf_rsi[hbar]
            htf_pr = htf_close[hbar]
            bullish = htf_pr > sma200 and htf_pr > ema20 > ema50 and rsi_h > 50
            bearish = htf_pr < sma200 and htf_pr < ema20 < ema50 and rsi_h < 50
            if not bullish and not bearish:
                _rej("reject_htf_trend")
                j += 1; continue
            ltf_h_v = ltf_hol[bar]
            ltf_r = ltf_rsi[bar]
            if bullish and (ltf_h_v < 0 or ltf_r < 45):
                _rej("reject_ltf"); j += 1; continue
            if bearish and (ltf_h_v > 0 or ltf_r > 55):
                _rej("reject_ltf"); j += 1; continue
            direction = "Buy" if bullish else "Sell"
        else:
            tr = pre.htf_trend[hbar]
            if tr == 0:
                _rej("reject_htf_trend"); j += 1; continue
            direction = "Buy" if tr == 1 else "Sell"

        # 3) Premium / Discount zone
        rh = pre.htf_range_high[hbar]
        rl = pre.htf_range_low[hbar]
        if require_pd_zone:
            if np.isnan(rh) or np.isnan(rl) or rh <= rl:
                _rej("reject_pd_zone:no_range"); j += 1; continue
            ratio = (price - rl) / (rh - rl)
            if direction == "Buy":
                if ratio >= pd_threshold:
                    _rej("reject_pd_zone"); j += 1; continue
            else:
                if ratio <= 1.0 - pd_threshold:
                    _rej("reject_pd_zone"); j += 1; continue

        # 4) Liquidity sweep (recent HTF wicks beyond equal highs/lows)
        if require_sweep:
            rec_hi = recent_high[hbar]
            rec_lo = recent_low[hbar]
            eq_h = pre.htf_eq_high[hbar]
            eq_l = pre.htf_eq_low[hbar]
            sweep_ok = False
            if direction == "Buy":
                # bullish sweep = wick below equal lows that closed back above
                if not np.isnan(eq_l) and rec_lo < eq_l:
                    sweep_ok = True
            else:
                if not np.isnan(eq_h) and rec_hi > eq_h:
                    sweep_ok = True
            if not sweep_ok:
                _rej("reject_sweep"); j += 1; continue

        # 5) Entry zone (FVG/OB containing current price)
        if require_entry_zone:
            if not _in_active_zone(price, direction, bar):
                _rej("reject_entry_zone"); j += 1; continue

        # 6) Build SL / TP from HTF ATR
        sl_dist = atr_h * sl_mult
        tp_dist = atr_h * tp_mult
        if direction == "Buy":
            sl = price - sl_dist
            tp = price + tp_dist
        else:
            sl = price + sl_dist
            tp = price - tp_dist

        # Simulate
        win, pnl, exit_idx = _simulate(direction, j, price, sl, tp,
                                        ltf_h, ltf_l, ltf_c, max_bars_in_trade)
        stats.add(Trade(
            symbol=pre.symbol, direction=direction,
            entry_idx=j, entry_ts=int(df_ltf["ts"].iat[j]),
            entry=price, sl=sl, tp=tp,
            exit_idx=exit_idx, bars_held=exit_idx - j,
            win=win, pnl_r=pnl,
        ))
        raw_signals += 1
        last_signal_bar = bar
        j = max(exit_idx, j + min_bars_between_signals)

    # Days covered
    if n >= 2:
        ms_span = int(df_ltf["ts"].iat[-1]) - int(df_ltf["ts"].iat[warmup_ltf])
        stats.days_covered = ms_span / (1000 * 60 * 60 * 24)
    stats.raw_signals = raw_signals
    return stats


def aggregate(stats_list: list[Stats]) -> Stats:
    out = Stats()
    out.days_covered = max((s.days_covered for s in stats_list), default=0.0)
    for s in stats_list:
        for t in s.trades:
            out.add(t)
        for k, v in s.rejects.items():
            out.rejects[k] = out.rejects.get(k, 0) + v
        out.raw_signals += s.raw_signals
    return out
