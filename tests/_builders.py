"""Shared test fixtures for signal engine tests.

Synthesises deterministic OHLCV dataframes that are rich enough for the
full SMC pipeline to run without external data.
"""
from __future__ import annotations

import math
from typing import Literal

import numpy as np
import pandas as pd

import indicators


def make_trend_df(
    n: int = 300,
    start_price: float = 100.0,
    direction: Literal["up", "down", "flat"] = "up",
    slope: float = 0.2,
    noise: float = 0.4,
    atr_bias: float = 1.0,
    seed: int = 7,
    interval_min: int = 15,
) -> pd.DataFrame:
    """Build a synthetic OHLCV dataframe with a clear directional bias.

    The last bar is intentionally "loud" (wide range) so tests can verify
    it is NOT leaked into the signal decision.
    """
    rng = np.random.default_rng(seed)
    ts0 = 1_700_000_000_000
    step_ms = interval_min * 60 * 1000

    closes = np.zeros(n)
    closes[0] = start_price
    for i in range(1, n):
        drift = slope * (1 if direction == "up" else -1 if direction == "down" else 0)
        closes[i] = closes[i - 1] + drift + rng.normal(0, noise)

    opens = np.concatenate([[closes[0]], closes[:-1]])
    highs = np.maximum(opens, closes) + np.abs(rng.normal(0, atr_bias, n))
    lows = np.minimum(opens, closes) - np.abs(rng.normal(0, atr_bias, n))
    vols = rng.uniform(100, 1000, n)
    ts = ts0 + np.arange(n) * step_ms

    df = pd.DataFrame({
        "ts": ts,
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": vols,
    })
    return df


def make_future_leak_df(
    n: int = 300,
    direction: Literal["up", "down", "flat"] = "up",
    spike_bars: int = 1,
    spike_size: float = 40.0,
    seed: int = 42,
) -> pd.DataFrame:
    """Build a dataframe whose LAST ``spike_bars`` bars are extreme outliers.

    A future-leak bug shows up as the engine's decision depending on these
    bars; a clean implementation must ignore them.
    """
    df = make_trend_df(n=n, direction=direction, seed=seed)
    for k in range(1, spike_bars + 1):
        idx = n - k
        df.loc[idx, "high"] = df.loc[idx, "high"] + spike_size
        df.loc[idx, "low"] = df.loc[idx, "low"] - spike_size
        df.loc[idx, "close"] = df.loc[idx, "close"] + spike_size
    return df


def fake_instrument() -> dict:
    return {
        "price_tick": 0.01,
        "qty_step":   0.001,
        "min_qty":    0.001,
    }


def full_frames(n_htf: int = 260, n_ltf: int = 80, n_ctf: int = 220,
                direction: Literal["up", "down", "flat"] = "up",
                seed: int = 11):
    """Return (df_htf, df_ltf, df_ctf) with indicators computed."""
    df_htf = indicators.compute_all(make_trend_df(n=n_htf, direction=direction, seed=seed, interval_min=240))
    df_ltf = indicators.compute_all(make_trend_df(n=n_ltf, direction=direction, seed=seed + 1, interval_min=15))
    df_ctf = indicators.compute_all(make_trend_df(n=n_ctf, direction=direction, seed=seed + 2, interval_min=1440))
    return df_htf, df_ltf, df_ctf
