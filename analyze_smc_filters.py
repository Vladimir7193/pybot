"""
Анализ SMC фильтров - показывает статистику прохождения каждого фильтра.
"""
import os
from dotenv import load_dotenv
from collections import Counter

from config import SYMBOLS, HTF, LTF
from bybit_client import BybitClient
from indicators import compute_all
from smc_structure import StructureDetector
from logger import log

load_dotenv()


def analyze_filters(client: BybitClient, symbol: str):
    """Анализ прохождения SMC фильтров."""
    log.info(f"\n{'='*60}")
    log.info(f"  Analyzing {symbol}")
    log.info(f"{'='*60}")
    
    # Load data
    df_htf = client.get_klines(symbol, HTF, limit=1000)
    df_ltf = client.get_klines(symbol, LTF, limit=1000)
    
    if df_htf.empty or df_ltf.empty:
        return
    
    df_htf = compute_all(df_htf)
    df_ltf = compute_all(df_ltf)
    
    struct_det = StructureDetector()
    
    # Detect structure
    struct_det.detect_swings(df_htf)
    struct_det.detect_bos(df_htf)
    
    log.info(f"  Swing Highs: {len(struct_det.swings_high)}")
    log.info(f"  Swing Lows: {len(struct_det.swings_low)}")
    log.info(f"  Current Trend: {struct_det.trend}")
    log.info(f"  Last BOS: {struct_det.last_bos}")
    
    # Check liquidity sweeps
    sweep = struct_det.check_liquidity_sweep(df_htf, lookback=10)
    log.info(f"  Recent Sweep: {sweep}")
    
    # Check equal highs/lows
    eq_highs = struct_det.get_equal_highs()
    eq_lows = struct_det.get_equal_lows()
    log.info(f"  Equal Highs: {len(eq_highs)}")
    log.info(f"  Equal Lows: {len(eq_lows)}")
    
    # Check premium/discount distribution
    prices = df_htf["close"].tail(100)
    pd_ratios = [struct_det.get_premium_discount_ratio(float(p), df_htf) for p in prices]
    
    discount_count = sum(1 for r in pd_ratios if r < 0.5)
    premium_count = sum(1 for r in pd_ratios if r > 0.5)
    
    log.info(f"  Last 100 candles:")
    log.info(f"    Discount zone: {discount_count}%")
    log.info(f"    Premium zone: {premium_count}%")
    log.info(f"    Current PD ratio: {pd_ratios[-1]:.2f}")


def main():
    log.info("="*60)
    log.info("  SMC Filters Analysis")
    log.info("="*60)
    
    api_key = os.getenv("BYBIT_API_KEY", "")
    api_secret = os.getenv("BYBIT_API_SECRET", "")
    testnet = os.getenv("BYBIT_TESTNET", "false").lower() == "true"
    
    client = BybitClient(api_key, api_secret, testnet)
    
    for symbol in SYMBOLS[:3]:
        try:
            analyze_filters(client, symbol)
        except Exception as e:
            log.error(f"[{symbol}] Error: {e}", exc_info=True)


if __name__ == "__main__":
    main()
