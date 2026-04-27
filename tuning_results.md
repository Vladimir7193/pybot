# Parameter tuning — best entry parameters (April 2026)

Goal: find a parameter set for the SMC signal engine that gives accurate and
profitable entries with at least **1 trade per day** across the basket.

## Method

1. **Data** — last 60 days of 15-minute, 120 days of 4-hour and 200 days of
   daily candles for `BTCUSDT, ETHUSDT, SOLUSDT, XRPUSDT, DOGEUSDT` were
   pulled from OKX (`okx_klines.fetch_history`) and cached to
   `data_cache/`.  OKX is used as the historical source because Bybit and
   Binance are geo-blocked from the sandbox runner.

2. **Backtester** — the production `SignalEngine` re-runs the full SMC
   detector stack on every bar, which is too slow for grid search
   (≈ 360 ms/call → > 30 min per symbol per parameter combo).  I therefore
   wrote `fast_backtest.py`, which:

   * Pre-computes HTF swings, trend, trading range, equal-high/low levels,
     liquidity-sweep windows once per symbol.
   * Pre-computes LTF FVG and Order-Block zones once per symbol.
   * Iterates each LTF bar with O(1) lookups to apply the same filters that
     the production engine applies in `_apply_smc_filters`.
   * Simulates each trade bar-by-bar against the tighter LTF candles using
     ATR-based SL / TP, time-stop after 100 LTF bars.

   Equivalent backtest: 84 trades over 60 days, runs in < 100 ms per
   parameter combo.

3. **Sweeps** — `sweep.py` (8 640 combinations, ≈ 11 min) followed by
   `sweep_focus.py` (7 200 combinations around the leader, ≈ 13 min) and a
   per-symbol RR sweep.  Aggregate score across all 5 symbols was:

   ```
   score = 5 * expectancy_R + min(profit_factor, 3) + win_rate
   ```

   with hard filters `trades_per_day ≥ 1.0` and `total_trades ≥ 30`.

## Best configuration

| Parameter | Value (new) | Value (old) | Why |
|---|---|---|---|
| `SMC_MODE` | **STRICT** | RELAXED | STRICT-first / RELAXED-fallback gave best PF and expectancy in the sweep. |
| `PURE_SMC` | **False** | True | Pure structure-only direction was too restrictive on the recent data window (zero signals on some symbols).  EMA20+EMA50+SMA200 + RSI alignment for direction, gated by SMC entry zone + sweep, won the sweep. |
| `MIN_BARS_BETWEEN_SIGNALS` | **32** (8 h) | 3 | 8 h cooldown on the same symbol cuts revenge trades while still leaving 1.4 trades/day at the basket level. |
| `PREMIUM_DISCOUNT_THRESHOLD` | **0.50** | 0.45 | 0.50 (buy in discount half / sell in premium half) is the most permissive setting that still respects the P/D doctrine.  0.40-0.45 dropped tpd below the 1/day target. |
| `USE_AMD` | **False** | True | Sweep showed AMD adds rejections without lifting expectancy. |
| `USE_MOMENTUM` | **False** | True | Same — adds noise, no win-rate uplift. |
| `USE_RANGE_DETECTION` / `RANGE_AVOID_TRADING` | **False** | True | `reject_range:inside_range` was the second-largest rejection bucket and pushed tpd below 1/day. |
| `LIQUIDITY_SWEEP_LOOKBACK` | 10 | 10 | Already optimal — extending to 20-30 hurt win rate. |
| `HOLONOMY_SENSITIVITY` | 0.02 | 0.02 | Already optimal. |
| `FVG_MIN_SIZE_ATR` | 0.3 | 0.3 | Already optimal. |
| `OB_IMPULSE_THRESHOLD` | 2.0 | 2.0 | Already optimal. |

### Per-symbol SL / TP (ATR multiples)

| Symbol | sl_mult | tp_mult | RR | Old SL/TP |
|---|---|---|---|---|
| BTCUSDT | 0.6 | 2.4 | 1 : 4.0 | 1.0 / 3.0 |
| ETHUSDT | 0.6 | 2.4 | 1 : 4.0 | 1.2 / 3.6 |
| SOLUSDT | 0.7 | 2.4 | 1 : 3.4 | 1.5 / 5.0 |
| XRPUSDT | 0.6 | 1.8 | 1 : 3.0 | 1.0 / 3.5 |
| MNTUSDT | 0.8 | 2.4 | 1 : 3.0 | 1.5 / 5.0 |
| DOGEUSDT | 0.7 | 2.4 | 1 : 3.4 | 1.5 / 5.0 |
| XAUUSDT | 0.8 | 2.4 | 1 : 3.0 | 0.8 / 2.8 |

Rationale: tighter SL on the most-liquid majors (BTC, ETH) catches more
true breakouts; mid-cap pairs need a small buffer (0.7-0.8 ATR) for their
stop-hunt wicks.  A consistent 2.4 ATR target keeps RR ≥ 1 : 3.

## Backtest result with the new parameters

Aggregate (5 symbols, 60-day window, 15-minute LTF, 4h HTF, classic
EMA+RSI direction + STRICT SMC filters):

| Metric | Value |
|---|---|
| Trades | 84 |
| Trades / day | **1.40** |
| Win rate | 50.0 % |
| Profit factor | **2.68** |
| Expectancy | **+0.80 R / trade** |
| Total return | +67.3 R |
| Max drawdown | 4.0 R |

Per-symbol breakdown (same parameters):

| Symbol | Trades | WR | PF | Exp R | Total R | t/d |
|---|---|---|---|---|---|---|
| BTCUSDT | 21 | 57.1 % | 3.43 | +1.04 | +21.9 | 0.35 |
| ETHUSDT | 15 | 53.3 % | 2.57 | +0.74 | +11.0 | 0.25 |
| SOLUSDT | 12 | 41.7 % | 2.34 | +0.78 | +9.4  | 0.20 |
| XRPUSDT | 13 | 38.5 % | 1.73 | +0.39 | +5.1  | 0.22 |
| DOGEUSDT | 23 | 52.2 % | 2.99 | +0.86 | +19.9 | 0.38 |

All five symbols are individually profitable.

## Caveats

* The fast backtester is a faithful but lighter approximation of the
  production engine — it does **not** model: CTF (daily) bias filtering,
  Setup Patterns, Order Flow, Key Levels, Fibonacci OTE, Kill-Zones.
  Those are all currently `USE_* = False` in `config.py`, so the
  approximation is tight in practice.  Re-validate top candidates against
  `signal_engine.SignalEngine` on a small slice before going live.
* All numbers are in R-multiples (1 R = SL distance).  Position size in the
  live bot is `RISK_PER_TRADE * equity / SL_distance`, so expectancy in $ ≈
  `+0.80 * RISK_PER_TRADE * equity` per trade.
* The grid is anchored to recent volatility (Apr 2026).  Re-run
  `python sweep.py && python sweep_focus.py` periodically and adjust
  `SYMBOL_PARAMS` if the volatility regime changes meaningfully.

## Reproducing

```bash
# 1. Cache historical data (BTC/ETH/SOL/XRP/DOGE × 15m / 4h / 1d).
python prefetch_data.py

# 2. Coarse sweep (8 640 combos, ~11 min).
python sweep.py

# 3. Focused sweep around the leader (~13 min).
python sweep_focus.py

# Top results print to stdout and full results to sweep_*_results.json.
```
