from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from types import SimpleNamespace

import pandas as pd

from smc_key_levels import KeyLevelsTracker
from smc_orderflow import LiquidityPool, OrderFlowDetector, OrderFlowPhase


def test_orderflow_tracks_internal_and_external_sweeps_and_targets():
    detector = OrderFlowDetector()
    swings_high = [SimpleNamespace(index=1, price=105.0), SimpleNamespace(index=2, price=111.0)]
    swings_low = [SimpleNamespace(index=3, price=95.0), SimpleNamespace(index=4, price=89.0)]
    df = pd.DataFrame({
        'open': [100, 104, 110, 96, 90, 100],
        'high': [101, 105, 111, 97, 91, 112],
        'low': [99, 103, 109, 95, 89, 88],
        'close': [100, 104.5, 110.5, 95.5, 89.5, 100],
        'ts': list(range(6)),
    })

    internal, external = detector.detect_liquidity_pools(
        df, swings_high=swings_high, swings_low=swings_low,
        trading_range_high=106.0, trading_range_low=94.0,
    )
    assert {p.pool_type for p in internal} == {'internal'}
    assert {p.pool_type for p in external} == {'external'}

    sweeps = detector.track_liquidity_sweeps(df, current_idx=5)
    assert len(sweeps) == 4
    assert any(s['pool_type'] == 'internal' and s['direction'] == 'bullish' for s in sweeps)
    assert any(s['pool_type'] == 'external' and s['direction'] == 'bearish' for s in sweeps)

    assert detector.get_next_liquidity_target(100.0, 'bullish') is None
    assert detector.get_next_liquidity_target(100.0, 'bearish') is None

    detector.order_flow_phases = [OrderFlowPhase('complete_sequence', 2, 5, 'bullish')]
    assert detector.is_valid_order_flow(current_idx=6, direction='bullish') is True
    assert detector.is_valid_order_flow(current_idx=6, direction='bearish') is False


def test_key_levels_tracker_builds_priority_stack_from_swings_zones_and_pools():
    tracker = KeyLevelsTracker()
    df = pd.DataFrame({
        'open': [100, 99, 101, 102, 98],
        'high': [101, 100, 102, 103, 99],
        'low': [99, 98, 100, 101, 97],
        'close': [100, 99.5, 101.2, 102.1, 98.4],
        'ts': list(range(5)),
    })

    swings_high = [SimpleNamespace(index=1, price=100.0), SimpleNamespace(index=3, price=103.0)]
    swings_low = [SimpleNamespace(index=0, price=99.0), SimpleNamespace(index=4, price=97.0)]
    structure_breaks = [
        {'index': 4, 'direction': 'bullish'},
        {'index': 3, 'direction': 'bearish'},
    ]

    key_swings = tracker.identify_key_swings(df, swings_high, swings_low, structure_breaks)
    assert len(key_swings) == 2
    assert {k.direction for k in key_swings} == {'support', 'resistance'}

    order_blocks = [SimpleNamespace(index=1, high=100.5, low=99.5, direction='bullish', tested=False)]
    fvgs = [SimpleNamespace(index=2, high=102.0, low=101.0, direction='bullish', fill_percentage=0.2)]
    breakers = [SimpleNamespace(original_ob=SimpleNamespace(high=103.0, low=102.0), break_index=3, new_direction='bearish')]
    mitigations = [SimpleNamespace(index=4, high=98.8, low=97.8, direction='bullish')]
    untested = tracker.identify_untested_zones(df, order_blocks, fvgs, breakers, mitigations)
    assert any(level.importance == 0.95 for level in untested)
    assert any(level.level_type == 'untested_zone' for level in untested)

    equal_highs = [(SimpleNamespace(index=1, price=100.0), SimpleNamespace(index=3, price=100.0))]
    equal_lows = [(SimpleNamespace(index=0, price=99.0), SimpleNamespace(index=4, price=99.0))]
    pools = tracker.identify_pool_liquidity(df, equal_highs, equal_lows)
    assert len(pools) == 2
    assert {p.direction for p in pools} == {'support', 'resistance'}
