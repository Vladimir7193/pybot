"""
Compare STRICT vs RELAXED mode signal generation.
Shows how many signals each mode generates.
"""
import sys
import os
from dotenv import load_dotenv
load_dotenv()

# Temporarily override config
import config
original_mode = config.SMC_MODE

print("="*60)
print("  SMC MODE COMPARISON TEST")
print("="*60)

from signal_engine import SignalEngine
from bybit_client import BybitClient
from indicators import compute_all

# Initialize
api_key = os.getenv("BYBIT_API_KEY")
api_secret = os.getenv("BYBIT_API_SECRET")

if not api_key or not api_secret:
    print("⚠️  No API keys found")
    sys.exit(0)

client = BybitClient(api_key=api_key, api_secret=api_secret)
symbol = "BTCUSDT"

# Fetch data once
print(f"\nFetching data for {symbol}...")
df_htf = client.get_klines(symbol, "240", limit=300)
df_ltf = client.get_klines(symbol, "15", limit=300)
df_htf = compute_all(df_htf)
df_ltf = compute_all(df_ltf)

instrument_info = client.get_instrument_info(symbol)
instrument = {
    "min_qty": instrument_info.get("lotSizeFilter", {}).get("minOrderQty", 0.001),
    "qty_step": instrument_info.get("lotSizeFilter", {}).get("qtyStep", 0.001),
    "price_tick": instrument_info.get("priceFilter", {}).get("tickSize", 0.01),
}

print(f"Data ready: HTF={len(df_htf)} candles, LTF={len(df_ltf)} candles")

# Test STRICT mode
print("\n" + "="*60)
print("  TEST 1: STRICT MODE (all filters REQUIRED)")
print("="*60)
config.SMC_MODE = "STRICT"
engine_strict = SignalEngine(equity_fn=lambda: 100.0, max_positions=3)

signal_strict = engine_strict.analyze(
    symbol=symbol,
    df_htf=df_htf,
    df_ltf=df_ltf,
    equity=100.0,
    drawdown=0.0,
    open_count=0,
    instrument=instrument,
)

if signal_strict:
    print(f"\n[OK] STRICT MODE SIGNAL:")
    print(f"  {signal_strict.direction} @ {signal_strict.entry:.4f}")
    print(f"  Reason: {signal_strict.reason}")
else:
    print(f"\n[WARN] STRICT MODE: No signal (filters too strict)")

# Test RELAXED mode
print("\n" + "="*60)
print("  TEST 2: RELAXED MODE (only Premium/Discount REQUIRED)")
print("="*60)
config.SMC_MODE = "RELAXED"
engine_relaxed = SignalEngine(equity_fn=lambda: 100.0, max_positions=3)

signal_relaxed = engine_relaxed.analyze(
    symbol=symbol,
    df_htf=df_htf,
    df_ltf=df_ltf,
    equity=100.0,
    drawdown=0.0,
    open_count=0,
    instrument=instrument,
)

if signal_relaxed:
    print(f"\n[OK] RELAXED MODE SIGNAL:")
    print(f"  {signal_relaxed.direction} @ {signal_relaxed.entry:.4f}")
    print(f"  Reason: {signal_relaxed.reason}")
else:
    print(f"\n[WARN] RELAXED MODE: No signal")

# Summary
print("\n" + "="*60)
print("  SUMMARY")
print("="*60)
print(f"  STRICT mode:  {'[OK] Signal' if signal_strict else '[X] No signal'}")
print(f"  RELAXED mode: {'[OK] Signal' if signal_relaxed else '[X] No signal'}")
print(f"\n  Recommendation:")
if signal_strict:
    print(f"    Use STRICT mode for Márko's methodology")
elif signal_relaxed:
    print(f"    Use RELAXED mode for more signals (less strict)")
else:
    print(f"    No signals in current market conditions")

# Restore original config
config.SMC_MODE = original_mode
print(f"\n[OK] Test completed")
