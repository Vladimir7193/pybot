"""Focused parameter sweep around the leading configuration."""
from __future__ import annotations
import itertools
import json
import time

from fast_backtest import precompute_symbol, backtest, aggregate

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT"]


def main():
    print("Pre-computing ...")
    t0 = time.time()
    precomp_def = {s: precompute_symbol(s) for s in SYMBOLS}
    precomp_lax = {s: precompute_symbol(s, fvg_min_size_atr=0.2,
                                         ob_impulse_threshold=1.5)
                   for s in SYMBOLS}
    print(f"  {time.time()-t0:.1f}s")

    grid = list(itertools.product(
        [(False, "smc_swing"), (True, "classic")],   # use_classic_filters
        [(0.6, 1.8), (0.6, 2.4), (0.7, 2.1), (0.8, 2.4),
         (0.8, 1.6), (1.0, 2.0), (1.0, 2.5), (1.0, 3.0),
         (1.2, 2.4), (1.5, 3.0)],                    # (sl_mult, tp_mult)
        [12, 16, 20, 24, 32, 48],                    # min_bars_between_signals
        [5, 10, 15, 20, 30],                         # sweep_lookback
        [True, False],                               # require_pd_zone
        [0.45, 0.50, 0.55],                          # pd_threshold
        ["lax", "def"],                              # FVG/OB strictness
    ))
    print(f"Grid size: {len(grid)}")

    rows = []
    started = time.time()
    for n, (mt, sltp, mbs, swl, req_pd, pdt, fob) in enumerate(grid):
        use_classic, mode_label = mt
        sl, tp = sltp
        pre = precomp_lax if fob == "lax" else precomp_def
        params = dict(
            sl_mult=sl, tp_mult=tp,
            pd_threshold=pdt, sweep_lookback=swl,
            holonomy_sensitivity=0.02,
            min_bars_between_signals=mbs,
            require_entry_zone=True,
            require_sweep=True,
            require_pd_zone=req_pd,
            use_classic_filters=use_classic,
        )
        stats_list = [backtest(pre[s], **params) for s in SYMBOLS]
        agg = aggregate(stats_list)
        s = agg.summary()
        s["params"] = params
        s["mode"] = mode_label
        s["fvg_ob"] = fob
        # Per-symbol breakdown
        s["per_symbol"] = {sym: stats_list[i].summary() for i, sym in enumerate(SYMBOLS)}
        # Score
        if s["trades_per_day"] >= 1.0 and s["trades"] >= 30:
            pf = s["profit_factor"]
            pf = 5.0 if pf == "inf" else float(pf)
            s["score"] = (s["expectancy_R"] * 5.0
                          + min(pf, 3.0)
                          + s["win_rate_%"] / 100.0)
        else:
            s["score"] = -10 + s["trades_per_day"]
        rows.append(s)
        if (n + 1) % 500 == 0:
            print(f"  [{n+1}/{len(grid)}] {time.time()-started:.0f}s")

    rows.sort(key=lambda r: r["score"], reverse=True)

    # Filter to qualified configs
    qualified = [r for r in rows if r["trades_per_day"] >= 1.0 and r["trades"] >= 30]
    print(f"\nQualified: {len(qualified)} / {len(rows)}")

    print("\nTop 25 (qualified):")
    for r in qualified[:25]:
        p = r["params"]
        print(f"  score={r['score']:6.3f}  trades={r['trades']:4d}  "
              f"tpd={r['trades_per_day']:.2f}  WR={r['win_rate_%']:5.1f}%  "
              f"PF={r['profit_factor']}  expR={r['expectancy_R']:+.3f}  "
              f"DD={r['max_dd_R']:5.2f}  totalR={r['total_R']:+6.2f}  "
              f"mode={r['mode']:10s} fob={r['fvg_ob']:4s} "
              f"pd={p['require_pd_zone']} pdt={p['pd_threshold']} "
              f"swl={p['sweep_lookback']:2d} mbs={p['min_bars_between_signals']:2d} "
              f"SL={p['sl_mult']:.1f} TP={p['tp_mult']:.1f}")

    with open("sweep_focus_results.json", "w") as f:
        json.dump(rows, f, indent=2, default=str)


if __name__ == "__main__":
    main()
