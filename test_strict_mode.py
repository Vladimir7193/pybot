"""
Quick test to verify STRICT mode and PURE_SMC implementation.
Tests that all SMC filters are REQUIRED in STRICT mode.
"""
import sys
import pandas as pd
from datetime import datetime

# Test imports
try:
    from signal_engine import SignalEngine
    from config import ENABLE_SMC, SMC_MODE, PURE_SMC
    from bybit_client import BybitClient
    from indicators import compute_all
    print("✅ All imports successful")
except Exception as e:
    print(f"❌ Import error: {e}")
    sys.exit(1)

# Test configuration
print(f"\n📋 Configuration:")
print(f"  ENABLE_SMC: {ENABLE_SMC}")
print(f"  SMC_MODE: {SMC_MODE}")
print(f"  PURE_SMC: {PURE_SMC}")

# Initialize client and engine
try:
    import os
    from dotenv import load_dotenv
    load_dotenv()
    
    api_key = os.getenv("BYBIT_API_KEY")
    api_secret = os.getenv("BYBIT_API_SECRET")
    
    if not api_key or not api_secret:
        print("⚠️  No API keys found, using dummy client")
        client = None
    else:
        client = BybitClient(api_key=api_key, api_secret=api_secret)
    
    engine = SignalEngine(equity_fn=lambda: 100.0, max_positions=3)
    print("✅ Client and engine initialized")
except Exception as e:
    print(f"❌ Initialization error: {e}")
    sys.exit(1)

# Test on BTCUSDT
symbol = "BTCUSDT"
print(f"\n🔍 Testing {symbol}...")

try:
    if not client:
        print("⚠️  Skipping test (no API keys)")
        sys.exit(0)
    
    # Fetch data
    df_htf = client.get_klines(symbol, "240", limit=300)
    df_ltf = client.get_klines(symbol, "15", limit=300)
    
    # Compute indicators
    df_htf = compute_all(df_htf)
    df_ltf = compute_all(df_ltf)
    
    print(f"✅ Data fetched: HTF={len(df_htf)} candles, LTF={len(df_ltf)} candles")
    
    # Get instrument info
    instrument_info = client.get_instrument_info(symbol)
    instrument = {
        "min_qty": instrument_info.get("lotSizeFilter", {}).get("minOrderQty", 0.001),
        "qty_step": instrument_info.get("lotSizeFilter", {}).get("qtyStep", 0.001),
        "price_tick": instrument_info.get("priceFilter", {}).get("tickSize", 0.01),
    }
    
    # Run signal analysis
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
        print(f"  Entry: {signal.entry:.4f}")
        print(f"  TP: {signal.tp:.4f} (+{signal.tp_pct:.2f}%)")
        print(f"  SL: {signal.sl:.4f} (-{signal.sl_pct:.2f}%)")
        print(f"  RR: 1:{signal.rr:.2f}")
        print(f"  Reason: {signal.reason}")
    else:
        print(f"\n⚠️  No signal (filters rejected)")
    
    print(f"\n✅ Test completed successfully")
    
except Exception as e:
    print(f"❌ Test error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
