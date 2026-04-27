"""
Technical indicators computed on pandas DataFrames.
All functions expect a DataFrame with columns: open, high, low, close, volume.
"""
import numpy as np
import pandas as pd
from config import (
    EMA_FAST, EMA_SLOW, SMA_TREND,
    RSI_PERIOD, ATR_PERIOD, ATR_AVG_PERIOD,
    MACD_FAST, MACD_SLOW, MACD_SIG,
    BB_PERIOD, BB_STD,
)


def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def sma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(period).mean()


def rsi(series: pd.Series, period: int = RSI_PERIOD) -> pd.Series:
    delta = series.diff()
    gain  = delta.clip(lower=0)
    loss  = (-delta.clip(upper=0))
    avg_gain = gain.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    rs    = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def atr(df: pd.DataFrame, period: int = ATR_PERIOD) -> pd.Series:
    h, l, pc = df["high"], df["low"], df["close"].shift(1)
    tr = pd.concat([
        h - l,
        (h - pc).abs(),
        (l - pc).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def macd(series: pd.Series, fast=MACD_FAST, slow=MACD_SLOW, sig=MACD_SIG):
    fast_ema = ema(series, fast)
    slow_ema = ema(series, slow)
    macd_line = fast_ema - slow_ema
    signal    = ema(macd_line, sig)
    hist      = macd_line - signal
    return macd_line, signal, hist


def bollinger(series: pd.Series, period=BB_PERIOD, std_mult=BB_STD):
    mid   = sma(series, period)
    std   = series.rolling(period).std()
    upper = mid + std_mult * std
    lower = mid - std_mult * std
    return upper, mid, lower


def vwap(df: pd.DataFrame) -> pd.Series:
    tp  = (df["high"] + df["low"] + df["close"]) / 3
    cum_vol = df["volume"].cumsum()
    cum_tp  = (tp * df["volume"]).cumsum()
    return cum_tp / cum_vol.replace(0, np.nan)


def compute_all(df: pd.DataFrame) -> pd.DataFrame:
    """Add all indicator columns to df in-place and return it."""
    c = df["close"]

    df["ema20"]    = ema(c, EMA_FAST)
    df["ema50"]    = ema(c, EMA_SLOW)
    df["sma200"]   = sma(c, SMA_TREND)
    df["rsi"]      = rsi(c, RSI_PERIOD)
    df["atr"]      = atr(df, ATR_PERIOD)
    df["atr_avg"]  = df["atr"].rolling(ATR_AVG_PERIOD).mean()

    df["macd"], df["macd_sig"], df["macd_hist"] = macd(c)

    df["bb_upper"], df["bb_mid"], df["bb_lower"] = bollinger(c)
    df["vwap"]     = vwap(df)

    # HolonomyField: normalised aggregate signal (-1 .. +1)
    # Combines RSI deviation, MACD histogram direction, EMA alignment
    rsi_norm  = (df["rsi"] - 50) / 50                          # -1..+1
    macd_norm = df["macd_hist"].apply(np.sign)                  # -1/0/+1
    ema_align = np.sign(df["ema20"] - df["ema50"])              # -1/0/+1
    df["holonomy"] = (rsi_norm * 0.4 + macd_norm * 0.3 + ema_align * 0.3)

    # AnomalyLevel: ratio of current ATR to average ATR
    df["anomaly"] = df["atr"] / df["atr_avg"].replace(0, np.nan)

    return df
