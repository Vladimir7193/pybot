from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from types import SimpleNamespace

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
def instrument():
    return {"min_qty": 0.001, "qty_step": 0.001, "price_tick": 0.01}


@pytest.fixture()
def engine():
    return SignalEngine(equity_fn=lambda: 1000.0, max_positions=3)


def test_smc_mode_is_read_dynamically(monkeypatch, engine, instrument):
    htf = _make_df(260)
    ltf = _make_df(80)
    mode_calls = []

    monkeypatch.setattr(se, "ENABLE_SMC", True)
    monkeypatch.setattr(se, "PURE_SMC", False)

    def fake_apply(self, symbol, df_htf, df_ltf, df_ctf, price, direction, atr_val, force_mode="STRICT"):
        mode_calls.append(force_mode)
        return "ok" if force_mode == "RELAXED" else None

    monkeypatch.setattr(SignalEngine, "_apply_smc_filters", fake_apply, raising=True)

    monkeypatch.setattr(se.config, "SMC_MODE", "STRICT")
    sig1 = engine.analyze("BTCUSDT", htf, ltf, 1000.0, 0.0, 0, instrument)
    assert sig1 is not None and sig1.mode == "RELAXED"
    assert mode_calls[:2] == ["STRICT", "RELAXED"]

    engine.get_state("BTCUSDT").bars_since_signal = 999
    mode_calls.clear()
    monkeypatch.setattr(se.config, "SMC_MODE", "RELAXED")
    sig2 = engine.analyze("BTCUSDT", htf, ltf, 1000.0, 0.0, 0, instrument)
    assert sig2 is not None and sig2.mode == "RELAXED"
    assert mode_calls[0] == "RELAXED"


def test_pure_smc_rejects_unresolved_bias(monkeypatch, engine, instrument):
    htf = _make_df(260)
    ltf = _make_df(80)

    monkeypatch.setattr(se, "ENABLE_SMC", True)
    monkeypatch.setattr(se, "PURE_SMC", True)

    fake_struct = SimpleNamespace(resolve_trend=lambda df, use_closed_candle=True: None)
    monkeypatch.setattr(engine, "_detectors", lambda symbol: (fake_struct, None, None, None, None, None))

    sig = engine.analyze("BTCUSDT", htf, ltf, 1000.0, 0.0, 0, instrument)
    assert sig is None
    assert engine.reject_stats["reject_htf_trend"] == 1


def test_relaxed_requires_zone_and_confirmation(monkeypatch, engine):
    htf = _make_df(260)
    ltf = _make_df(80)

    class FakeStruct:
        trend = "bullish"
        swings_high = []
        swings_low = []

        def detect_swings(self, df):
            return [], []

        def detect_bos(self, df):
            return SimpleNamespace(type="BOS", index=10, price=100.0, direction="bullish")

        def check_liquidity_sweep(self, df, lookback=10):
            return None

        def get_premium_discount_ratio(self, price, df):
            return 0.1

        def get_range_high(self, df):
            return 110.0

        def get_range_low(self, df):
            return 90.0

        def get_equal_highs(self):
            return []

        def get_equal_lows(self):
            return []

        def resolve_trend(self, df, use_closed_candle=True):
            return "bullish"

    class FakeOB:
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

    class FakeFVG:
        fvgs = []

        def detect_fvgs(self, *args, **kwargs):
            return []

        def update_fill_status(self, *args, **kwargs):
            return None

        def cleanup_expired(self, *args, **kwargs):
            return None

        def is_price_in_fvg(self, *args, **kwargs):
            return False

    class FakeSetup:
        def detect_all_patterns(self, *args, **kwargs):
            return []

        def get_latest_pattern(self, *args, **kwargs):
            return None

    class FakeOrderFlow:
        def track_liquidity_sweeps(self, *args, **kwargs):
            return []

        def detect_liquidity_pools(self, *args, **kwargs):
            return None

        def detect_order_flow_sequence(self, *args, **kwargs):
            return None

        def is_valid_order_flow(self, *args, **kwargs):
            return False

    class FakeLevels:
        def update_all_levels(self, *args, **kwargs):
            return None

        def mark_tested(self, *args, **kwargs):
            return None

        def what_holds_price(self, *args, **kwargs):
            return None

        def is_true_structure_break(self, *args, **kwargs):
            return False

    monkeypatch.setattr(engine, "_detectors", lambda symbol: (FakeStruct(), FakeOB(), FakeFVG(), FakeSetup(), FakeOrderFlow(), FakeLevels()))
    monkeypatch.setattr(se, "USE_RANGE_DETECTION", False)
    monkeypatch.setattr(se, "USE_KILL_ZONES", False)
    monkeypatch.setattr(se, "USE_AMD", False)
    monkeypatch.setattr(se, "USE_MOMENTUM", False)
    monkeypatch.setattr(se, "USE_SETUP_PATTERNS", True)
    monkeypatch.setattr(se, "USE_ORDER_FLOW", False)
    monkeypatch.setattr(se, "USE_KEY_LEVELS", True)

    result = engine._apply_smc_filters("BTCUSDT", htf, ltf, None, 100.0, "Buy", 2.0, force_mode="RELAXED")
    assert result is None
    assert engine.reject_stats["reject_relaxed:zone"] == 1
