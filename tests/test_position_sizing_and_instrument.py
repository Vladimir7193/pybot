from pathlib import Path
import math
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd
import pytest

import signal_engine as se
from signal_engine import SignalEngine


def _make_df(rows: int = 260, bullish: bool = True) -> pd.DataFrame:
    close = [100 + i * 0.1 for i in range(rows)] if bullish else [100 - i * 0.1 for i in range(rows)]
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


@pytest.fixture()
def engine():
    return SignalEngine(equity_fn=lambda: 1000.0, max_positions=3)


def test_analyze_accepts_nested_instrument_format(monkeypatch, engine):
    htf = _make_df(260)
    ltf = _make_df(80)
    nested = {
        "lotSizeFilter": {"minOrderQty": "0.005", "qtyStep": "0.005"},
        "priceFilter": {"tickSize": "0.1"},
    }

    monkeypatch.setattr(se, "ENABLE_SMC", False)

    sig = engine.analyze("BTCUSDT", htf, ltf, 1000.0, 0.0, 0, nested)
    assert sig is not None
    assert abs((sig.qty / 0.005) - round(sig.qty / 0.005)) < 1e-9


def test_qty_is_rounded_down_to_step(monkeypatch, engine):
    htf = _make_df(260)
    ltf = _make_df(80)
    instrument = {"min_qty": 0.005, "qty_step": 0.005, "price_tick": 0.1}

    monkeypatch.setattr(se, "ENABLE_SMC", False)
    monkeypatch.setattr(se, "RISK_PER_TRADE", 0.011)

    sig = engine.analyze("BTCUSDT", htf, ltf, 1000.0, 0.0, 0, instrument)
    assert sig is not None

    price = float(ltf.iloc[-2]["close"])
    atr = float(htf.iloc[-2]["atr"])
    sl_dist = atr * se.SYMBOL_PARAMS["BTCUSDT"]["sl_mult"]
    qty_raw = (1000.0 * se.RISK_PER_TRADE) / sl_dist
    expected = round(math.floor(qty_raw / instrument["qty_step"]) * instrument["qty_step"], 8)
    assert sig.qty == expected


def test_rejects_when_qty_below_min(monkeypatch, engine):
    htf = _make_df(260)
    ltf = _make_df(80)
    instrument = {"min_qty": 100.0, "qty_step": 0.001, "price_tick": 0.01}

    monkeypatch.setattr(se, "ENABLE_SMC", False)

    sig = engine.analyze("BTCUSDT", htf, ltf, 1000.0, 0.0, 0, instrument)
    assert sig is None
    assert engine.reject_stats["reject_qty_min"] == 1
