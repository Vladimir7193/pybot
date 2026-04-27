"""
Persistent signal dedupe / cooldown.

Prevents the bot from re-emitting the same signal after a process restart
(which resets the in-memory cooldown inside SignalEngine) or multiple ticks
before the LTF candle actually closes. The key is (symbol, direction,
entry, tp, sl) with a relative tolerance, scoped per symbol for a
configurable time window.

State is persisted to a JSON file so paper and live bots keep their
dedupe across restarts.
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class _SignalKey:
    symbol:    str
    direction: str
    entry:     float
    tp:        float
    sl:        float

    def matches(self, other: "_SignalKey", rel_tol: float = 1e-6) -> bool:
        if self.symbol != other.symbol:
            return False
        if self.direction != other.direction:
            return False

        def _close(a: float, b: float) -> bool:
            if a == b:
                return True
            denom = max(abs(a), abs(b), 1e-9)
            return abs(a - b) / denom <= rel_tol

        return (
            _close(self.entry, other.entry)
            and _close(self.tp, other.tp)
            and _close(self.sl, other.sl)
        )


class SignalDedupe:
    """
    Cross-restart dedupe with a time-window cooldown.

    Parameters
    ----------
    path: str
        JSON file path. Parent directories are created on write.
        Pass an empty string to run purely in-memory (tests).
    window_sec: int
        Cooldown window in seconds. Within this window, any signal with the
        same (direction, entry, tp, sl) on the same symbol is suppressed.
    """

    def __init__(self, path: str, window_sec: int = 7200):
        self._path = path
        self._window_sec = max(0, int(window_sec))
        self._lock = threading.Lock()
        self._state: dict = self._load()

    # ── persistence ───────────────────────────────────────────────────────
    def _load(self) -> dict:
        if not self._path or not os.path.exists(self._path):
            return {}
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _save(self) -> None:
        if not self._path:
            return
        directory = os.path.dirname(self._path) or "."
        os.makedirs(directory, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(prefix=".dedupe_", dir=directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self._state, f)
            os.replace(tmp_path, self._path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass
            raise

    # ── public API ────────────────────────────────────────────────────────
    @property
    def window_sec(self) -> int:
        return self._window_sec

    def last(self, symbol: str) -> Optional[dict]:
        with self._lock:
            rec = self._state.get(symbol)
            return dict(rec) if isinstance(rec, dict) else None

    def should_emit(
        self,
        symbol:    str,
        direction: str,
        entry:     float,
        tp:        float,
        sl:        float,
        now_ts:    Optional[float] = None,
    ) -> bool:
        """Return True iff this signal is not a duplicate of a recent one."""
        now = time.time() if now_ts is None else float(now_ts)
        with self._lock:
            rec = self._state.get(symbol)
            if not isinstance(rec, dict):
                return True
            try:
                ts = float(rec.get("ts", 0.0))
            except (TypeError, ValueError):
                ts = 0.0
            if self._window_sec > 0 and (now - ts) > self._window_sec:
                return True

            k_new = _SignalKey(symbol, direction, float(entry), float(tp), float(sl))
            try:
                k_old = _SignalKey(
                    symbol=symbol,
                    direction=str(rec.get("dir", "")),
                    entry=float(rec.get("entry", 0.0)),
                    tp=float(rec.get("tp", 0.0)),
                    sl=float(rec.get("sl", 0.0)),
                )
            except (TypeError, ValueError):
                return True
            return not k_new.matches(k_old)

    def record(
        self,
        symbol:    str,
        direction: str,
        entry:     float,
        tp:        float,
        sl:        float,
        now_ts:    Optional[float] = None,
    ) -> None:
        now = time.time() if now_ts is None else float(now_ts)
        with self._lock:
            self._state[symbol] = {
                "ts":    float(now),
                "dir":   direction,
                "entry": float(entry),
                "tp":    float(tp),
                "sl":    float(sl),
            }
            try:
                self._save()
            except Exception:
                # Persistence must never crash the bot.
                pass

    def clear(self, symbol: Optional[str] = None) -> None:
        with self._lock:
            if symbol is None:
                self._state.clear()
            else:
                self._state.pop(symbol, None)
            try:
                self._save()
            except Exception:
                pass
