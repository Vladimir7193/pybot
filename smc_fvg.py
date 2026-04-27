"""
Smart Money Concepts: Fair Value Gap (FVG/Imbalance) detection.
FVG = inefficient price area formed by 3 candles where middle candle creates a gap.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import List, Optional
import pandas as pd


@dataclass
class FairValueGap:
    """Fair Value Gap (imbalance) zone."""
    index:          int      # middle candle index
    high:           float    # top of FVG zone
    low:            float    # bottom of FVG zone
    direction:      str      # "bullish" | "bearish"
    fill_percentage: float   # 0.0 to 1.0 (how much filled)
    high_priority:  bool     # formed after liquidity sweep?
    timestamp:      int      # unix timestamp
    size_atr:       float    # FVG size in ATR units


class FVGDetector:
    """
    Detects Fair Value Gaps based on Марко's methodology.
    Bullish FVG: candle[i-1].high < candle[i+1].low
    Bearish FVG: candle[i-1].low > candle[i+1].high
    """
    
    def __init__(self, min_size_atr: float = 0.3, expiry_candles: int = 100):
        """
        min_size_atr: minimum FVG size in ATR units
        expiry_candles: how many candles before FVG expires
        """
        self.min_size_atr = min_size_atr
        self.expiry_candles = expiry_candles
        self.fvgs: List[FairValueGap] = []
    
    def detect_fvgs(
        self,
        df: pd.DataFrame,
        liquidity_sweep_indices: Optional[List[int]] = None,
    ) -> List[FairValueGap]:
        """
        Detect all Fair Value Gaps in the dataframe.
        liquidity_sweep_indices: list of candle indices where liquidity was swept.
        Returns list of FairValueGap objects.
        """
        fvgs = []
        
        if len(df) < 3:
            return fvgs
        
        # Need ATR for size filtering
        if "atr" not in df.columns or df["atr"].isna().all():
            return fvgs
        
        sweep_set = set(liquidity_sweep_indices or [])
        
        for i in range(1, len(df) - 1):
            prev = df.iloc[i - 1]
            curr = df.iloc[i]
            next_candle = df.iloc[i + 1]
            
            atr = float(curr["atr"])
            if atr == 0 or pd.isna(atr):
                continue
            
            # Bullish FVG: prev.high < next.low
            if float(prev["high"]) < float(next_candle["low"]):
                fvg_high = float(next_candle["low"])
                fvg_low = float(prev["high"])
                fvg_size = fvg_high - fvg_low
                
                # Check minimum size
                if fvg_size >= self.min_size_atr * atr:
                    # Check if formed after liquidity sweep
                    high_priority = (i - 1) in sweep_set or i in sweep_set
                    
                    fvgs.append(FairValueGap(
                        index=i,
                        high=fvg_high,
                        low=fvg_low,
                        direction="bullish",
                        fill_percentage=0.0,
                        high_priority=high_priority,
                        timestamp=int(curr["ts"]),
                        size_atr=fvg_size / atr,
                    ))
            
            # Bearish FVG: prev.low > next.high
            if float(prev["low"]) > float(next_candle["high"]):
                fvg_high = float(prev["low"])
                fvg_low = float(next_candle["high"])
                fvg_size = fvg_high - fvg_low
                
                # Check minimum size
                if fvg_size >= self.min_size_atr * atr:
                    # Check if formed after liquidity sweep
                    high_priority = (i - 1) in sweep_set or i in sweep_set
                    
                    fvgs.append(FairValueGap(
                        index=i,
                        high=fvg_high,
                        low=fvg_low,
                        direction="bearish",
                        fill_percentage=0.0,
                        high_priority=high_priority,
                        timestamp=int(curr["ts"]),
                        size_atr=fvg_size / atr,
                    ))
        
        self.fvgs = fvgs
        return fvgs
    
    def update_fill_status(self, df: pd.DataFrame) -> None:
        """
        Update fill percentage for all FVGs based on subsequent price action.
        """
        for fvg in self.fvgs:
            if fvg.index >= len(df) - 1:
                continue
            
            # Check candles after FVG formation
            max_fill = 0.0
            fvg_size = fvg.high - fvg.low
            
            for i in range(fvg.index + 1, len(df)):
                candle = df.iloc[i]
                high = float(candle["high"])
                low = float(candle["low"])
                
                if fvg.direction == "bullish":
                    # Check how much of FVG was filled from above
                    if high >= fvg.high:
                        # Fully entered FVG from above
                        if low <= fvg.low:
                            # Fully filled
                            max_fill = 1.0
                            break
                        else:
                            # Partially filled
                            filled = (fvg.high - low) / fvg_size
                            max_fill = max(max_fill, filled)
                
                elif fvg.direction == "bearish":
                    # Check how much of FVG was filled from below
                    if low <= fvg.low:
                        # Fully entered FVG from below
                        if high >= fvg.high:
                            # Fully filled
                            max_fill = 1.0
                            break
                        else:
                            # Partially filled
                            filled = (high - fvg.low) / fvg_size
                            max_fill = max(max_fill, filled)
            
            fvg.fill_percentage = max_fill
    
    def is_price_in_fvg(
        self,
        price: float,
        direction: str,
        current_idx: int,
    ) -> Optional[FairValueGap]:
        """
        Check if price is within an active FVG.
        Returns the FVG if found, None otherwise.
        """
        for fvg in self.fvgs:
            # Skip expired FVGs
            if current_idx - fvg.index > self.expiry_candles:
                continue
            
            # Skip wrong direction
            if fvg.direction != direction:
                continue
            
            # Skip fully filled FVGs
            if fvg.fill_percentage >= 1.0:
                continue
            
            # Check if price is in FVG zone
            if fvg.low <= price <= fvg.high:
                return fvg
        
        return None
    
    def cleanup_expired(self, current_idx: int) -> None:
        """Remove expired or fully filled FVGs."""
        self.fvgs = [
            fvg for fvg in self.fvgs
            if (current_idx - fvg.index <= self.expiry_candles and
                fvg.fill_percentage < 1.0)
        ]
    
    def get_active_fvgs(
        self,
        current_idx: int,
        direction: Optional[str] = None,
        high_priority_only: bool = False,
        max_fill: float = 0.5,
    ) -> List[FairValueGap]:
        """
        Get list of active (non-expired, not fully filled) FVGs.
        Can filter by direction, priority, and fill percentage.
        """
        fvgs = []
        for fvg in self.fvgs:
            # Skip expired
            if current_idx - fvg.index > self.expiry_candles:
                continue
            
            # Skip fully filled
            if fvg.fill_percentage >= max_fill:
                continue
            
            # Filter by direction
            if direction and fvg.direction != direction:
                continue
            
            # Filter by priority
            if high_priority_only and not fvg.high_priority:
                continue
            
            fvgs.append(fvg)
        
        return fvgs
