"""
Smart Money Concepts: Setup Pattern Detection
Implements Марко's setup patterns: TTS, TDP, Stop Hunt, Double Top/Bottom

Марко: "логика простая слон структуры новая зона интереса вход"
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import List, Optional
import pandas as pd


@dataclass
class SetupPattern:
    """Setup pattern detected in price action."""
    pattern_type: str  # "TTS", "TDP", "StopHunt", "DoubleTop", "DoubleBottom"
    index: int         # candle index where pattern completed
    direction: str     # "bullish" | "bearish"
    entry_zone_high: float
    entry_zone_low: float
    liquidity_swept: float  # price level that was swept
    structure_break: float  # price level where structure broke
    timestamp: int
    confidence: float  # 0.0-1.0 based on quality


class SetupPatternDetector:
    """
    Detects Марко's setup patterns for entry.
    
    Марко: "первый фактор это снятие ликвидности и тест зона интереса
    второй фактор это снятие минимум который снимал ликвидность
    третий фактор это импульсный слом структуры"
    """
    
    def __init__(self, lookback: int = 20):
        """
        lookback: how many candles to look back for pattern detection
        """
        self.lookback = lookback
        self.patterns: List[SetupPattern] = []
    
    def detect_tts_pattern(
        self,
        df: pd.DataFrame,
        liquidity_sweeps: List,
        zones_of_interest: List,
        structure_breaks: List,
    ) -> List[SetupPattern]:
        """
        Detect TTS (Test-Trap-Setup) pattern.
        
        Марко: "снятие ликвидности слом структуры образования новой зоны интереса"
        
        Pattern:
        1. Test zone of interest
        2. Trap (sweep liquidity)
        3. Setup (break structure + new zone)
        """
        patterns = []
        
        if len(df) < self.lookback:
            return patterns
        
        for i in range(self.lookback, len(df)):
            # FACTOR 1: Test zone of interest
            zone_tested = self._check_zone_test(df, i, zones_of_interest)
            if not zone_tested:
                continue
            
            # FACTOR 2: Liquidity sweep (trap)
            sweep = self._find_recent_sweep(i, liquidity_sweeps, lookback=5)
            if not sweep:
                continue
            
            # FACTOR 3: Structure break (setup)
            structure_break = self._find_recent_break(i, structure_breaks, lookback=3)
            if not structure_break:
                continue
            
            # Check if new zone formed after break
            new_zone = self._check_new_zone_formed(df, i)
            if not new_zone:
                continue
            
            # Valid TTS pattern found
            direction = structure_break.get("direction", "")
            candle = df.iloc[i]
            
            patterns.append(SetupPattern(
                pattern_type="TTS",
                index=i,
                direction=direction,
                entry_zone_high=new_zone["high"],
                entry_zone_low=new_zone["low"],
                liquidity_swept=sweep.get("price", 0),
                structure_break=structure_break.get("price", 0),
                timestamp=int(candle["ts"]),
                confidence=0.9,  # TTS is high confidence
            ))
        
        return patterns
    
    def detect_tdp_pattern(
        self,
        df: pd.DataFrame,
        liquidity_sweeps: List,
        structure_breaks: List,
    ) -> List[SetupPattern]:
        """
        Detect TDP (Trap-Displacement-Pullback) pattern.
        
        Марко: "повторное снятие ликвидности это у нас уже двойная вершина"
        
        Pattern:
        1. Trap (first sweep)
        2. Displacement (impulse move)
        3. Pullback (second sweep + reversal)
        """
        patterns = []
        
        if len(df) < self.lookback:
            return patterns
        
        for i in range(self.lookback, len(df)):
            # FACTOR 1: First sweep (trap)
            first_sweep = self._find_sweep_at_index(i - 10, i - 5, liquidity_sweeps)
            if not first_sweep:
                continue
            
            # FACTOR 2: Displacement (impulse)
            displacement = self._check_impulse_move(df, i - 5, i - 1)
            if not displacement:
                continue
            
            # FACTOR 3: Second sweep (pullback)
            second_sweep = self._find_recent_sweep(i, liquidity_sweeps, lookback=3)
            if not second_sweep:
                continue
            
            # Check if both sweeps are at similar level (double top/bottom)
            if not self._are_sweeps_similar(first_sweep, second_sweep):
                continue
            
            # Structure break after second sweep
            structure_break = self._find_recent_break(i, structure_breaks, lookback=2)
            if not structure_break:
                continue
            
            # Valid TDP pattern found
            direction = structure_break.get("direction", "")
            candle = df.iloc[i]
            new_zone = self._check_new_zone_formed(df, i)
            
            if new_zone:
                patterns.append(SetupPattern(
                    pattern_type="TDP",
                    index=i,
                    direction=direction,
                    entry_zone_high=new_zone["high"],
                    entry_zone_low=new_zone["low"],
                    liquidity_swept=second_sweep.get("price", 0),
                    structure_break=structure_break.get("price", 0),
                    timestamp=int(candle["ts"]),
                    confidence=0.85,  # TDP is high confidence
                ))
        
        return patterns
    
    def detect_stop_hunt_pattern(
        self,
        df: pd.DataFrame,
        liquidity_sweeps: List,
        structure_breaks: List,
    ) -> List[SetupPattern]:
        """
        Detect Stop Hunt pattern.
        
        Марко: "одиночное снятие ликвидности слом структуры и вход"
        
        Pattern:
        1. Single liquidity sweep
        2. Immediate structure break
        3. Entry from new zone
        """
        patterns = []
        
        if len(df) < self.lookback:
            return patterns
        
        for i in range(self.lookback, len(df)):
            # FACTOR 1: Single liquidity sweep
            sweep = self._find_recent_sweep(i, liquidity_sweeps, lookback=2)
            if not sweep:
                continue
            
            # FACTOR 2: Immediate structure break (within 1-2 candles)
            structure_break = self._find_recent_break(i, structure_breaks, lookback=2)
            if not structure_break:
                continue
            
            # Check if break is opposite to sweep direction (reversal)
            sweep_dir = sweep.get("direction", "")
            break_dir = structure_break.get("direction", "")
            
            if not self._is_reversal(sweep_dir, break_dir):
                continue
            
            # New zone formed
            new_zone = self._check_new_zone_formed(df, i)
            if not new_zone:
                continue
            
            # Valid Stop Hunt pattern found
            candle = df.iloc[i]
            
            patterns.append(SetupPattern(
                pattern_type="StopHunt",
                index=i,
                direction=break_dir,
                entry_zone_high=new_zone["high"],
                entry_zone_low=new_zone["low"],
                liquidity_swept=sweep.get("price", 0),
                structure_break=structure_break.get("price", 0),
                timestamp=int(candle["ts"]),
                confidence=0.8,  # Stop Hunt is good confidence
            ))
        
        return patterns
    
    def detect_double_top_bottom(
        self,
        df: pd.DataFrame,
        liquidity_sweeps: List,
        structure_breaks: List,
    ) -> List[SetupPattern]:
        """
        Detect Double Top/Bottom pattern.
        
        Марко: "повторное снятие это у нас двойная вершина/дно"
        
        Pattern:
        1. First sweep
        2. Reaction
        3. Second sweep (similar level)
        4. Structure break
        """
        patterns = []
        
        if len(df) < self.lookback:
            return patterns
        
        for i in range(self.lookback, len(df)):
            # Find two sweeps at similar levels
            sweeps = [s for s in liquidity_sweeps 
                     if i - 15 <= s.get("index", -1) <= i]
            
            if len(sweeps) < 2:
                continue
            
            # Check if last two sweeps are at similar level
            last_two = sorted(sweeps, key=lambda x: x.get("index", 0))[-2:]
            
            if not self._are_sweeps_similar(last_two[0], last_two[1]):
                continue
            
            # Structure break after second sweep
            structure_break = self._find_recent_break(i, structure_breaks, lookback=3)
            if not structure_break:
                continue
            
            # Determine pattern type
            sweep_dir = last_two[0].get("direction", "")
            break_dir = structure_break.get("direction", "")
            
            if sweep_dir == "bearish" and break_dir == "bullish":
                pattern_type = "DoubleBottom"
            elif sweep_dir == "bullish" and break_dir == "bearish":
                pattern_type = "DoubleTop"
            else:
                continue
            
            # New zone formed
            new_zone = self._check_new_zone_formed(df, i)
            if not new_zone:
                continue
            
            candle = df.iloc[i]
            
            patterns.append(SetupPattern(
                pattern_type=pattern_type,
                index=i,
                direction=break_dir,
                entry_zone_high=new_zone["high"],
                entry_zone_low=new_zone["low"],
                liquidity_swept=last_two[1].get("price", 0),
                structure_break=structure_break.get("price", 0),
                timestamp=int(candle["ts"]),
                confidence=0.85,
            ))
        
        return patterns
    
    # Helper methods
    
    def _check_zone_test(
        self, 
        df: pd.DataFrame, 
        idx: int, 
        zones: List,
    ) -> bool:
        """Check if price tested a zone of interest."""
        if not zones:
            return False
        
        price = float(df.iloc[idx]["close"])
        
        for zone in zones:
            if zone["low"] <= price <= zone["high"]:
                return True
        
        return False
    
    def _find_recent_sweep(
        self, 
        idx: int, 
        sweeps: List, 
        lookback: int = 5,
    ) -> Optional[dict]:
        """Find most recent liquidity sweep."""
        for sweep in reversed(sweeps):
            sweep_idx = sweep.get("index", -1)
            if idx - lookback <= sweep_idx <= idx:
                return sweep
        return None
    
    def _find_sweep_at_index(
        self,
        start_idx: int,
        end_idx: int,
        sweeps: List,
    ) -> Optional[dict]:
        """Find sweep in specific index range."""
        for sweep in sweeps:
            sweep_idx = sweep.get("index", -1)
            if start_idx <= sweep_idx <= end_idx:
                return sweep
        return None
    
    def _find_recent_break(
        self, 
        idx: int, 
        breaks: List, 
        lookback: int = 3,
    ) -> Optional[dict]:
        """Find most recent structure break."""
        for sb in reversed(breaks):
            sb_idx = sb.get("index", -1)
            if idx - lookback <= sb_idx <= idx:
                return sb
        return None
    
    def _check_impulse_move(
        self, 
        df: pd.DataFrame, 
        start_idx: int, 
        end_idx: int,
    ) -> bool:
        """Check if there was an impulse move in range."""
        if start_idx >= end_idx or end_idx >= len(df):
            return False
        
        start_price = float(df.iloc[start_idx]["close"])
        end_price = float(df.iloc[end_idx]["close"])
        
        move = abs(end_price - start_price) / start_price
        
        # Impulse = move > 2% in short time
        return move > 0.02
    
    def _check_new_zone_formed(
        self, 
        df: pd.DataFrame, 
        idx: int,
    ) -> Optional[dict]:
        """Check if new zone of interest formed."""
        if idx < 1 or idx >= len(df):
            return None
        
        # Last candle that created the zone
        candle = df.iloc[idx - 1]
        
        return {
            "high": float(candle["high"]),
            "low": float(candle["low"]),
            "index": idx - 1,
        }
    
    def _are_sweeps_similar(
        self, 
        sweep1: dict, 
        sweep2: dict, 
        tolerance: float = 0.005,
    ) -> bool:
        """Check if two sweeps are at similar price level."""
        price1 = sweep1.get("price", 0)
        price2 = sweep2.get("price", 0)
        
        if price1 == 0 or price2 == 0:
            return False
        
        diff = abs(price1 - price2) / price1
        return diff < tolerance
    
    def _is_reversal(self, sweep_dir: str, break_dir: str) -> bool:
        """Check if structure break is reversal of sweep."""
        if sweep_dir == "bullish" and break_dir == "bearish":
            return True
        if sweep_dir == "bearish" and break_dir == "bullish":
            return True
        return False
    
    def detect_all_patterns(
        self,
        df: pd.DataFrame,
        liquidity_sweeps: List,
        zones_of_interest: List,
        structure_breaks: List,
    ) -> List[SetupPattern]:
        """Detect all setup patterns."""
        all_patterns = []
        
        # TTS patterns
        tts = self.detect_tts_pattern(
            df, liquidity_sweeps, zones_of_interest, structure_breaks
        )
        all_patterns.extend(tts)
        
        # TDP patterns
        tdp = self.detect_tdp_pattern(
            df, liquidity_sweeps, structure_breaks
        )
        all_patterns.extend(tdp)
        
        # Stop Hunt patterns
        stop_hunt = self.detect_stop_hunt_pattern(
            df, liquidity_sweeps, structure_breaks
        )
        all_patterns.extend(stop_hunt)
        
        # Double Top/Bottom patterns
        double = self.detect_double_top_bottom(
            df, liquidity_sweeps, structure_breaks
        )
        all_patterns.extend(double)
        
        # Sort by index
        all_patterns.sort(key=lambda p: p.index)
        
        self.patterns = all_patterns
        return all_patterns
    
    def get_latest_pattern(
        self, 
        current_idx: int, 
        lookback: int = 5,
    ) -> Optional[SetupPattern]:
        """Get most recent pattern near current index."""
        for pattern in reversed(self.patterns):
            if current_idx - lookback <= pattern.index <= current_idx:
                return pattern
        return None
