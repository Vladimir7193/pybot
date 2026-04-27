"""
Smart Money Concepts: Order Flow Detection
Tracks internal vs external liquidity and order flow patterns

Марко: "постоянно работа с внутренней и внешней ликвидностью и это и есть Орды Flow"
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import List, Optional
import pandas as pd


@dataclass
class LiquidityPool:
    """Liquidity pool (internal or external)."""
    index: int
    price: float
    pool_type: str  # "internal" | "external"
    direction: str  # "buy" | "sell"
    swept: bool
    timestamp: int


@dataclass
class OrderFlowPhase:
    """Order flow phase in the sequence."""
    phase_type: str  # "accumulation" | "sweep" | "displacement" | "retest"
    start_idx: int
    end_idx: int
    direction: str  # "bullish" | "bearish"


class OrderFlowDetector:
    """
    Detects Order Flow patterns.
    
    Марко: "снимается внешняя ликвидность далее формирование ликвидности 
    съем обновление структуры формирование ликвидности съем обновление структуры"
    
    Order Flow sequence:
    1. External liquidity sweep
    2. Internal liquidity formation
    3. Internal liquidity sweep
    4. Structure update
    5. Repeat
    """
    
    def __init__(self, trading_range_lookback: int = 50):
        """
        trading_range_lookback: candles to look back for range definition
        """
        self.trading_range_lookback = trading_range_lookback
        self.internal_liquidity: List[LiquidityPool] = []
        self.external_liquidity: List[LiquidityPool] = []
        self.order_flow_phases: List[OrderFlowPhase] = []
    
    def detect_liquidity_pools(
        self,
        df: pd.DataFrame,
        swings_high: List,
        swings_low: List,
        trading_range_high: float,
        trading_range_low: float,
    ) -> tuple[List[LiquidityPool], List[LiquidityPool]]:
        """
        Detect internal and external liquidity pools.
        
        Марко: "все что у нас находится за границами торгового диапазона 
        это внешняя ликвидность все сосредоточение ликвидности внутри 
        торговых диапазона это и есть внутренняя ликвидность"
        """
        internal = []
        external = []
        
        # Process swing highs (sell liquidity above)
        for swing in swings_high:
            swing_price = swing.price
            swing_idx = swing.index
            
            if swing_idx >= len(df):
                continue
            
            candle = df.iloc[swing_idx]
            
            # Determine if internal or external
            if trading_range_low <= swing_price <= trading_range_high:
                pool_type = "internal"
                internal.append(LiquidityPool(
                    index=swing_idx,
                    price=swing_price,
                    pool_type=pool_type,
                    direction="sell",  # liquidity above = sell stops
                    swept=False,
                    timestamp=int(candle["ts"]),
                ))
            else:
                pool_type = "external"
                external.append(LiquidityPool(
                    index=swing_idx,
                    price=swing_price,
                    pool_type=pool_type,
                    direction="sell",
                    swept=False,
                    timestamp=int(candle["ts"]),
                ))
        
        # Process swing lows (buy liquidity below)
        for swing in swings_low:
            swing_price = swing.price
            swing_idx = swing.index
            
            if swing_idx >= len(df):
                continue
            
            candle = df.iloc[swing_idx]
            
            # Determine if internal or external
            if trading_range_low <= swing_price <= trading_range_high:
                pool_type = "internal"
                internal.append(LiquidityPool(
                    index=swing_idx,
                    price=swing_price,
                    pool_type=pool_type,
                    direction="buy",  # liquidity below = buy stops
                    swept=False,
                    timestamp=int(candle["ts"]),
                ))
            else:
                pool_type = "external"
                external.append(LiquidityPool(
                    index=swing_idx,
                    price=swing_price,
                    pool_type=pool_type,
                    direction="buy",
                    swept=False,
                    timestamp=int(candle["ts"]),
                ))
        
        self.internal_liquidity = internal
        self.external_liquidity = external
        
        return internal, external
    
    def track_liquidity_sweeps(
        self,
        df: pd.DataFrame,
        current_idx: int,
    ) -> List[dict]:
        """
        Track which liquidity pools have been swept.
        Returns list of sweep events.
        """
        sweeps = []
        
        if current_idx >= len(df):
            return sweeps
        
        current_price = float(df.iloc[current_idx]["close"])
        current_high = float(df.iloc[current_idx]["high"])
        current_low = float(df.iloc[current_idx]["low"])
        
        # Check internal liquidity sweeps
        for pool in self.internal_liquidity:
            if pool.swept:
                continue
            
            # Check if swept
            if pool.direction == "sell" and current_high >= pool.price:
                pool.swept = True
                sweeps.append({
                    "index": current_idx,
                    "price": pool.price,
                    "pool_type": "internal",
                    "direction": "bullish",  # swept upward
                })
            elif pool.direction == "buy" and current_low <= pool.price:
                pool.swept = True
                sweeps.append({
                    "index": current_idx,
                    "price": pool.price,
                    "pool_type": "internal",
                    "direction": "bearish",  # swept downward
                })
        
        # Check external liquidity sweeps
        for pool in self.external_liquidity:
            if pool.swept:
                continue
            
            # Check if swept
            if pool.direction == "sell" and current_high >= pool.price:
                pool.swept = True
                sweeps.append({
                    "index": current_idx,
                    "price": pool.price,
                    "pool_type": "external",
                    "direction": "bullish",
                })
            elif pool.direction == "buy" and current_low <= pool.price:
                pool.swept = True
                sweeps.append({
                    "index": current_idx,
                    "price": pool.price,
                    "pool_type": "external",
                    "direction": "bearish",
                })
        
        return sweeps
    
    def detect_order_flow_sequence(
        self,
        df: pd.DataFrame,
        structure_breaks: List,
    ) -> List[OrderFlowPhase]:
        """
        Detect order flow sequence.
        
        Марко: "снимается внешняя ликвидность далее формирование ликвидности 
        съем обновление структуры"
        
        Sequence:
        1. External liquidity sweep
        2. Internal liquidity formation
        3. Internal liquidity sweep
        4. Structure break
        """
        phases = []
        
        if len(df) < 20:
            return phases
        
        # Find external sweeps
        external_sweeps = [p for p in self.external_liquidity if p.swept]
        
        for ext_sweep in external_sweeps:
            sweep_idx = ext_sweep.index
            
            # Look for internal liquidity formation after external sweep
            internal_formed = self._find_internal_formation_after(
                sweep_idx, lookback=10
            )
            
            if not internal_formed:
                continue
            
            # Look for internal liquidity sweep
            internal_swept = self._find_internal_sweep_after(
                internal_formed["index"], lookback=10
            )
            
            if not internal_swept:
                continue
            
            # Look for structure break
            structure_break = self._find_structure_break_after(
                internal_swept["index"], structure_breaks, lookback=5
            )
            
            if not structure_break:
                continue
            
            # Valid order flow sequence found
            direction = structure_break.get("direction", "")
            
            phases.append(OrderFlowPhase(
                phase_type="complete_sequence",
                start_idx=sweep_idx,
                end_idx=structure_break.get("index", sweep_idx),
                direction=direction,
            ))
        
        self.order_flow_phases = phases
        return phases
    
    def is_valid_order_flow(
        self,
        current_idx: int,
        direction: str,
    ) -> bool:
        """
        Check if current position has valid order flow.
        
        Марко: "работа с внутренней и внешней ликвидностью"
        """
        # Look for recent order flow sequence
        for phase in reversed(self.order_flow_phases):
            if (current_idx - 20 <= phase.end_idx <= current_idx and
                phase.direction == direction):
                return True
        
        return False
    
    def get_next_liquidity_target(
        self,
        current_price: float,
        direction: str,
    ) -> Optional[float]:
        """
        Get next liquidity target in the direction.
        
        Марко: "цена всегда стремится либо снять ликвидность"
        """
        if direction == "bullish":
            # Find nearest unswept liquidity above
            targets = [
                p.price for p in self.internal_liquidity + self.external_liquidity
                if not p.swept and p.direction == "sell" and p.price > current_price
            ]
            return min(targets) if targets else None
        
        elif direction == "bearish":
            # Find nearest unswept liquidity below
            targets = [
                p.price for p in self.internal_liquidity + self.external_liquidity
                if not p.swept and p.direction == "buy" and p.price < current_price
            ]
            return max(targets) if targets else None
        
        return None
    
    # Helper methods
    
    def _find_internal_formation_after(
        self,
        after_idx: int,
        lookback: int = 10,
    ) -> Optional[dict]:
        """Find internal liquidity formation after index."""
        for pool in self.internal_liquidity:
            if after_idx < pool.index <= after_idx + lookback:
                return {
                    "index": pool.index,
                    "price": pool.price,
                }
        return None
    
    def _find_internal_sweep_after(
        self,
        after_idx: int,
        lookback: int = 10,
    ) -> Optional[dict]:
        """Find internal liquidity sweep after index."""
        for pool in self.internal_liquidity:
            if pool.swept and after_idx < pool.index <= after_idx + lookback:
                return {
                    "index": pool.index,
                    "price": pool.price,
                }
        return None
    
    def _find_structure_break_after(
        self,
        after_idx: int,
        structure_breaks: List,
        lookback: int = 5,
    ) -> Optional[dict]:
        """Find structure break after index."""
        for sb in structure_breaks:
            sb_idx = sb.get("index", -1)
            if after_idx < sb_idx <= after_idx + lookback:
                return sb
        return None
