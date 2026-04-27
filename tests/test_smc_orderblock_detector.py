from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from types import SimpleNamespace

import pandas as pd

from smc_orderblock import OrderBlock, OrderBlockDetector


def test_detects_bearish_breaker_from_broken_bullish_order_block():
    detector = OrderBlockDetector(impulse_threshold=0.5, expiry_candles=50)
    ob = OrderBlock(index=1, high=101.0, low=99.0, direction='bullish', tested=False, timestamp=1, strength=1.5)
    detector.order_blocks = [ob]

    df = pd.DataFrame({
        'open': [100.0, 100.5, 100.0, 98.5],
        'high': [101.0, 101.0, 100.2, 99.0],
        'low': [99.0, 99.4, 97.6, 97.8],
        'close': [100.2, 100.0, 98.0, 98.7],
        'atr': [1.0, 1.0, 1.0, 1.0],
        'ts': list(range(4)),
    })

    breakers = detector.detect_breaker_blocks(df)
    assert len(breakers) == 1
    breaker = breakers[0]
    assert breaker.new_direction == 'bearish'
    assert detector.is_price_in_breaker(100.0, 'bearish', current_idx=3) is breaker
    assert detector.is_price_in_breaker(100.0, 'bullish', current_idx=3) is None


def test_detects_bullish_mitigation_when_previous_low_not_swept():
    detector = OrderBlockDetector()
    swings_low = [
        SimpleNamespace(index=1, price=98.0),
        SimpleNamespace(index=3, price=98.5),
    ]
    swings_high = []
    df = pd.DataFrame({
        'open': [101.0, 99.0, 100.0, 99.2, 100.5],
        'high': [102.0, 100.0, 101.0, 100.0, 101.0],
        'low': [100.0, 98.0, 98.2, 98.5, 99.5],
        'close': [100.5, 98.8, 100.2, 99.0, 100.8],
        'atr': [1.0, 1.0, 1.0, 1.0, 1.0],
        'ts': list(range(5)),
    })

    mitigations = detector.detect_mitigation_blocks(df, swings_high=swings_high, swings_low=swings_low)
    assert len(mitigations) == 1
    mitigation = mitigations[0]
    assert mitigation.direction == 'bullish'
    assert mitigation.failed_to_break == 98.0

    detector.mitigation_blocks = mitigations
    assert detector.is_price_in_mitigation(99.0, 'bullish', current_idx=4) is mitigation
