from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd

from smc_fvg import FVGDetector


def test_detects_bullish_fvg_marks_priority_and_partial_fill():
    df = pd.DataFrame({
        'open': [99.0, 100.0, 103.0, 102.0, 102.4],
        'high': [100.0, 103.0, 104.0, 103.2, 102.6],
        'low': [98.0, 99.5, 102.0, 101.0, 100.4],
        'close': [99.5, 102.5, 103.5, 101.8, 101.2],
        'atr': [2.0, 2.0, 2.0, 2.0, 2.0],
        'ts': list(range(5)),
    })
    detector = FVGDetector(min_size_atr=0.3, expiry_candles=10)

    fvgs = detector.detect_fvgs(df.iloc[:3], liquidity_sweep_indices=[1])
    assert len(fvgs) == 1
    fvg = fvgs[0]
    assert fvg.direction == 'bullish'
    assert fvg.low == 100.0
    assert fvg.high == 102.0
    assert fvg.high_priority is True

    detector.update_fill_status(df)
    assert 0.0 < fvg.fill_percentage < 1.0
    assert detector.is_price_in_fvg(101.0, 'bullish', current_idx=4) is fvg
    assert detector.get_active_fvgs(current_idx=4, direction='bullish', max_fill=0.9) == [fvg]


def test_cleanup_removes_fully_filled_and_expired_fvgs():
    df = pd.DataFrame({
        'open': [105.0, 103.0, 100.0, 102.0],
        'high': [106.0, 104.0, 101.0, 105.5],
        'low': [104.0, 103.0, 99.0, 98.0],
        'close': [104.5, 103.2, 100.5, 104.8],
        'atr': [2.0, 2.0, 2.0, 2.0],
        'ts': list(range(4)),
    })
    detector = FVGDetector(min_size_atr=0.3, expiry_candles=1)
    fvgs = detector.detect_fvgs(df.iloc[:3])
    assert len(fvgs) == 1
    fvg = fvgs[0]
    assert fvg.direction == 'bearish'

    detector.update_fill_status(df)
    assert fvg.fill_percentage == 1.0
    detector.cleanup_expired(current_idx=3)
    assert detector.fvgs == []
