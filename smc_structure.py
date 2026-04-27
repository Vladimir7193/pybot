"""
Smart Money Concepts: Structure detection.
Implements swing detection, BOS/CHoCH, trading range identification.

Боевые правки:
- bias определяется не только свежим BOS/CHoCH, но и по уже сложившейся swing-структуре;
- структура считается по закрытой свече (по умолчанию), чтобы не дёргаться на незакрытом баре;
- последний подтверждённый bias сохраняется между свечами и не сбрасывается в ranging без причины.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, List
import pandas as pd


@dataclass
class Swing:
    """5-candle swing high or low."""
    index: int
    price: float
    is_high: bool
    timestamp: int


@dataclass
class StructureBreak:
    """Break of Structure (BOS) or Change of Character (CHoCH)."""
    index: int
    price: float
    direction: str     # "bullish" | "bearish"
    type: str          # "BOS" | "CHoCH"
    prev_swing: Swing


class StructureDetector:
    """Detects market structure: swings, BOS, CHoCH, trading ranges."""

    def __init__(self):
        self.swings_high: List[Swing] = []
        self.swings_low: List[Swing] = []
        self.last_bos: Optional[StructureBreak] = None
        self.trend: str = "ranging"
        self.bias_source: str = "none"  # bos | structure | persisted | none

    def detect_swings(self, df: pd.DataFrame) -> tuple[List[Swing], List[Swing]]:
        """Find all 5-candle swing highs and lows on recent history."""
        start_idx = max(0, len(df) - 200)
        df_recent = df.iloc[start_idx:]

        highs: List[Swing] = []
        lows: List[Swing] = []
        for i in range(2, len(df_recent) - 2):
            actual_idx = start_idx + i

            if (
                df_recent.iloc[i]["high"] > df_recent.iloc[i - 1]["high"]
                and df_recent.iloc[i]["high"] > df_recent.iloc[i - 2]["high"]
                and df_recent.iloc[i]["high"] > df_recent.iloc[i + 1]["high"]
                and df_recent.iloc[i]["high"] > df_recent.iloc[i + 2]["high"]
            ):
                highs.append(
                    Swing(
                        index=actual_idx,
                        price=float(df_recent.iloc[i]["high"]),
                        is_high=True,
                        timestamp=int(df_recent.iloc[i]["ts"]),
                    )
                )

            if (
                df_recent.iloc[i]["low"] < df_recent.iloc[i - 1]["low"]
                and df_recent.iloc[i]["low"] < df_recent.iloc[i - 2]["low"]
                and df_recent.iloc[i]["low"] < df_recent.iloc[i + 1]["low"]
                and df_recent.iloc[i]["low"] < df_recent.iloc[i + 2]["low"]
            ):
                lows.append(
                    Swing(
                        index=actual_idx,
                        price=float(df_recent.iloc[i]["low"]),
                        is_high=False,
                        timestamp=int(df_recent.iloc[i]["ts"]),
                    )
                )

        self.swings_high = highs
        self.swings_low = lows
        return highs, lows

    def infer_bias_from_swings(self) -> str:
        """
        Infer current directional bias from the latest confirmed swing sequence.
        This is more stable than waiting for a fresh BOS on every candle.
        """
        if len(self.swings_high) < 2 or len(self.swings_low) < 2:
            return self.trend if self.trend in {"bullish", "bearish"} else "ranging"

        last_high = self.swings_high[-1]
        prev_high = self.swings_high[-2]
        last_low = self.swings_low[-1]
        prev_low = self.swings_low[-2]

        bullish = last_high.price > prev_high.price and last_low.price > prev_low.price
        bearish = last_high.price < prev_high.price and last_low.price < prev_low.price

        if bullish and not bearish:
            return "bullish"
        if bearish and not bullish:
            return "bearish"

        # Mixed structure: keep the last confirmed directional bias if it existed.
        return self.trend if self.trend in {"bullish", "bearish"} else "ranging"

    def resolve_trend(self, df: pd.DataFrame, use_closed_candle: bool = True) -> str:
        """Refresh swings, try BOS/CHoCH, then stable swing-based bias fallback."""
        self.detect_swings(df)
        bos = self.detect_bos(df, use_closed_candle=use_closed_candle)
        if bos is not None:
            self.bias_source = "bos"
            return self.trend

        inferred = self.infer_bias_from_swings()
        if inferred in {"bullish", "bearish"}:
            if self.trend != inferred:
                self.bias_source = "structure"
                self.trend = inferred
            else:
                self.bias_source = "persisted" if self.trend != "ranging" else "none"
            return self.trend

        self.bias_source = "persisted" if self.trend != "ranging" else "none"
        return self.trend

    def detect_bos(self, df: pd.DataFrame, use_closed_candle: bool = True) -> Optional[StructureBreak]:
        """Detect BOS / CHoCH using confirmed swings and, by default, a closed candle."""
        if len(self.swings_high) < 2 or len(self.swings_low) < 2:
            return None

        last_high = self.swings_high[-1]
        prev_high = self.swings_high[-2]
        last_low = self.swings_low[-1]
        prev_low = self.swings_low[-2]

        if len(df) < 2:
            return None
        current_index = len(df) - 2 if use_closed_candle and len(df) >= 2 else len(df) - 1
        current = df.iloc[current_index]
        close = float(current["close"])

        if close > last_high.price:
            is_hh = last_high.price > prev_high.price
            hl_between = any(
                sl.price > prev_low.price and prev_high.index < sl.index < last_high.index
                for sl in self.swings_low
            )
            if is_hh and hl_between:
                self.trend = "bullish"
                self.last_bos = StructureBreak(
                    index=current_index,
                    price=close,
                    direction="bullish",
                    type="BOS",
                    prev_swing=last_high,
                )
                return self.last_bos

        if close < last_low.price:
            is_ll = last_low.price < prev_low.price
            lh_between = any(
                sh.price < prev_high.price and prev_low.index < sh.index < last_low.index
                for sh in self.swings_high
            )
            if is_ll and lh_between:
                self.trend = "bearish"
                self.last_bos = StructureBreak(
                    index=current_index,
                    price=close,
                    direction="bearish",
                    type="BOS",
                    prev_swing=last_low,
                )
                return self.last_bos

        if self.trend == "bearish" and close > last_high.price:
            self.trend = "bullish"
            self.last_bos = StructureBreak(
                index=current_index,
                price=close,
                direction="bullish",
                type="CHoCH",
                prev_swing=last_high,
            )
            return self.last_bos

        if self.trend == "bullish" and close < last_low.price:
            self.trend = "bearish"
            self.last_bos = StructureBreak(
                index=current_index,
                price=close,
                direction="bearish",
                type="CHoCH",
                prev_swing=last_low,
            )
            return self.last_bos

        return None

    def get_trading_range(self, df: pd.DataFrame) -> Optional[tuple[float, float]]:
        if not self.swings_high or not self.swings_low:
            return None

        recent_highs = [s for s in self.swings_high if s.index >= len(df) - 50]
        recent_lows = [s for s in self.swings_low if s.index >= len(df) - 50]
        if not recent_highs or not recent_lows:
            return None

        return max(s.price for s in recent_highs), min(s.price for s in recent_lows)

    def is_premium_zone(self, price: float, df: pd.DataFrame) -> bool:
        rng = self.get_trading_range(df)
        if not rng:
            return False
        high, low = rng
        return price > (high + low) / 2

    def is_discount_zone(self, price: float, df: pd.DataFrame) -> bool:
        rng = self.get_trading_range(df)
        if not rng:
            return False
        high, low = rng
        return price < (high + low) / 2

    def get_equal_highs(self, tolerance_pct: float = 0.002) -> List[tuple[Swing, Swing]]:
        equals = []
        for i in range(len(self.swings_high) - 1):
            for j in range(i + 1, len(self.swings_high)):
                s1, s2 = self.swings_high[i], self.swings_high[j]
                diff = abs(s1.price - s2.price) / s1.price
                if diff < tolerance_pct:
                    equals.append((s1, s2))
        return equals

    def get_equal_lows(self, tolerance_pct: float = 0.002) -> List[tuple[Swing, Swing]]:
        equals = []
        for i in range(len(self.swings_low) - 1):
            for j in range(i + 1, len(self.swings_low)):
                s1, s2 = self.swings_low[i], self.swings_low[j]
                diff = abs(s1.price - s2.price) / s1.price
                if diff < tolerance_pct:
                    equals.append((s1, s2))
        return equals

    def check_liquidity_sweep(self, df: pd.DataFrame, lookback: int = 10) -> Optional[str]:
        if len(df) < lookback:
            return None

        recent = df.iloc[-lookback:]
        recent_high = float(recent["high"].max())
        recent_low = float(recent["low"].min())

        for s1, s2 in self.get_equal_highs():
            if recent_high > max(s1.price, s2.price):
                return "bearish_sweep"

        for s1, s2 in self.get_equal_lows():
            if recent_low < min(s1.price, s2.price):
                return "bullish_sweep"

        if self.swings_high:
            last_sh = self.swings_high[-1]
            if last_sh.index < len(df) - lookback and recent_high > last_sh.price * 1.001:
                return "bearish_sweep"

        if self.swings_low:
            last_sl = self.swings_low[-1]
            if last_sl.index < len(df) - lookback and recent_low < last_sl.price * 0.999:
                return "bullish_sweep"

        return None

    def get_premium_discount_ratio(self, price: float, df: pd.DataFrame) -> float:
        rng = self.get_trading_range(df)
        if not rng:
            return 0.5
        high, low = rng
        if high == low:
            return 0.5
        ratio = (price - low) / (high - low)
        return max(0.0, min(1.0, ratio))

    def get_last_bos(self) -> Optional[StructureBreak]:
        return self.last_bos

    def get_trend(self) -> str:
        return self.trend

    def get_recent_liquidity_sweeps(self, df: pd.DataFrame, lookback: int = 10) -> list[str]:
        sweeps = []
        if len(df) < lookback:
            return sweeps

        for i in range(len(df) - lookback, len(df)):
            if i < 2:
                continue
            temp_highs = [s for s in self.swings_high if s.index < i]
            temp_lows = [s for s in self.swings_low if s.index < i]
            if not temp_highs or not temp_lows:
                continue

            candle = df.iloc[i]
            high = float(candle["high"])
            low = float(candle["low"])

            for j in range(len(temp_highs) - 1):
                for k in range(j + 1, len(temp_highs)):
                    s1, s2 = temp_highs[j], temp_highs[k]
                    if abs(s1.price - s2.price) / s1.price < 0.002 and high > max(s1.price, s2.price):
                        sweeps.append("bearish_sweep")
                        break

            for j in range(len(temp_lows) - 1):
                for k in range(j + 1, len(temp_lows)):
                    s1, s2 = temp_lows[j], temp_lows[k]
                    if abs(s1.price - s2.price) / s1.price < 0.002 and low < min(s1.price, s2.price):
                        sweeps.append("bullish_sweep")
                        break
        return sweeps

    def get_range_high(self, df: pd.DataFrame) -> float:
        if self.swings_high:
            return max(s.price for s in self.swings_high)
        return float(df["high"].max())

    def get_range_low(self, df: pd.DataFrame) -> float:
        if self.swings_low:
            return min(s.price for s in self.swings_low)
        return float(df["low"].min())

    def get_structure_breaks(self) -> List[dict]:
        breaks = []
        if hasattr(self, "bos_events"):
            for bos in self.bos_events:
                breaks.append(
                    {
                        "index": bos.get("index", -1),
                        "price": bos.get("price", 0),
                        "direction": "bullish" if bos.get("type") == "bullish_bos" else "bearish",
                    }
                )
        return breaks

    def get_recent_sweeps(self, lookback: int = 20) -> List[dict]:
        return []
