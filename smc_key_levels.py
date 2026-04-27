"""
Smart Money Concepts: Key Levels Tracker
Tracks what holds price - untested zones, key swings, pool liquidity

Марко: "цену всегда держит не тестированная зона"

Hardening notes:
- Every public method tolerates malformed inputs (tuples of wrong size,
  objects lacking ``index``/``price``/``direction``) and silently skips them
  instead of crashing the whole tick. This used to manifest as
  ``'tuple' object has no attribute 'get'`` in production logs.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import List, Optional
import pandas as pd


@dataclass
class KeyLevel:
    """Key level that holds price."""
    level_type: str  # "key_swing" | "untested_zone" | "pool_liquidity"
    price: float
    index: int
    direction: str  # "support" | "resistance"
    tested: bool
    importance: float  # 0.0-1.0
    timestamp: int


def _ts_at(df: pd.DataFrame, idx: int) -> int:
    """Safe timestamp lookup. Returns 0 if idx out of range or ts missing."""
    if idx is None or idx < 0 or idx >= len(df):
        return 0
    row = df.iloc[idx]
    try:
        return int(row["ts"])
    except (KeyError, TypeError, ValueError):
        return 0


class KeyLevelsTracker:
    """
    Tracks key levels that hold price.

    Марко: "цену всегда держит не тестированная зона словно
    если у нас ценообразование было бы такое У нас остался
    не тестированный ордер блок выше него не тестированный баланс"
    """

    def __init__(self, test_tolerance: float = 0.002):
        """
        test_tolerance: price tolerance for considering zone "tested" (0.2%)
        """
        self.test_tolerance = test_tolerance
        self.key_levels: List[KeyLevel] = []

    def identify_key_swings(
        self,
        df: pd.DataFrame,
        swings_high: List,
        swings_low: List,
        structure_breaks: List,
    ) -> List[KeyLevel]:
        """
        Identify key swings that hold price.

        Марко: "ключевым свингом будет данный свинг только при нарушении его
        мы будем расценивать это как слом структуры"
        """
        key_swings: List[KeyLevel] = []

        for sb in structure_breaks or []:
            # Accept either a dict ({"index":.., "direction":..}) or a
            # dataclass-like object with matching attributes. Skip anything
            # else instead of crashing — this used to raise
            # "'tuple' object has no attribute 'get'" in the wild.
            if isinstance(sb, dict):
                sb_idx = int(sb.get("index", -1))
                sb_dir = str(sb.get("direction", ""))
            elif hasattr(sb, "index") and hasattr(sb, "direction"):
                sb_idx = int(getattr(sb, "index", -1))
                sb_dir = str(getattr(sb, "direction", ""))
            else:
                continue

            if sb_dir == "bullish":
                # Find last swing low before break
                relevant_swings = [s for s in (swings_low or []) if getattr(s, "index", -1) < sb_idx]
                if relevant_swings:
                    last_swing = max(relevant_swings, key=lambda x: x.index)
                    if last_swing.index < len(df):
                        key_swings.append(KeyLevel(
                            level_type="key_swing",
                            price=float(last_swing.price),
                            index=int(last_swing.index),
                            direction="support",
                            tested=False,
                            importance=0.9,
                            timestamp=_ts_at(df, last_swing.index),
                        ))

            elif sb_dir == "bearish":
                # Find last swing high before break
                relevant_swings = [s for s in (swings_high or []) if getattr(s, "index", -1) < sb_idx]
                if relevant_swings:
                    last_swing = max(relevant_swings, key=lambda x: x.index)
                    if last_swing.index < len(df):
                        key_swings.append(KeyLevel(
                            level_type="key_swing",
                            price=float(last_swing.price),
                            index=int(last_swing.index),
                            direction="resistance",
                            tested=False,
                            importance=0.9,
                            timestamp=_ts_at(df, last_swing.index),
                        ))

        return key_swings

    def identify_untested_zones(
        self,
        df: pd.DataFrame,
        order_blocks: List,
        fvgs: List,
        breakers: List,
        mitigations: List,
    ) -> List[KeyLevel]:
        """
        Identify untested zones of interest.

        Марко: "ниже у нас не тестированные зоны интереса
        из большей вероятностью цена продолжит наценку"
        """
        untested: List[KeyLevel] = []

        # Order Blocks
        for ob in order_blocks or []:
            if getattr(ob, "tested", False):
                continue
            idx = int(getattr(ob, "index", -1))
            if idx < 0 or idx >= len(df):
                continue
            direction = "support" if getattr(ob, "direction", "") == "bullish" else "resistance"
            mid_price = (float(ob.high) + float(ob.low)) / 2
            untested.append(KeyLevel(
                level_type="untested_zone",
                price=mid_price,
                index=idx,
                direction=direction,
                tested=False,
                importance=0.8,
                timestamp=_ts_at(df, idx),
            ))

        # FVGs — only zones that are still mostly un-filled
        for fvg in fvgs or []:
            if getattr(fvg, "fill_percentage", 1.0) >= 0.5:
                continue
            idx = int(getattr(fvg, "index", -1))
            if idx < 0 or idx >= len(df):
                continue
            direction = "support" if getattr(fvg, "direction", "") == "bullish" else "resistance"
            mid_price = (float(fvg.high) + float(fvg.low)) / 2
            untested.append(KeyLevel(
                level_type="untested_zone",
                price=mid_price,
                index=idx,
                direction=direction,
                tested=False,
                importance=0.7,
                timestamp=_ts_at(df, idx),
            ))

        # Breakers (very important)
        for breaker in breakers or []:
            ob = getattr(breaker, "original_ob", None)
            break_idx = int(getattr(breaker, "break_index", -1))
            new_dir = getattr(breaker, "new_direction", "")
            if ob is None or break_idx < 0 or break_idx >= len(df):
                continue
            direction = "support" if new_dir == "bullish" else "resistance"
            mid_price = (float(ob.high) + float(ob.low)) / 2
            untested.append(KeyLevel(
                level_type="untested_zone",
                price=mid_price,
                index=break_idx,
                direction=direction,
                tested=False,
                importance=0.95,
                timestamp=_ts_at(df, break_idx),
            ))

        # Mitigations
        for mitigation in mitigations or []:
            idx = int(getattr(mitigation, "index", -1))
            if idx < 0 or idx >= len(df):
                continue
            direction = "support" if getattr(mitigation, "direction", "") == "bullish" else "resistance"
            mid_price = (float(mitigation.high) + float(mitigation.low)) / 2
            untested.append(KeyLevel(
                level_type="untested_zone",
                price=mid_price,
                index=idx,
                direction=direction,
                tested=False,
                importance=0.75,
                timestamp=_ts_at(df, idx),
            ))

        return untested

    def identify_pool_liquidity(
        self,
        df: pd.DataFrame,
        equal_highs: List,
        equal_lows: List,
    ) -> List[KeyLevel]:
        """
        Identify pool liquidity (equal highs/lows).

        ``equal_highs`` / ``equal_lows`` are expected to be iterables of
        ``(Swing, Swing)`` tuples. Anything else is silently skipped.
        """
        pools: List[KeyLevel] = []

        def _process(pairs, direction: str, pool: List[KeyLevel]) -> None:
            for swing_pair in pairs or []:
                if not isinstance(swing_pair, (tuple, list)) or len(swing_pair) != 2:
                    continue
                s1, s2 = swing_pair
                if not (hasattr(s1, "index") and hasattr(s1, "price")
                        and hasattr(s2, "index") and hasattr(s2, "price")):
                    continue
                swing = s1 if s1.index > s2.index else s2
                if swing.index >= len(df):
                    continue
                pool.append(KeyLevel(
                    level_type="pool_liquidity",
                    price=float(swing.price),
                    index=int(swing.index),
                    direction=direction,
                    tested=False,
                    importance=0.6,
                    timestamp=_ts_at(df, swing.index),
                ))

        _process(equal_highs, "resistance", pools)
        _process(equal_lows,  "support",    pools)
        return pools

    def update_all_levels(
        self,
        df: pd.DataFrame,
        swings_high: List,
        swings_low: List,
        structure_breaks: List,
        order_blocks: List,
        fvgs: List,
        breakers: List,
        mitigations: List,
        equal_highs: List,
        equal_lows: List,
    ) -> List[KeyLevel]:
        """Update all key levels."""
        all_levels: List[KeyLevel] = []

        all_levels.extend(self.identify_key_swings(df, swings_high, swings_low, structure_breaks))
        all_levels.extend(self.identify_untested_zones(df, order_blocks, fvgs, breakers, mitigations))
        all_levels.extend(self.identify_pool_liquidity(df, equal_highs, equal_lows))

        all_levels.sort(key=lambda x: x.importance, reverse=True)
        self.key_levels = all_levels
        return all_levels

    def mark_tested(
        self,
        df: pd.DataFrame,
        current_idx: int,
    ) -> List[KeyLevel]:
        """Mark levels as tested when price reaches them."""
        tested: List[KeyLevel] = []

        if current_idx >= len(df) or current_idx < 0:
            return tested

        current_high = float(df.iloc[current_idx]["high"])
        current_low = float(df.iloc[current_idx]["low"])

        for level in self.key_levels:
            if level.tested:
                continue

            tolerance = level.price * self.test_tolerance

            if level.direction == "support":
                if current_low <= level.price + tolerance:
                    level.tested = True
                    tested.append(level)

            elif level.direction == "resistance":
                if current_high >= level.price - tolerance:
                    level.tested = True
                    tested.append(level)

        return tested

    def what_holds_price(
        self,
        current_price: float,
        direction: str,
    ) -> Optional[KeyLevel]:
        """
        Determine what holds price in the direction.

        Returns the most important untested level in the direction.
        """
        if direction == "bullish":
            supports = [
                level for level in self.key_levels
                if not level.tested
                and level.direction == "support"
                and level.price < current_price
            ]
            if supports:
                supports.sort(key=lambda x: (current_price - x.price, -x.importance))
                return supports[0]

        elif direction == "bearish":
            resistances = [
                level for level in self.key_levels
                if not level.tested
                and level.direction == "resistance"
                and level.price > current_price
            ]
            if resistances:
                resistances.sort(key=lambda x: (x.price - current_price, -x.importance))
                return resistances[0]

        return None

    def is_true_structure_break(
        self,
        current_price: float,
        break_direction: str,
    ) -> bool:
        """
        Check if structure break is "true" (no untested key swings holding price).

        Only ``key_swing`` levels indicate fake structure breaks (Марко:
        "ключевой свинг"). Breakers, OBs, FVGs are valid entry zones — they
        must NOT block a valid signal.
        """
        holding_level = self.what_holds_price(current_price, break_direction)
        if holding_level is None:
            return True
        if holding_level.level_type != "key_swing":
            return True
        if holding_level.importance < 0.7:
            return True
        return False

    def get_key_swing_level(
        self,
        direction: str,
    ) -> Optional[float]:
        """Get key swing level that must be broken for true structure break."""
        key_swings = [
            level for level in self.key_levels
            if level.level_type == "key_swing" and not level.tested
        ]
        if not key_swings:
            return None

        if direction == "bullish":
            supports = [s for s in key_swings if s.direction == "support"]
            return min([s.price for s in supports]) if supports else None

        if direction == "bearish":
            resistances = [s for s in key_swings if s.direction == "resistance"]
            return max([s.price for s in resistances]) if resistances else None

        return None
