"""
SMC Strategy Integration Test Script.
Tests SMC detectors and signal generation on historical data.
"""
import sys
import os
import argparse
from datetime import datetime
import pandas as pd
from dotenv import load_dotenv

from bybit_client import BybitClient
from signal_engine import SignalEngine
from indicators import compute_all
from config import ENABLE_SMC, SYMBOLS
from logger import log

load_dotenv()


def load_historical_data(client: BybitClient, symbol: str, interval: str, limit: int = 300):
    """Load historical candles and compute indicators."""
    log.info(f"Loading {limit} candles for {symbol} ({interval}m)...")
    
    candles = client.get_klines(symbol, interval, limit)
    if candles is None or (isinstance(candles, pd.DataFrame) and candles.empty):
        log.error(f"Failed to load candles for {symbol}")
        return None
    
    df = pd.DataFrame(candles) if not isinstance(candles, pd.DataFrame) else candles
    df = compute_all(df)
    
    log.info(f"Loaded {len(df)} candles with indicators")
    return df


def test_smc_detectors(symbol: str, df_htf: pd.DataFrame, df_ltf: pd.DataFrame):
    """Test SMC detectors and print diagnostics."""
    from smc_structure import StructureDetector
    from smc_orderblock import OrderBlockDetector
    from smc_fvg import FVGDetector
    from config import (
        OB_IMPULSE_THRESHOLD, OB_EXPIRY_CANDLES,
        FVG_MIN_SIZE_ATR, FVG_EXPIRY_CANDLES,
        LIQUIDITY_SWEEP_LOOKBACK,
    )
    
    print(f"\n{'='*70}")
    print(f"  SMC DETECTOR TEST: {symbol}")
    print(f"{'='*70}")
    
    # ── Structure Detector ────────────────────────────────────────────
    print("\n[1] Structure Detector")
    struct_det = StructureDetector()
    
    highs, lows = struct_det.detect_swings(df_htf)
    print(f"  Swing Highs: {len(highs)}")
    print(f"  Swing Lows:  {len(lows)}")
    
    bos = struct_det.detect_bos(df_htf)
    trend = struct_det.get_trend()
    print(f"  Trend: {trend}")
    print(f"  Last BOS: {bos.direction if bos else 'None'}")
    
    current_price = float(df_htf.iloc[-1]["close"])
    pd_ratio = struct_det.get_premium_discount_ratio(current_price, df_htf)
    print(f"  Premium/Discount Ratio: {pd_ratio:.2f}")
    
    sweep = struct_det.check_liquidity_sweep(df_htf, lookback=LIQUIDITY_SWEEP_LOOKBACK)
    print(f"  Recent Liquidity Sweep: {sweep or 'None'}")
    
    eq_highs = struct_det.get_equal_highs()
    eq_lows = struct_det.get_equal_lows()
    print(f"  Equal Highs: {len(eq_highs)}")
    print(f"  Equal Lows:  {len(eq_lows)}")
    
    # ── Order Block Detector ──────────────────────────────────────────
    print("\n[2] Order Block Detector")
    ob_det = OrderBlockDetector(
        impulse_threshold=OB_IMPULSE_THRESHOLD,
        expiry_candles=OB_EXPIRY_CANDLES,
    )
    
    obs = ob_det.detect_order_blocks(df_ltf)
    print(f"  Total Order Blocks: {len(obs)}")
    
    current_idx = len(df_ltf) - 1
    active_obs = ob_det.get_active_order_blocks(current_idx)
    print(f"  Active Order Blocks: {len(active_obs)}")
    
    bullish_obs = [ob for ob in active_obs if ob.direction == "bullish"]
    bearish_obs = [ob for ob in active_obs if ob.direction == "bearish"]
    print(f"    Bullish: {len(bullish_obs)}")
    print(f"    Bearish: {len(bearish_obs)}")
    
    if active_obs:
        print(f"\n  Recent Order Blocks:")
        for ob in active_obs[-5:]:
            age = current_idx - ob.index
            print(f"    {ob.direction:8s} | {ob.low:.4f}-{ob.high:.4f} | "
                  f"strength={ob.strength:.2f} | age={age} candles")
    
    # ── Fair Value Gap Detector ───────────────────────────────────────
    print("\n[3] Fair Value Gap Detector")
    fvg_det = FVGDetector(
        min_size_atr=FVG_MIN_SIZE_ATR,
        expiry_candles=FVG_EXPIRY_CANDLES,
    )
    
    fvgs = fvg_det.detect_fvgs(df_ltf)
    print(f"  Total FVGs: {len(fvgs)}")
    
    fvg_det.update_fill_status(df_ltf)
    active_fvgs = fvg_det.get_active_fvgs(current_idx, max_fill=0.5)
    print(f"  Active FVGs (<50% filled): {len(active_fvgs)}")
    
    bullish_fvgs = [fvg for fvg in active_fvgs if fvg.direction == "bullish"]
    bearish_fvgs = [fvg for fvg in active_fvgs if fvg.direction == "bearish"]
    print(f"    Bullish: {len(bullish_fvgs)}")
    print(f"    Bearish: {len(bearish_fvgs)}")
    
    high_priority = [fvg for fvg in active_fvgs if fvg.high_priority]
    print(f"    High Priority: {len(high_priority)}")
    
    if active_fvgs:
        print(f"\n  Recent FVGs:")
        for fvg in active_fvgs[-5:]:
            age = current_idx - fvg.index
            priority = "⭐" if fvg.high_priority else "  "
            print(f"    {priority} {fvg.direction:8s} | {fvg.low:.4f}-{fvg.high:.4f} | "
                  f"size={fvg.size_atr:.2f}ATR | fill={fvg.fill_percentage*100:.0f}% | age={age}")
    
    print(f"\n{'='*70}\n")


