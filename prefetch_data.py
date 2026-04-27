"""Prefetch and cache historical klines from OKX for backtesting."""
from okx_klines import fetch_history

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT"]

# (interval, candle count)
TIMEFRAMES = [
    ("15", 5760),    # ~60 days of 15m
    ("240", 720),    # ~120 days of 4h
    ("D",  200),     # ~200 days of daily
]


def main():
    for sym in SYMBOLS:
        for tf, count in TIMEFRAMES:
            df = fetch_history(sym, tf, total_candles=count, use_cache=True)
            print(f"{sym:10s}  tf={tf:>3s}  rows={len(df):5d}  "
                  f"span={df['datetime'].iloc[0]} -> {df['datetime'].iloc[-1]}")


if __name__ == "__main__":
    main()
