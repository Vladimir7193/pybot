"""Grid search over strategy parameters using the fast backtester."""
from __future__ import annotations
import itertools
import time
import json

from fast_backtest import precompute_symbol, backtest, aggregate, Stats


SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT"]


def precompute_all(fvg_min_size_atr: float = 0.3,
                   ob_impulse_threshold: float = 2.0):
    out = {}
    for s in SYMBOLS:
        out[s] = precompute_symbol(s,
            fvg_min_size_atr=fvg_min_size_atr,
            ob_impulse_threshold=ob_impulse_threshold)
    return out


def evaluate(precomp: dict, params: dict) -> dict:
    """Run backtest across all symbols with given params, aggregate."""
    stats_list = []
    for sym, pre in precomp.items():
        s = backtest(pre, **params)
        stats_list.append(s)
    agg = aggregate(stats_list)
    out = agg.summary()
    out["params"] = params
    return out


def score(row: dict, min_trades_per_day: float = 1.0) -> float:
    """
    Composite score: penalises configs that don't hit ≥1 trade/day,
    rewards positive expectancy and profit factor.
    """
    if row["trades_per_day"] < min_trades_per_day:
        return -10.0 + row["trades_per_day"]   # still rank by tpd among <1
    if row["trades"] < 5:
        return -5.0
    pf = row["profit_factor"]
    pf = 5.0 if pf == "inf" else float(pf)
    exp = row["expectancy_R"]
    wr = row["win_rate_%"] / 100.0
    # Prefer positive expectancy and high profit factor; small bonus for trade count.
    return (exp * 5.0) + min(pf, 3.0) + wr + min(row["trades_per_day"] / 5.0, 1.0)


def main():
    print("Pre-computing data for all symbols ...")
    t0 = time.time()
    # Two FVG/OB strictness levels are pre-computed separately.
    precomp_lax = precompute_all(fvg_min_size_atr=0.2, ob_impulse_threshold=1.5)
    precomp_def = precompute_all(fvg_min_size_atr=0.3, ob_impulse_threshold=2.0)
    precomp_str = precompute_all(fvg_min_size_atr=0.5, ob_impulse_threshold=2.5)
    print(f"  done in {time.time()-t0:.1f}s")

    grid = list(itertools.product(
        # strategy mode
        [("smc_swing", False), ("classic", True)],
        # require_entry_zone
        [True, False],
        # require_sweep
        [False, True],
        # require_pd_zone
        [True, False],
        # pd_threshold
        [0.40, 0.45, 0.50],
        # sweep_lookback
        [10, 20],
        # holonomy_sensitivity
        [0.02, 0.04],
        # min_bars_between_signals (15m candles)
        [4, 8, 16],
        # sl_mult / tp_mult / RR
        [(1.0, 2.0), (1.0, 3.0), (1.0, 4.0), (1.5, 3.0), (0.8, 2.4)],
        # FVG/OB strictness
        ["lax", "def", "strict"],
    ))

    print(f"Grid size: {len(grid)} combinations")

    results: list[dict] = []
    started = time.time()
    for n, (mode_t, req_zone, req_sweep, req_pd, pdt, swl, hol, mbs, sltp, fob) in enumerate(grid):
        mode_label, use_classic = mode_t
        sl_m, tp_m = sltp
        if fob == "lax":
            pre = precomp_lax
        elif fob == "def":
            pre = precomp_def
        else:
            pre = precomp_str
        params = dict(
            sl_mult=sl_m, tp_mult=tp_m,
            pd_threshold=pdt, sweep_lookback=swl,
            holonomy_sensitivity=hol,
            min_bars_between_signals=mbs,
            require_entry_zone=req_zone,
            require_sweep=req_sweep,
            require_pd_zone=req_pd,
            use_classic_filters=use_classic,
        )
        row = evaluate(pre, params)
        row["mode"] = mode_label
        row["fvg_ob"] = fob
        row["score"] = score(row)
        results.append(row)
        if (n + 1) % 200 == 0:
            print(f"  [{n+1}/{len(grid)}] elapsed {time.time()-started:.0f}s")

    # Sort by score
    results.sort(key=lambda r: r["score"], reverse=True)

    # Filter: must hit ≥1 trade/day and ≥30 trades total
    qualified = [r for r in results if r["trades_per_day"] >= 1.0 and r["trades"] >= 30]
    print(f"\nTotal: {len(results)}, qualified (≥1 trade/day, ≥30 trades): {len(qualified)}")

    print("\nTop 20 (qualified) by score:")
    for r in qualified[:20]:
        p = r["params"]
        print(f"  score={r['score']:6.3f}  trades={r['trades']:4d}  "
              f"tpd={r['trades_per_day']:.2f}  WR={r['win_rate_%']:5.1f}%  "
              f"PF={r['profit_factor']}  expR={r['expectancy_R']:+.3f}  "
              f"DD={r['max_dd_R']:5.2f}  totalR={r['total_R']:+6.2f}  "
              f"mode={r['mode']:10s} fob={r['fvg_ob']:6s} "
              f"zone={p['require_entry_zone']} sweep={p['require_sweep']} pd={p['require_pd_zone']} "
              f"pdt={p['pd_threshold']} swl={p['sweep_lookback']} hol={p['holonomy_sensitivity']} "
              f"mbs={p['min_bars_between_signals']} SL={p['sl_mult']} TP={p['tp_mult']}")

    # Save results to JSON
    with open("sweep_results.json", "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nSaved {len(results)} rows to sweep_results.json")


if __name__ == "__main__":
    main()
