"""
Smart Money Concepts: Advanced Features
AMD Pattern, Fibonacci, Kill Zones, Range Detection, Momentum

Марко: "в момент открытия свечей цена делает некую аккумуляцию 
далее происходит манипуляция где снимается ликвидность 
далее происходит наценка актива"
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import List, Optional, Tuple
import pandas as pd
from datetime import datetime, timezone


@dataclass
class AMDPattern:
    """AMD (Accumulation-Manipulation-Distribution) pattern."""
    candle_open_idx: int
    accumulation_range: Tuple[float, float]  # (low, high)
    manipulation_price: float
    distribution_direction: str  # "bullish" | "bearish"
    confidence: float


@dataclass
class FibonacciLevels:
    """Fibonacci retracement levels."""
    range_high: float
    range_low: float
    fib_0618: float  # 61.8% retracement
    fib_0786: float  # 78.6% retracement
    fib_0500: float  # 50% (equilibrium)
    ote_zone_high: float  # Optimal Trade Entry 0.62-0.79
    ote_zone_low: float


@dataclass
class RangePattern:
    """Range/Sideways pattern."""
    start_idx: int
    end_idx: int
    range_high: float
    range_low: float
    deviations: List[dict]  # List of deviation events
    breakout_direction: Optional[str]


class AMDDetector:
    """
    Detect AMD patterns on candle opens.
    
    Марко: "в момент открытия свечей цена делает некую аккумуляцию 
    далее происходит манипуляция где снимается ликвидность 
    далее происходит наценка актива"
    """
    
    @staticmethod
    def detect_amd_on_candle(
        df: pd.DataFrame,
        candle_idx: int,
        timeframe: str = "D",  # D=daily, W=weekly, M=monthly
    ) -> Optional[AMDPattern]:
        """
        Detect AMD pattern on candle open.
        
        Pattern:
        1. Accumulation (sideways at open)
        2. Manipulation (liquidity sweep)
        3. Distribution (impulse move)
        """
        if candle_idx + 20 >= len(df):
            return None
        
        candle_open = float(df.iloc[candle_idx]["open"])
        
        # Look at next 20 sub-candles for AMD pattern
        sub_df = df.iloc[candle_idx:candle_idx + 20]
        
        # 1. Accumulation phase (first 5-10 candles near open)
        accum_df = sub_df.iloc[:10]
        accum_high = float(accum_df["high"].max())
        accum_low = float(accum_df["low"].min())
        accum_range = accum_high - accum_low
        
        # Check if accumulation (tight range)
        if accum_range / candle_open > 0.02:  # > 2% range = not accumulation
            return None
        
        # 2. Manipulation phase (sweep outside accumulation)
        manip_df = sub_df.iloc[10:15]
        manip_high = float(manip_df["high"].max())
        manip_low = float(manip_df["low"].min())
        
        swept_above = manip_high > accum_high * 1.005
        swept_below = manip_low < accum_low * 0.995
        
        if not (swept_above or swept_below):
            return None
        
        # 3. Distribution phase (impulse move opposite to manipulation)
        dist_df = sub_df.iloc[15:]
        dist_close = float(dist_df.iloc[-1]["close"])
        
        if swept_above and dist_close < candle_open:
            # Swept above, then moved down = bearish AMD
            return AMDPattern(
                candle_open_idx=candle_idx,
                accumulation_range=(accum_low, accum_high),
                manipulation_price=manip_high,
                distribution_direction="bearish",
                confidence=0.8,
            )
        
        elif swept_below and dist_close > candle_open:
            # Swept below, then moved up = bullish AMD
            return AMDPattern(
                candle_open_idx=candle_idx,
                accumulation_range=(accum_low, accum_high),
                manipulation_price=manip_low,
                distribution_direction="bullish",
                confidence=0.8,
            )
        
        return None


class FibonacciCalculator:
    """
    Calculate Fibonacci levels.
    
    Марко: "данная область 0618 079 является зоной 
    это оптимальная Зона для набора своих позиций"
    """
    
    @staticmethod
    def calculate_levels(
        range_high: float,
        range_low: float,
    ) -> FibonacciLevels:
        """Calculate Fibonacci retracement levels."""
        range_size = range_high - range_low
        
        fib_0618 = range_high - (range_size * 0.618)
        fib_0786 = range_high - (range_size * 0.786)
        fib_0500 = range_high - (range_size * 0.500)
        
        # OTE (Optimal Trade Entry) zone: 0.62-0.79
        ote_high = range_high - (range_size * 0.62)
        ote_low = range_high - (range_size * 0.79)
        
        return FibonacciLevels(
            range_high=range_high,
            range_low=range_low,
            fib_0618=fib_0618,
            fib_0786=fib_0786,
            fib_0500=fib_0500,
            ote_zone_high=ote_high,
            ote_zone_low=ote_low,
        )
    
    @staticmethod
    def is_in_ote_zone(price: float, fib: FibonacciLevels) -> bool:
        """Check if price is in OTE zone."""
        return fib.ote_zone_low <= price <= fib.ote_zone_high


class KillZoneDetector:
    """
    Detect Kill Zones (trading sessions).
    
    Марко: "Kill зона Это то время когда торгуют крупные игроки 
    Лондон с 9 до 12 до 18 и Токио Азия 3 до 8 утра"
    """
    
    # Kill zones in UTC+3 (Марко's timezone)
    LONDON_OPEN = 9
    LONDON_CLOSE = 18
    ASIA_OPEN = 3
    ASIA_CLOSE = 8
    NY_OPEN = 16
    NY_CLOSE = 23
    
    @staticmethod
    def get_current_kill_zone(timestamp: int) -> Optional[str]:
        """Get current kill zone."""
        dt = datetime.fromtimestamp(timestamp / 1000, tz=timezone.utc)
        hour = dt.hour + 3  # Convert to UTC+3
        hour = hour % 24
        
        if KillZoneDetector.LONDON_OPEN <= hour < KillZoneDetector.LONDON_CLOSE:
            return "London"
        elif KillZoneDetector.NY_OPEN <= hour < KillZoneDetector.NY_CLOSE:
            return "NewYork"
        elif KillZoneDetector.ASIA_OPEN <= hour < KillZoneDetector.ASIA_CLOSE:
            return "Asia"
        
        return None
    
    @staticmethod
    def is_in_kill_zone(timestamp: int) -> bool:
        """Check if timestamp is in any kill zone."""
        return KillZoneDetector.get_current_kill_zone(timestamp) is not None


class RangeDetector:
    """
    Detect Range/Sideways patterns.
    
    МАРКО: "раньше формируется по трем движениям 
    это формирование более высокого максимума hairha чаще всего после импульса 
    далее происходит коррекция цены и формируется Нижняя граница ренджа 
    далее должно сформироваться третье движение которое не будет выходить 
    за границы диапазона"
    
    3 movements required:
    1. First movement (high) - after impulse
    2. Second movement (low) - correction
    3. Third movement (failed to break) - SMS (unsuccessful swing)
    
    Deviation: "девиация цены в одну из сторон и далее мы уже видим выход 
    в противоположную сторону"
    """
    
    @staticmethod
    def detect_range(
        df: pd.DataFrame,
        start_idx: int,
        lookback: int = 30,
    ) -> Optional[RangePattern]:
        """
        Detect range pattern with 3 movements.
        
        МАРКО's 3 movements:
        1. First movement (high) - establishes upper boundary
        2. Second movement (low) - establishes lower boundary
        3. Third movement (failed to break) - confirms range
        """
        if start_idx + lookback >= len(df):
            return None
        
        range_df = df.iloc[start_idx:start_idx + lookback]
        
        # Find swing highs and lows (5-candle swings)
        highs = []
        lows = []
        
        for i in range(2, len(range_df) - 2):
            # Check if swing high (5-candle)
            if (range_df.iloc[i]["high"] > range_df.iloc[i-1]["high"] and
                range_df.iloc[i]["high"] > range_df.iloc[i-2]["high"] and
                range_df.iloc[i]["high"] > range_df.iloc[i+1]["high"] and
                range_df.iloc[i]["high"] > range_df.iloc[i+2]["high"]):
                highs.append({
                    "index": start_idx + i,
                    "price": float(range_df.iloc[i]["high"]),
                })
            
            # Check if swing low (5-candle)
            if (range_df.iloc[i]["low"] < range_df.iloc[i-1]["low"] and
                range_df.iloc[i]["low"] < range_df.iloc[i-2]["low"] and
                range_df.iloc[i]["low"] < range_df.iloc[i+1]["low"] and
                range_df.iloc[i]["low"] < range_df.iloc[i+2]["low"]):
                lows.append({
                    "index": start_idx + i,
                    "price": float(range_df.iloc[i]["low"]),
                })
        
        # МАРКО: Need at least 3 movements (2 highs + 1 low OR 2 lows + 1 high)
        if len(highs) < 2 or len(lows) < 1:
            return None
        
        # Movement 1: First high (upper boundary)
        first_high = highs[0]["price"]
        
        # Movement 2: First low (lower boundary)
        first_low = lows[0]["price"]
        
        # Movement 3: Second high (should NOT break first high)
        if len(highs) >= 2:
            second_high = highs[1]["price"]
            
            # МАРКО: Third movement failed to break = range confirmed
            # "третий фильм который не смог обновить структуру"
            if second_high < first_high * 1.005:  # Failed to break (0.5% tolerance)
                range_high = max(first_high, second_high)
                range_low = first_low
                
                return RangePattern(
                    start_idx=start_idx,
                    end_idx=start_idx + lookback,
                    range_high=range_high,
                    range_low=range_low,
                    deviations=[],
                    breakout_direction=None,
                )
        
        # Alternative: 2 lows + 1 high
        if len(lows) >= 2:
            second_low = lows[1]["price"]
            
            if second_low > first_low * 0.995:  # Failed to break (0.5% tolerance)
                range_high = first_high
                range_low = min(first_low, second_low)
                
                return RangePattern(
                    start_idx=start_idx,
                    end_idx=start_idx + lookback,
                    range_high=range_high,
                    range_low=range_low,
                    deviations=[],
                    breakout_direction=None,
                )
        
        return None
    
    @staticmethod
    def detect_deviation(
        df: pd.DataFrame,
        range_pattern: RangePattern,
        current_idx: int,
    ) -> Optional[dict]:
        """
        Detect deviation (sweep outside range).
        
        МАРКО: "девиация цены в одну из сторон и далее мы уже видим выход 
        в противоположную сторону данная манипуляция с более ликвидности 
        является девиации когда цена снимает ликвидности далее возвращается 
        в торговый диапазон"
        
        Optimal deviation: ~0.5 of trading range
        "оптимальная девиация не упомянул это на 05 торговый диапазона"
        """
        if current_idx >= len(df):
            return None
        
        current_high = float(df.iloc[current_idx]["high"])
        current_low = float(df.iloc[current_idx]["low"])
        current_close = float(df.iloc[current_idx]["close"])
        
        range_size = range_pattern.range_high - range_pattern.range_low
        range_mid = (range_pattern.range_high + range_pattern.range_low) / 2
        
        # Check for deviation above range
        if current_high > range_pattern.range_high:
            deviation_size = (current_high - range_pattern.range_high) / range_size
            
            # МАРКО: Check if returned to range
            returned_to_range = current_close < range_pattern.range_high
            
            # МАРКО: Optimal deviation ~0.5 of range
            is_optimal = 0.3 <= deviation_size <= 0.7
            
            return {
                "index": current_idx,
                "direction": "above",
                "price": current_high,
                "deviation_size": deviation_size,
                "returned_to_range": returned_to_range,
                "is_optimal": is_optimal,
            }
        
        # Check for deviation below range
        if current_low < range_pattern.range_low:
            deviation_size = (range_pattern.range_low - current_low) / range_size
            
            # МАРКО: Check if returned to range
            returned_to_range = current_close > range_pattern.range_low
            
            # МАРКО: Optimal deviation ~0.5 of range
            is_optimal = 0.3 <= deviation_size <= 0.7
            
            return {
                "index": current_idx,
                "direction": "below",
                "price": current_low,
                "deviation_size": deviation_size,
                "returned_to_range": returned_to_range,
                "is_optimal": is_optimal,
            }
        
        return None


class MomentumAnalyzer:
    """
    Analyze bullish/bearish momentum.
    
    Марко: "Это то время за которое цена проходит определенный отрезок 
    скапливается ликвидность и за счет данной ликвидности у нас рост 
    всегда по времени проходит быстрее чем коррекция"
    """
    
    @staticmethod
    def calculate_momentum(
        df: pd.DataFrame,
        start_idx: int,
        end_idx: int,
    ) -> dict:
        """
        Calculate momentum for price movement.
        
        Returns:
        - direction: "bullish" | "bearish"
        - speed: price change per candle
        - time: number of candles
        """
        if start_idx >= end_idx or end_idx >= len(df):
            return {"direction": "neutral", "speed": 0, "time": 0}
        
        start_price = float(df.iloc[start_idx]["close"])
        end_price = float(df.iloc[end_idx]["close"])
        time_candles = end_idx - start_idx
        
        price_change = end_price - start_price
        speed = abs(price_change) / time_candles if time_candles > 0 else 0
        
        direction = "bullish" if price_change > 0 else "bearish"
        
        return {
            "direction": direction,
            "speed": speed,
            "time": time_candles,
            "price_change_pct": (price_change / start_price) * 100,
        }
    
    @staticmethod
    def compare_impulse_vs_correction(
        impulse_momentum: dict,
        correction_momentum: dict,
    ) -> str:
        """
        Compare impulse vs correction momentum.
        
        Марко: "рост всегда по времени проходит быстрее чем коррекция"
        
        Returns: "bullish_momentum" | "bearish_momentum" | "neutral"
        """
        impulse_time = impulse_momentum.get("time", 0)
        correction_time = correction_momentum.get("time", 0)
        
        if impulse_time == 0 or correction_time == 0:
            return "neutral"
        
        # Impulse should be faster (less time) than correction
        if impulse_time < correction_time * 0.5:
            return f"{impulse_momentum['direction']}_momentum"
        
        return "neutral"
