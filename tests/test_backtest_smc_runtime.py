from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from types import SimpleNamespace

import pandas as pd

import backtest_smc
from signal_engine import SignalEngine


def _make_df(rows: int = 120) -> pd.DataFrame:
    close = [100 + i * 0.1 for i in range(rows)]
    return pd.DataFrame({
        "open": close,
        "high": [c + 1 for c in close],
        "low": [c - 1 for c in close],
        "close": close,
        "atr": [2.0] * rows,
        "atr_avg": [2.0] * rows,
        "holonomy": [0.2] * rows,
        "anomaly": [1.0] * rows,
        "ema20": [c - 0.2 for c in close],
        "ema50": [c - 0.5 for c in close],
        "sma200": [c - 1.0 for c in close],
        "rsi": [60.0] * rows,
        "ts": list(range(rows)),
    })


def test_detect_smc_signals_skips_bars_and_passes_ctf(monkeypatch):
    engine = SignalEngine(equity_fn=lambda: 1000.0, max_positions=3)
    htf = _make_df(400)
    ltf = _make_df(120)
    ctf = _make_df(90)
    instrument = {"min_qty": 0.001, "qty_step": 0.001, "price_tick": 0.01}
    calls = []

    def fake_analyze(**kwargs):
        calls.append((len(kwargs["df_ltf"]), None if kwargs.get("df_ctf") is None else len(kwargs["df_ctf"])))
        return SimpleNamespace(direction="Buy", entry=float(kwargs["df_ltf"].iloc[-2]["close"]), atr=2.0)

    monkeypatch.setattr(engine, "analyze", fake_analyze)

    signals = backtest_smc.detect_smc_signals(engine, htf, ltf, "BTCUSDT", instrument, df_ctf=ctf)

    assert signals, "signals should be produced by fake analyze"
    gaps = [signals[i + 1]["entry_idx"] - signals[i]["entry_idx"] for i in range(len(signals) - 1)]
    assert gaps and min(gaps) >= backtest_smc.MIN_BARS_BETWEEN_SIGNALS
    assert all(ctf_len is not None and ctf_len >= 1 for _, ctf_len in calls)
