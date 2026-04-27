"""
OKX-based klines fetcher with the same DataFrame shape as BybitClient.get_klines.
Used for backtesting only (Bybit/Binance APIs are geo-blocked from sandbox).

OKX symbol mapping: BTCUSDT -> BTC-USDT-SWAP, etc.
"""
from __future__ import annotations
import os
import time
import pickle
from typing import Optional

import pandas as pd
import requests


CACHE_DIR = os.path.join(os.path.dirname(__file__), "data_cache")
os.makedirs(CACHE_DIR, exist_ok=True)


# Bybit-interval -> OKX-bar mapping
_BAR_MAP = {
    "1":   "1m",
    "3":   "3m",
    "5":   "5m",
    "15":  "15m",
    "30":  "30m",
    "60":  "1H",
    "120": "2H",
    "240": "4H",
    "360": "6H",
    "720": "12H",
    "D":   "1Dutc",
    "W":   "1Wutc",
    "M":   "1Mutc",
}


# Symbols supported on OKX swaps.  Symbols not on OKX (e.g. MNTUSDT, XAUUSDT)
# will simply be skipped by the backtester.
_INST_MAP_OVERRIDE = {
    # default:  XYZUSDT -> XYZ-USDT-SWAP
}


def to_okx_inst(symbol: str) -> str:
    if symbol in _INST_MAP_OVERRIDE:
        return _INST_MAP_OVERRIDE[symbol]
    if symbol.endswith("USDT"):
        return f"{symbol[:-4]}-USDT-SWAP"
    return symbol


def _bar_ms(bar: str) -> int:
    table = {
        "1m": 60_000, "3m": 180_000, "5m": 300_000, "15m": 900_000, "30m": 1_800_000,
        "1H": 3_600_000, "2H": 7_200_000, "4H": 14_400_000, "6H": 21_600_000, "12H": 43_200_000,
        "1Dutc": 86_400_000, "1Wutc": 7 * 86_400_000, "1Mutc": 30 * 86_400_000,
    }
    return table[bar]


def _fetch_page(inst: str, bar: str, after_ms: Optional[int] = None, limit: int = 300) -> list:
    """Fetch one page of OKX klines (oldest 300 ending at `after_ms`)."""
    params = {"instId": inst, "bar": bar, "limit": str(limit)}
    if after_ms is not None:
        params["after"] = str(after_ms)
    for attempt in range(5):
        try:
            r = requests.get("https://www.okx.com/api/v5/market/history-candles",
                             params=params, timeout=15)
            if r.status_code == 429:
                time.sleep(1 + attempt)
                continue
            r.raise_for_status()
            data = r.json()
            if data.get("code") != "0":
                raise RuntimeError(f"OKX error: {data}")
            return data.get("data", [])
        except Exception as e:
            if attempt == 4:
                raise
            time.sleep(1 + attempt)
    return []


def fetch_history(symbol: str, interval: str, total_candles: int = 5000,
                  use_cache: bool = True) -> pd.DataFrame:
    """Fetch up to `total_candles` of historical klines, returning Bybit-style DF."""
    inst = to_okx_inst(symbol)
    bar = _BAR_MAP[interval]
    cache_key = f"{symbol}_{interval}_{total_candles}.pkl"
    cache_path = os.path.join(CACHE_DIR, cache_key)

    if use_cache and os.path.exists(cache_path):
        with open(cache_path, "rb") as f:
            return pickle.load(f)

    rows: list = []
    after_ms: Optional[int] = None
    bar_step = _bar_ms(bar)

    while len(rows) < total_candles:
        page = _fetch_page(inst, bar, after_ms=after_ms, limit=300)
        if not page:
            break
        rows.extend(page)
        # OKX returns newest first; oldest in page is page[-1]
        oldest_ts = int(page[-1][0])
        after_ms = oldest_ts  # next call returns candles before this
        if len(page) < 300:
            break
        time.sleep(0.05)  # gentle rate-limit

    if not rows:
        return pd.DataFrame()

    # Deduplicate by ts (keep newest)
    df = pd.DataFrame(rows, columns=[
        "ts", "open", "high", "low", "close", "volume", "turnover", "vol_ccy_quote", "confirm"
    ])
    df = df.drop_duplicates(subset="ts", keep="first")
    df = df.astype({"ts": int})
    df = df.astype({"open": float, "high": float, "low": float, "close": float, "volume": float})
    df = df[["ts", "open", "high", "low", "close", "volume"]]
    df.sort_values("ts", inplace=True)
    df.reset_index(drop=True, inplace=True)
    df["datetime"] = pd.to_datetime(df["ts"], unit="ms", utc=True)

    if use_cache:
        with open(cache_path, "wb") as f:
            pickle.dump(df, f)

    return df


# Default instrument info (sufficient for backtest sizing checks)
_INSTRUMENT_INFO = {
    "BTCUSDT":  {"min_qty": 0.001, "qty_step": 0.001, "min_price": 0.1,    "price_tick": 0.1},
    "ETHUSDT":  {"min_qty": 0.01,  "qty_step": 0.01,  "min_price": 0.01,   "price_tick": 0.01},
    "SOLUSDT":  {"min_qty": 0.1,   "qty_step": 0.1,   "min_price": 0.001,  "price_tick": 0.001},
    "XRPUSDT":  {"min_qty": 1.0,   "qty_step": 1.0,   "min_price": 0.0001, "price_tick": 0.0001},
    "DOGEUSDT": {"min_qty": 1.0,   "qty_step": 1.0,   "min_price": 0.00001,"price_tick": 0.00001},
    "MNTUSDT":  {"min_qty": 1.0,   "qty_step": 1.0,   "min_price": 0.0001, "price_tick": 0.0001},
    "XAUUSDT":  {"min_qty": 0.01,  "qty_step": 0.01,  "min_price": 0.01,   "price_tick": 0.01},
}


def get_instrument(symbol: str) -> dict:
    return dict(_INSTRUMENT_INFO.get(symbol, _INSTRUMENT_INFO["BTCUSDT"]))


if __name__ == "__main__":
    df = fetch_history("BTCUSDT", "15", total_candles=600, use_cache=False)
    print(df.head())
    print(df.tail())
    print("rows:", len(df), "span:", df["datetime"].iloc[0], "->", df["datetime"].iloc[-1])
