"""
Test script for SMC strategy.
Loads historical data and tests SMC signal generation.
"""
import os
from dotenv import load_dotenv

from config import SYMBOLS, HTF, LTF, ENABLE_SMC
from bybit_client import BybitClient
from indicators import compute_all
from signal_engine import SignalEngine
from logger import log

load_dotenv()


def test_smc_on_symbol(client: BybitClient, symbol: str):
    """Test SMC strategy on one symbol."""
    log.info(f"\n{'='*60}")
    log.info(f"  Testing SMC on {symbol}")
    log.info(f"{'='*60}")
    
    # Load data
    df_htf = client.get_klines(symbol, HTF, limit=300)
    df_ltf = client.get_klines(symbol, LTF, limit=300)
    
    if df_htf.empty or df_ltf.empty:
        log.error(f"[{symbol}] Failed to load data")
        return
    
    # Compute indicators
    df_htf = compute_all(df_htf)
    df_ltf = compute_all(df_ltf)
    
    log.info(f"[{symbol}] Loaded {len(df_htf)} HTF candles, {len(df_ltf)} LTF candles")
    
    # Create signal engine
    engine = SignalEngine(equity_fn=lambda: 1000.0, max_positions=3)
    
    # Get instrument info
    try:
        instrument = client.get_instrument_info(symbol)
    except Exception as e:
        log.error(f"[{symbol}] Failed to get instrument info: {e}")
        return
    
    # Test signal generation
    signal = engine.analyze(
        symbol=symbol,
        df_htf=df_htf,
        df_ltf=df_ltf,
        equity=1000.0,
        drawdown=0.0,
        open_count=0,
        instrument=instrument,
    )
    
    if signal:
        log.info(f"\n✅ SIGNAL GENERATED:")
        log.info(f"  Direction: {signal.direction}")
        log.info(f"  Entry: {signal.entry:.4f}")
        log.info(f"  TP: {signal.tp:.4f} (+{signal.tp_pct:.2f}%)")
        log.info(f"  SL: {signal.sl:.4f} (-{signal.sl_pct:.2f}%)")
        log.info(f"  RR: 1:{signal.rr:.2f}")
        log.info(f"  Reason: {signal.reason}")
    else:
        log.info(f"\n❌ NO SIGNAL (filters rejected)")


def main():
    log.info("="*60)
    log.info(f"  SMC Strategy Test (ENABLE_SMC={ENABLE_SMC})")
    log.info("="*60)
    
    # Connect to Bybit
    api_key = os.getenv("BYBIT_API_KEY", "")
    api_secret = os.getenv("BYBIT_API_SECRET", "")
    testnet = os.getenv("BYBIT_TESTNET", "false").lower() == "true"
    
    client = BybitClient(api_key, api_secret, testnet)
    
    # Test on first 3 symbols
    test_symbols = SYMBOLS[:3]
    
    for symbol in test_symbols:
        try:
            test_smc_on_symbol(client, symbol)
        except Exception as e:
            log.error(f"[{symbol}] Test failed: {e}", exc_info=True)
    
    log.info(f"\n{'='*60}")
    log.info("  Test completed")
    log.info(f"{'='*60}")


if __name__ == "__main__":
    main()
