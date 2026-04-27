"""
Smart Money Concepts: Order Block detection.
Order Block = last bearish candle before bullish impulse (or vice versa).
Breaker Block = Order Block that was broken impulsively (changes polarity).
Mitigation Block = Failed swing that didn't break structure (SMS).
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import List, Optional
import pandas as pd


@dataclass
class OrderBlock:
    """Order Block zone where smart money accumulated positions."""
    index:     int      # candle index in dataframe
    high:      float    # top of order block zone
    low:       float    # bottom of order block zone
    direction: str      # "bullish" | "bearish"
    tested:    bool     # has price revisited this zone?
    timestamp: int      # unix timestamp
    strength:  float    # impulse strength (size of move after OB)


@dataclass
class BreakerBlock:
    """
    Breaker Block = Order Block that was broken impulsively.
    Changes polarity: bullish OB becomes bearish breaker, and vice versa.
    """
    original_ob: OrderBlock
    break_index: int
    break_price: float
    new_direction: str  # opposite of original OB direction
    timestamp: int


@dataclass
class MitigationBlock:
    """
    Mitigation Block = Failed swing that didn't break structure (SMS).
    Forms when price fails to take out previous high/low.
    """
    index: int
    high: float
    low: float
    direction: str      # "bullish" | "bearish"
    failed_to_break: float  # price level it failed to break
    timestamp: int
    strength: float


class OrderBlockDetector:
    """
    Detects Order Blocks, Breaker Blocks, and Mitigation Blocks.
    Based on Марко's methodology.
    
    Order Block: last bearish candle before bullish impulse (or vice versa)
    Breaker Block: OB that was broken impulsively (changes polarity)
    Mitigation Block: failed swing that didn't break structure (SMS)
    """
    
    def __init__(self, impulse_threshold: float = 2.0, expiry_candles: int = 100):
        """
        impulse_threshold: minimum ATR multiplier to consider as impulse
        expiry_candles: how many candles before OB expires
        """
        self.impulse_threshold = impulse_threshold
        self.expiry_candles = expiry_candles
        self.order_blocks: List[OrderBlock] = []
        self.breaker_blocks: List[BreakerBlock] = []
        self.mitigation_blocks: List[MitigationBlock] = []
    
    def detect_order_blocks(
        self, 
        df: pd.DataFrame,
        liquidity_sweeps: List = None,
        zones_of_interest: List = None,
        structure_breaks: List = None,
    ) -> List[OrderBlock]:
        """
        Detect all order blocks in the dataframe.
        
        Марко's 3 factors for valid Order Block:
        1. Liquidity sweep BEFORE the OB formation
        2. Formation FROM zone of interest (imbalance or higher TF OB)
        3. Structure element update (BOS or swing update)
        
        Returns list of OrderBlock objects.
        """
        obs = []
        
        if len(df) < 10:
            return obs
        
        # Need ATR for impulse detection
        if "atr" not in df.columns or df["atr"].isna().all():
            return obs
        
        liquidity_sweeps = liquidity_sweeps or []
        zones_of_interest = zones_of_interest or []
        structure_breaks = structure_breaks or []
        
        scan_start = max(5, len(df) - 30)
        for i in range(scan_start, len(df) - 3):
            atr = float(df.iloc[i]["atr"])
            if atr == 0 or pd.isna(atr):
                continue
            
            # Check for bullish impulse (3+ candles moving up)
            bullish_impulse = self._detect_bullish_impulse(df, i, atr)
            if bullish_impulse:
                # Find last bearish candle before impulse
                ob_idx = self._find_last_bearish_candle(df, i)
                if ob_idx is not None:
                    # МАРКО FACTOR 1: Check liquidity sweep BEFORE OB
                    sweep_before = self._check_liquidity_sweep_before(
                        ob_idx, liquidity_sweeps, direction="bullish"
                    )
                    
                    # МАРКО FACTOR 2: Check formation from zone of interest
                    from_zone = self._check_formation_from_zone(
                        df, ob_idx, zones_of_interest
                    )
                    
                    # МАРКО FACTOR 3: Check structure update
                    structure_update = self._check_structure_update(
                        ob_idx, structure_breaks, direction="bullish"
                    )
                    
                    # МАРКО: ALL 3 FACTORS REQUIRED for valid OB
                    # "вроде блока в первую очередь отображает следы умных денег"
                    if not (sweep_before and from_zone and structure_update):
                        continue  # Skip invalid OB
                    
                    # Calculate validity score (all 3 required)
                    validity_score = 3.0
                    
                    candle = df.iloc[ob_idx]
                    
                    # МАРКО: Check if FVG exists (non-standard OB by wick)
                    # "при бычьих Орде блоках это всегда тень зеленой свечи"
                    has_fvg = self._check_fvg_in_candle(df, ob_idx, zones_of_interest)
                    
                    if has_fvg:
                        # Non-standard OB: use wick (low to close for bullish)
                        ob_high = float(candle["close"])
                        ob_low = float(candle["low"])
                    else:
                        # Standard OB: use body only
                        ob_high = float(candle["high"])
                        ob_low = float(candle["low"])
                    
                    obs.append(OrderBlock(
                        index=ob_idx,
                        high=ob_high,
                        low=ob_low,
                        direction="bullish",
                        tested=False,
                        timestamp=int(candle["ts"]),
                        strength=bullish_impulse * (1 + validity_score * 0.3),  # Boost strength
                    ))
            
            # Check for bearish impulse (3+ candles moving down)
            bearish_impulse = self._detect_bearish_impulse(df, i, atr)
            if bearish_impulse:
                # Find last bullish candle before impulse
                ob_idx = self._find_last_bullish_candle(df, i)
                if ob_idx is not None:
                    # МАРКО FACTOR 1: Check liquidity sweep BEFORE OB
                    sweep_before = self._check_liquidity_sweep_before(
                        ob_idx, liquidity_sweeps, direction="bearish"
                    )
                    
                    # МАРКО FACTOR 2: Check formation from zone of interest
                    from_zone = self._check_formation_from_zone(
                        df, ob_idx, zones_of_interest
                    )
                    
                    # МАРКО FACTOR 3: Check structure update
                    structure_update = self._check_structure_update(
                        ob_idx, structure_breaks, direction="bearish"
                    )
                    
                    # МАРКО: ALL 3 FACTORS REQUIRED for valid OB
                    if not (sweep_before and from_zone and structure_update):
                        continue  # Skip invalid OB
                    
                    # Calculate validity score (all 3 required)
                    validity_score = 3.0
                    
                    candle = df.iloc[ob_idx]
                    
                    # МАРКО: Check if FVG exists (non-standard OB by wick)
                    # "при медвежьих Вроде блоках это тень А черные свечи"
                    has_fvg = self._check_fvg_in_candle(df, ob_idx, zones_of_interest)
                    
                    if has_fvg:
                        # Non-standard OB: use wick (close to high for bearish)
                        ob_high = float(candle["high"])
                        ob_low = float(candle["close"])
                    else:
                        # Standard OB: use body only
                        ob_high = float(candle["high"])
                        ob_low = float(candle["low"])
                    
                    obs.append(OrderBlock(
                        index=ob_idx,
                        high=ob_high,
                        low=ob_low,
                        direction="bearish",
                        tested=False,
                        timestamp=int(candle["ts"]),
                        strength=bearish_impulse * (1 + validity_score * 0.3),  # Boost strength
                    ))
        
        new_indices = {ob.index for ob in obs}
        kept = [ob for ob in self.order_blocks if ob.index not in new_indices]
        self.order_blocks = kept + obs
        return obs
    
    def _check_liquidity_sweep_before(
        self, 
        ob_idx: int, 
        liquidity_sweeps: List,
        direction: str,
    ) -> bool:
        """
        МАРКО FACTOR 1: Check if liquidity was swept BEFORE OB formation.
        """
        if not liquidity_sweeps:
            return False
        
        # Look for sweeps within 10 candles before OB
        for sweep in liquidity_sweeps:
            sweep_idx = sweep.get("index", -1)
            sweep_dir = sweep.get("direction", "")
            
            # Sweep should be before OB and in correct direction
            if (ob_idx - 10 <= sweep_idx < ob_idx and 
                sweep_dir == direction):
                return True
        
        return False
    
    def _check_formation_from_zone(
        self,
        df: pd.DataFrame,
        ob_idx: int,
        zones_of_interest: List,
    ) -> bool:
        """
        МАРКО FACTOR 2: Check if OB formed FROM zone of interest.
        Zone of interest = imbalance, higher TF OB, breaker, mitigation.
        """
        if not zones_of_interest:
            return False
        
        ob_price = float(df.iloc[ob_idx]["close"])
        
        # Check if OB price is within any zone of interest
        for zone in zones_of_interest:
            zone_high = zone.get("high", 0)
            zone_low = zone.get("low", 0)
            
            if zone_low <= ob_price <= zone_high:
                return True
        
        return False
    
    def _check_structure_update(
        self,
        ob_idx: int,
        structure_breaks: List,
        direction: str,
    ) -> bool:
        """
        МАРКО FACTOR 3: Check if structure was updated (BOS or swing update).
        """
        if not structure_breaks:
            return False
        
        # Look for structure breaks within 5 candles after OB
        for sb in structure_breaks:
            sb_idx = sb.get("index", -1)
            sb_dir = sb.get("direction", "")
            
            # Structure break should be after OB and in correct direction
            if (ob_idx < sb_idx <= ob_idx + 5 and 
                sb_dir == direction):
                return True
        
        return False
    
    def _check_fvg_in_candle(
        self,
        df: pd.DataFrame,
        candle_idx: int,
        zones_of_interest: List,
    ) -> bool:
        """
        МАРКО: Check if FVG (imbalance) exists inside candle.
        
        "в случае же если у нас был образован имбаланс на поглощающей свече 
        данная зона выделялась бы по фитилю свечи"
        
        Returns True if FVG exists, False otherwise.
        """
        if candle_idx < 1 or candle_idx >= len(df) - 1:
            return False
        
        prev = df.iloc[candle_idx - 1]
        curr = df.iloc[candle_idx]
        next_candle = df.iloc[candle_idx + 1]
        
        # Check for bullish FVG: prev.high < next.low
        if float(prev["high"]) < float(next_candle["low"]):
            return True
        
        # Check for bearish FVG: prev.low > next.high
        if float(prev["low"]) > float(next_candle["high"]):
            return True
        
        # Also check zones_of_interest for existing FVGs
        curr_price = float(curr["close"])
        for zone in zones_of_interest:
            zone_type = zone.get("type", "")
            if zone_type == "fvg":
                zone_high = zone.get("high", 0)
                zone_low = zone.get("low", 0)
                if zone_low <= curr_price <= zone_high:
                    return True
        
        return False
    
    def _detect_bullish_impulse(self, df: pd.DataFrame, start_idx: int, atr: float) -> Optional[float]:
        """
        Detect bullish impulse starting at start_idx.

        МАРКО: "данная свеча снимает ликвидность, далее мы видим полное поглощение"

        Логика:
        - c1 = df[start_idx]   — свеча, которую поглощают
        - c2 = df[start_idx+1] — промежуточная
        - c3 = df[start_idx+2] — поглощающая свеча (должна покрыть весь диапазон c1)
        - Размер хода = c3.high - c1.low (в рамках тех же трёх свечей)
        """
        if start_idx + 2 >= len(df):
            return None

        c1 = df.iloc[start_idx]
        c3 = df.iloc[start_idx + 2]

        c1_low  = float(c1["low"])
        c1_high = float(c1["high"])
        c3_low  = float(c3["low"])
        c3_high = float(c3["high"])
        c3_close = float(c3["close"])

        # Bullish engulfment: c3 wick reaches below c1 AND c3 closes above c1
        if not (c3_low <= c1_low and c3_close > c1_high):
            return None

        # Размер хода считаем по тем же трём свечам (c1.low → c3.high)
        move = c3_high - c1_low
        if move > self.impulse_threshold * atr:
            return move / atr
        return None
    
    def _detect_bearish_impulse(self, df: pd.DataFrame, start_idx: int, atr: float) -> Optional[float]:
        """
        Detect bearish impulse starting at start_idx.

        МАРКО: "данная свеча снимает ликвидность, далее мы видим полное поглощение"

        Логика:
        - c1 = df[start_idx]   — свеча, которую поглощают
        - c3 = df[start_idx+2] — поглощающая свеча (должна покрыть весь диапазон c1)
        - Размер хода = c1.high - c3.low (в рамках тех же трёх свечей)
        """
        if start_idx + 2 >= len(df):
            return None

        c1 = df.iloc[start_idx]
        c3 = df.iloc[start_idx + 2]

        c1_low  = float(c1["low"])
        c1_high = float(c1["high"])
        c3_low  = float(c3["low"])
        c3_high = float(c3["high"])
        c3_close = float(c3["close"])

        # Bearish engulfment: c3 wick reaches above c1 AND c3 closes below c1
        if not (c3_high >= c1_high and c3_close < c1_low):
            return None

        # Размер хода считаем по тем же трём свечам (c1.high → c3.low)
        move = c1_high - c3_low
        if move > self.impulse_threshold * atr:
            return move / atr
        return None
    
    def _find_last_bearish_candle(self, df: pd.DataFrame, before_idx: int) -> Optional[int]:
        """Find last bearish candle before the given index."""
        for i in range(before_idx - 1, max(0, before_idx - 5), -1):
            candle = df.iloc[i]
            if float(candle["close"]) < float(candle["open"]):
                return i
        return None
    
    def _find_last_bullish_candle(self, df: pd.DataFrame, before_idx: int) -> Optional[int]:
        """Find last bullish candle before the given index."""
        for i in range(before_idx - 1, max(0, before_idx - 5), -1):
            candle = df.iloc[i]
            if float(candle["close"]) > float(candle["open"]):
                return i
        return None
    
    def is_price_in_order_block(
        self,
        price: float,
        direction: str,
        current_idx: int,
    ) -> Optional[OrderBlock]:
        """
        Check if price is within an active order block.
        Returns the OrderBlock if found, None otherwise.
        """
        for ob in self.order_blocks:
            # Skip expired OBs
            if current_idx - ob.index > self.expiry_candles:
                continue
            
            # Skip wrong direction
            if ob.direction != direction:
                continue
            
            # Check if price is in OB zone
            if ob.low <= price <= ob.high:
                return ob
        
        return None
    
    def mark_tested(self, ob: OrderBlock) -> None:
        """Mark an order block as tested when price revisits it."""
        ob.tested = True
    
    def cleanup_expired(self, current_idx: int) -> None:
        """Remove expired order blocks."""
        self.order_blocks = [
            ob for ob in self.order_blocks
            if current_idx - ob.index <= self.expiry_candles
        ]
    
    def get_active_order_blocks(
        self,
        current_idx: int,
        direction: Optional[str] = None,
        untested_only: bool = False,
    ) -> List[OrderBlock]:
        """
        Get list of active (non-expired) order blocks.
        Can filter by direction and tested status.
        """
        obs = []
        for ob in self.order_blocks:
            # Skip expired
            if current_idx - ob.index > self.expiry_candles:
                continue
            
            # Filter by direction
            if direction and ob.direction != direction:
                continue
            
            # Filter by tested status
            if untested_only and ob.tested:
                continue
            
            obs.append(ob)
        
        return obs

    
    def detect_breaker_blocks(self, df: pd.DataFrame) -> List[BreakerBlock]:
        """
        Detect Breaker Blocks - Order Blocks that were broken impulsively.
        
        Марко: "брейкер блок формируется когда ордер блок пробивается импульсно"
        
        Logic:
        1. Find Order Blocks that were broken
        2. Check if break was impulsive (> threshold * ATR)
        3. Breaker changes polarity (bullish OB → bearish breaker)
        """
        breakers = []
        
        if "atr" not in df.columns or df["atr"].isna().all():
            return breakers
        
        for ob in self.order_blocks:
            # Check if OB was broken
            for i in range(ob.index + 1, len(df)):
                candle = df.iloc[i]
                atr = float(candle["atr"])
                
                if atr == 0 or pd.isna(atr):
                    continue
                
                # Check for impulsive break
                if ob.direction == "bullish":
                    # Bullish OB broken downward → becomes bearish breaker
                    if float(candle["close"]) < ob.low:
                        # Check if break was impulsive
                        move = ob.low - float(candle["low"])
                        if move > self.impulse_threshold * atr:
                            breakers.append(BreakerBlock(
                                original_ob=ob,
                                break_index=i,
                                break_price=float(candle["close"]),
                                new_direction="bearish",
                                timestamp=int(candle["ts"]),
                            ))
                            break
                
                elif ob.direction == "bearish":
                    # Bearish OB broken upward → becomes bullish breaker
                    if float(candle["close"]) > ob.high:
                        # Check if break was impulsive
                        move = float(candle["high"]) - ob.high
                        if move > self.impulse_threshold * atr:
                            breakers.append(BreakerBlock(
                                original_ob=ob,
                                break_index=i,
                                break_price=float(candle["close"]),
                                new_direction="bullish",
                                timestamp=int(candle["ts"]),
                            ))
                            break
        
        self.breaker_blocks = breakers
        return breakers
    
    def detect_mitigation_blocks(self, df: pd.DataFrame, swings_high: List, swings_low: List) -> List[MitigationBlock]:
        """
        Detect Mitigation Blocks — failed swings that didn't break structure (SMS).

        МАРКО: "митигейшен блок — когда ликвидность последнего High НЕ снималась.
        Отличие от брейкера: ликвидность последнего High не снималась."

        Условие: свинг не смог обновить предыдущий экстремум И
                 ликвидность предыдущего экстремума НЕ была снята
                 (т.е. цена не уходила за prev_swing.price до текущего свинга).
        """
        mitigations = []

        if "atr" not in df.columns or df["atr"].isna().all():
            return mitigations

        # ── Swing highs: failed to break prev high (bearish mitigation) ──
        for i in range(1, len(swings_high)):
            current_swing = swings_high[i]
            prev_swing    = swings_high[i - 1]

            if current_swing.price >= prev_swing.price:
                continue  # Обновил — не митигейшен

            # Проверяем: ликвидность prev_swing НЕ снималась между ними
            liq_swept = any(
                float(df.iloc[j]["high"]) > prev_swing.price
                for j in range(prev_swing.index + 1, current_swing.index)
                if j < len(df)
            )
            if liq_swept:
                continue  # Ликвидность снималась → это брейкер, не митигейшен

            candle = df.iloc[current_swing.index]
            atr    = float(candle["atr"])
            if atr <= 0 or pd.isna(atr):
                continue

            mitigations.append(MitigationBlock(
                index=current_swing.index,
                high=float(candle["high"]),
                low=float(candle["low"]),
                direction="bearish",
                failed_to_break=prev_swing.price,
                timestamp=int(candle["ts"]),
                strength=abs(prev_swing.price - current_swing.price) / atr,
            ))

        # ── Swing lows: failed to break prev low (bullish mitigation) ────
        for i in range(1, len(swings_low)):
            current_swing = swings_low[i]
            prev_swing    = swings_low[i - 1]

            if current_swing.price <= prev_swing.price:
                continue  # Обновил — не митигейшен

            # Проверяем: ликвидность prev_swing НЕ снималась между ними
            liq_swept = any(
                float(df.iloc[j]["low"]) < prev_swing.price
                for j in range(prev_swing.index + 1, current_swing.index)
                if j < len(df)
            )
            if liq_swept:
                continue  # Ликвидность снималась → это брейкер, не митигейшен

            candle = df.iloc[current_swing.index]
            atr    = float(candle["atr"])
            if atr <= 0 or pd.isna(atr):
                continue

            mitigations.append(MitigationBlock(
                index=current_swing.index,
                high=float(candle["high"]),
                low=float(candle["low"]),
                direction="bullish",
                failed_to_break=prev_swing.price,
                timestamp=int(candle["ts"]),
                strength=abs(current_swing.price - prev_swing.price) / atr,
            ))

        self.mitigation_blocks = mitigations
        return mitigations
    
    def is_price_in_breaker(
        self,
        price: float,
        direction: str,
        current_idx: int,
    ) -> Optional[BreakerBlock]:
        """Check if price is within an active breaker block."""
        for breaker in self.breaker_blocks:
            # Skip expired breakers
            if current_idx - breaker.break_index > self.expiry_candles:
                continue
            
            # Skip wrong direction
            if breaker.new_direction != direction:
                continue
            
            # Check if price is in breaker zone (original OB zone)
            ob = breaker.original_ob
            if ob.low <= price <= ob.high:
                return breaker
        
        return None
    
    def is_price_in_mitigation(
        self,
        price: float,
        direction: str,
        current_idx: int,
    ) -> Optional[MitigationBlock]:
        """Check if price is within an active mitigation block."""
        for mitigation in self.mitigation_blocks:
            # Skip expired mitigations
            if current_idx - mitigation.index > self.expiry_candles:
                continue
            
            # Skip wrong direction
            if mitigation.direction != direction:
                continue
            
            # Check if price is in mitigation zone
            if mitigation.low <= price <= mitigation.high:
                return mitigation
        
        return None
    
    def get_active_breakers(
        self,
        current_idx: int,
        direction: Optional[str] = None,
    ) -> List[BreakerBlock]:
        """Get list of active breaker blocks."""
        breakers = []
        for breaker in self.breaker_blocks:
            if current_idx - breaker.break_index > self.expiry_candles:
                continue
            if direction and breaker.new_direction != direction:
                continue
            breakers.append(breaker)
        return breakers
    
    def get_active_mitigations(
        self,
        current_idx: int,
        direction: Optional[str] = None,
    ) -> List[MitigationBlock]:
        """Get list of active mitigation blocks."""
        mitigations = []
        for mitigation in self.mitigation_blocks:
            if current_idx - mitigation.index > self.expiry_candles:
                continue
            if direction and mitigation.direction != direction:
                continue
            mitigations.append(mitigation)
        return mitigations
