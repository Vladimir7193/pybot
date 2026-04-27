from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from types import SimpleNamespace

import pandas as pd

from signal_engine import SignalEngine
import signal_engine as se


def _make_df(rows: int = 320) -> pd.DataFrame:
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


class _FakeStruct:
    trend = "bullish"
    swings_high = []
    swings_low = []

    def detect_swings(self, df):
        return [], []

    def detect_bos(self, df):
        return SimpleNamespace(type="BOS", index=max(5, len(df) - 5), price=float(df.iloc[-2]["close"]), direction="bullish")

    def check_liquidity_sweep(self, df, lookback=10):
        return None

    def get_premium_discount_ratio(self, price, df):
        return 0.10

    def get_range_high(self, df):
        return float(df["high"].max())

    def get_range_low(self, df):
        return float(df["low"].min())

    def get_equal_highs(self):
        return []

    def get_equal_lows(self):
        return []

    def resolve_trend(self, df, use_closed_candle=True):
        return "bullish"


class _FakeOBNoZone:
    order_blocks = []

    def detect_order_blocks(self, *args, **kwargs):
        return []

    def detect_breaker_blocks(self, *args, **kwargs):
        return []

    def detect_mitigation_blocks(self, *args, **kwargs):
        return []

    def cleanup_expired(self, *args, **kwargs):
        return None

    def is_price_in_breaker(self, *args, **kwargs):
        return False

    def is_price_in_mitigation(self, *args, **kwargs):
        return False

    def is_price_in_order_block(self, *args, **kwargs):
        return False


class _FakeFVGNoZone:
    fvgs = []

    def detect_fvgs(self, *args, **kwargs):
        return []

    def update_fill_status(self, *args, **kwargs):
        return None

    def cleanup_expired(self, *args, **kwargs):
        return None

    def is_price_in_fvg(self, *args, **kwargs):
        return False


class _FakeSetupNone:
    def detect_all_patterns(self, *args, **kwargs):
        return []

    def get_latest_pattern(self, *args, **kwargs):
        return None


class _FakeOrderFlow:
    def track_liquidity_sweeps(self, *args, **kwargs):
        return []

    def detect_liquidity_pools(self, *args, **kwargs):
        return None

    def detect_order_flow_sequence(self, *args, **kwargs):
        return None

    def is_valid_order_flow(self, *args, **kwargs):
        return False


class _FakeLevels:
    def update_all_levels(self, *args, **kwargs):
        return None

    def mark_tested(self, *args, **kwargs):
        return None

    def what_holds_price(self, *args, **kwargs):
        return None

    def is_true_structure_break(self, *args, **kwargs):
        return False


def test_relaxed_reject_reason_is_specific(monkeypatch):
    engine = SignalEngine(equity_fn=lambda: 1000.0, max_positions=3)
    htf = _make_df(320)
    ltf = _make_df(120)

    monkeypatch.setattr(se, "ENABLE_SMC", True)
    monkeypatch.setattr(se, "PURE_SMC", True)
    monkeypatch.setattr(se.config, "SMC_MODE", "RELAXED")
    monkeypatch.setattr(se, "USE_RANGE_DETECTION", False)
    monkeypatch.setattr(se, "USE_KILL_ZONES", False)
    monkeypatch.setattr(se, "USE_AMD", False)
    monkeypatch.setattr(se, "USE_MOMENTUM", False)
    monkeypatch.setattr(se, "USE_SETUP_PATTERNS", True)
    monkeypatch.setattr(se, "USE_ORDER_FLOW", False)
    monkeypatch.setattr(se, "USE_KEY_LEVELS", True)

    monkeypatch.setattr(
        engine,
        "_detectors",
        lambda symbol: (
            _FakeStruct(),
            _FakeOBNoZone(),
            _FakeFVGNoZone(),
            _FakeSetupNone(),
            _FakeOrderFlow(),
            _FakeLevels(),
        ),
    )

    sig = engine.analyze("BTCUSDT", htf, ltf, 1000.0, 0.0, 0, {"min_qty": 0.001, "qty_step": 0.001, "price_tick": 0.01})
    assert sig is None
    assert engine.reject_stats["reject_relaxed:zone"] == 1
    assert any("reject_relaxed:zone" in item for item in engine.reject_details["BTCUSDT"])