def test_signal_generation(
    symbol: str,
    df_htf: pd.DataFrame,
    df_ltf: pd.DataFrame,
    enable_smc: bool,
):
    """Test signal generation with SMC filters."""
    import config
    
    # Temporarily override ENABLE_SMC
    original_enable_smc = config.ENABLE_SMC
    config.ENABLE_SMC = enable_smc
    
    print(f"\n{'='*70}")
    print(f"  SIGNAL GENERATION TEST: {symbol}")
    print(f"  Mode: {'SMC' if enable_smc else 'Classic'}")
    print(f"{'='*70}")
    
    # Mock equity function
    def get_equity():
        return 100.0  # $100 test equity
    
    # Mock instrument info
    instrument = {
        "min_qty": 0.001,
        "qty_step": 0.001,
        "price_tick": 0.01,
    }
    
    engine = SignalEngine(equity_fn=get_equity, max_positions=3)
    
    signal = engine.analyze(
        symbol=symbol,
        df_htf=df_htf,
        df_ltf=df_ltf,
        equity=100.0,
        drawdown=0.0,
        open_count=0,
        instrument=instrument,
    )
    
    if signal:
        print(f"\n✅ SIGNAL GENERATED:")
        print(f"  Direction: {signal.direction}")
        print(f"  Entry:     {signal.entry:.4f}")
        print(f"  TP:        {signal.tp:.4f} (+{signal.tp_pct:.2f}%)")
        print(f"  SL:        {signal.sl:.4f} (-{signal.sl_pct:.2f}%)")
        print(f"  RR:        1:{signal.rr:.2f}")
        print(f"  Qty:       {signal.qty}")
        print(f"  Reason:    {signal.reason}")
    else:
        print(f"\n❌ NO SIGNAL (filters rejected)")
    
    print(f"\n{'='*70}\n")
    
    # Restore original setting
    config.ENABLE_SMC = original_enable_smc
    
    return signal


def run_comparison(symbol: str, client: BybitClient):
    """Run comparison between classic and SMC strategies."""
    print(f"\n{'#'*70}")
    print(f"  COMPARISON TEST: {symbol}")
    print(f"{'#'*70}\n")
    
    # Load data
    df_htf = load_historical_data(client, symbol, "240", limit=300)
    df_ltf = load_historical_data(client, symbol, "15", limit=300)
    
    if df_htf is None or df_ltf is None:
        log.error(f"Failed to load data for {symbol}")
        return
    
    # Test SMC detectors
    test_smc_detectors(symbol, df_htf, df_ltf)
    
    # Test signal generation (Classic)
    signal_classic = test_signal_generation(symbol, df_htf, df_ltf, enable_smc=False)
    
    # Test signal generation (SMC)
    signal_smc = test_signal_generation(symbol, df_htf, df_ltf, enable_smc=True)
    
    # Summary
    print(f"\n{'='*70}")
    print(f"  COMPARISON SUMMARY: {symbol}")
    print(f"{'='*70}")
    print(f"  Classic Strategy: {'✅ Signal' if signal_classic else '❌ No Signal'}")
    print(f"  SMC Strategy:     {'✅ Signal' if signal_smc else '❌ No Signal'}")
    
    if signal_classic and signal_smc:
        print(f"\n  Both strategies generated signals:")
        print(f"    Classic: {signal_classic.direction} @ {signal_classic.entry:.4f}")
        print(f"    SMC:     {signal_smc.direction} @ {signal_smc.entry:.4f}")
    elif signal_classic and not signal_smc:
        print(f"\n  ⚠️  Classic generated signal but SMC rejected (filters working)")
    elif not signal_classic and signal_smc:
        print(f"\n  ⚠️  SMC generated signal but Classic rejected (unusual)")
    else:
        print(f"\n  Both strategies rejected (no opportunity)")
    
    print(f"{'='*70}\n")


def main():
    parser = argparse.ArgumentParser(description="Test SMC strategy integration")
    parser.add_argument(
        "--symbol",
        type=str,
        default="BTCUSDT",
        help="Symbol to test (default: BTCUSDT)",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Test all configured symbols",
    )
    parser.add_argument(
        "--detectors-only",
        action="store_true",
        help="Only test SMC detectors (no signal generation)",
    )
    
    args = parser.parse_args()
    
    # Initialize client with API keys from .env
    api_key = os.getenv("BYBIT_API_KEY", "")
    api_secret = os.getenv("BYBIT_API_SECRET", "")
    testnet = os.getenv("BYBIT_TESTNET", "false").lower() == "true"
    
    if not api_key or not api_secret:
        log.error("BYBIT_API_KEY and BYBIT_API_SECRET must be set in .env")
        sys.exit(1)
    
    client = BybitClient(api_key, api_secret, testnet)
    
    if args.all:
        symbols = SYMBOLS
    else:
        symbols = [args.symbol]
    
    for symbol in symbols:
        if args.detectors_only:
            # Load data
            df_htf = load_historical_data(client, symbol, "240", limit=300)
            df_ltf = load_historical_data(client, symbol, "15", limit=300)
            
            if df_htf is not None and df_ltf is not None:
                test_smc_detectors(symbol, df_htf, df_ltf)
        else:
            # Full comparison
            run_comparison(symbol, client)
    
    print("\n✅ Test completed!")


if __name__ == "__main__":
    main()
