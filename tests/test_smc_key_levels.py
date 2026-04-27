"""
Tests for smc_key_levels.KeyLevelsTracker.
Guards the regression where malformed inputs crashed the tick with
"'tuple' object has no attribute 'get'".
"""
import pandas as pd
import pytest

from smc_key_levels import KeyLevelsTracker


class _Swing:
    def __init__(self, index, price):
        self.index = index
        self.price = price


def _df(n=20):
    return pd.DataFrame({
        "ts": list(range(n)),
        "open": [1.0] * n,
        "high": [1.5] * n,
        "low": [0.5] * n,
        "close": [1.0] * n,
        "volume": [100.0] * n,
    })


def test_identify_key_swings_accepts_dict_breaks():
    tr = KeyLevelsTracker()
    df = _df()
    s_low = _Swing(5, 0.4)
    levels = tr.identify_key_swings(
        df, [], [s_low],
        structure_breaks=[{"index": 10, "direction": "bullish"}],
    )
    assert levels and levels[0].direction == "support"


def test_identify_key_swings_accepts_object_breaks():
    tr = KeyLevelsTracker()
    df = _df()
    s_low = _Swing(5, 0.4)

    class SB:
        def __init__(self, idx, dir_):
            self.index = idx
            self.direction = dir_

    levels = tr.identify_key_swings(df, [], [s_low], structure_breaks=[SB(10, "bullish")])
    assert levels


def test_identify_key_swings_skips_malformed_breaks():
    tr = KeyLevelsTracker()
    df = _df()
    s_low = _Swing(5, 0.4)

    # None / tuple / int — all invalid, must not crash
    levels = tr.identify_key_swings(
        df, [], [s_low],
        structure_breaks=[None, (1, 2, 3), 42, "oops"],
    )
    assert levels == []


def test_identify_pool_liquidity_handles_tuple_pairs():
    tr = KeyLevelsTracker()
    df = _df()
    pair = (_Swing(3, 1.2), _Swing(5, 1.2))
    levels = tr.identify_pool_liquidity(df, equal_highs=[pair], equal_lows=[])
    assert levels and levels[0].direction == "resistance"


def test_identify_pool_liquidity_silently_skips_garbage():
    tr = KeyLevelsTracker()
    df = _df()
    # Previously raised 'tuple' object has no attribute 'get'
    levels = tr.identify_pool_liquidity(
        df,
        equal_highs=[(1, 2), None, "x", ()],
        equal_lows=[(_Swing(1, 0.1),)],  # wrong arity
    )
    assert levels == []


def test_is_true_structure_break_ignores_non_key_swing_obstacles():
    tr = KeyLevelsTracker()
    from smc_key_levels import KeyLevel

    tr.key_levels = [
        KeyLevel("pool_liquidity", 99.0, 1, "support", False, 0.6, 0),
    ]
    # A pool-liquidity obstacle must not invalidate a bullish break.
    assert tr.is_true_structure_break(100.0, "bullish") is True


def test_is_true_structure_break_blocked_by_high_importance_key_swing():
    tr = KeyLevelsTracker()
    from smc_key_levels import KeyLevel

    tr.key_levels = [
        KeyLevel("key_swing", 99.0, 1, "support", False, 0.95, 0),
    ]
    assert tr.is_true_structure_break(100.0, "bullish") is False
