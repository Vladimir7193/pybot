"""Unit tests for signal_dedupe.SignalDedupe."""
import json
import os
import tempfile
import time

import pytest

from signal_dedupe import SignalDedupe


@pytest.fixture
def tmp_path_json(tmp_path):
    return str(tmp_path / "dedupe.json")


def test_first_emit_allowed(tmp_path_json):
    d = SignalDedupe(path=tmp_path_json, window_sec=3600)
    assert d.should_emit("BTCUSDT", "Buy", 100.0, 110.0, 95.0) is True


def test_duplicate_within_window_blocked(tmp_path_json):
    d = SignalDedupe(path=tmp_path_json, window_sec=3600)
    now = time.time()
    d.record("BTCUSDT", "Buy", 100.0, 110.0, 95.0, now_ts=now)

    assert d.should_emit("BTCUSDT", "Buy", 100.0, 110.0, 95.0, now_ts=now + 10) is False


def test_different_direction_allowed(tmp_path_json):
    d = SignalDedupe(path=tmp_path_json, window_sec=3600)
    now = time.time()
    d.record("BTCUSDT", "Buy", 100.0, 110.0, 95.0, now_ts=now)

    assert d.should_emit("BTCUSDT", "Sell", 100.0, 90.0, 105.0, now_ts=now + 10) is True


def test_different_symbol_allowed(tmp_path_json):
    d = SignalDedupe(path=tmp_path_json, window_sec=3600)
    now = time.time()
    d.record("BTCUSDT", "Buy", 100.0, 110.0, 95.0, now_ts=now)

    assert d.should_emit("ETHUSDT", "Buy", 100.0, 110.0, 95.0, now_ts=now + 10) is True


def test_price_within_tolerance_blocked(tmp_path_json):
    d = SignalDedupe(path=tmp_path_json, window_sec=3600)
    now = time.time()
    d.record("BTCUSDT", "Buy", 100.0, 110.0, 95.0, now_ts=now)

    # 1e-7 relative change — within default rel_tol
    assert d.should_emit("BTCUSDT", "Buy", 100.000005, 110.0, 95.0, now_ts=now + 10) is False


def test_price_outside_tolerance_allowed(tmp_path_json):
    d = SignalDedupe(path=tmp_path_json, window_sec=3600)
    now = time.time()
    d.record("BTCUSDT", "Buy", 100.0, 110.0, 95.0, now_ts=now)

    # 0.1% change — well above tolerance
    assert d.should_emit("BTCUSDT", "Buy", 100.1, 110.0, 95.0, now_ts=now + 10) is True


def test_window_expiration_allows_re_emit(tmp_path_json):
    d = SignalDedupe(path=tmp_path_json, window_sec=60)
    now = 1000.0
    d.record("BTCUSDT", "Buy", 100.0, 110.0, 95.0, now_ts=now)

    assert d.should_emit("BTCUSDT", "Buy", 100.0, 110.0, 95.0, now_ts=now + 30) is False
    assert d.should_emit("BTCUSDT", "Buy", 100.0, 110.0, 95.0, now_ts=now + 120) is True


def test_persistence_across_instances(tmp_path_json):
    d1 = SignalDedupe(path=tmp_path_json, window_sec=3600)
    now = time.time()
    d1.record("BTCUSDT", "Buy", 100.0, 110.0, 95.0, now_ts=now)

    d2 = SignalDedupe(path=tmp_path_json, window_sec=3600)
    assert d2.should_emit("BTCUSDT", "Buy", 100.0, 110.0, 95.0, now_ts=now + 10) is False


def test_corrupted_state_file_does_not_crash(tmp_path):
    path = str(tmp_path / "corrupt.json")
    with open(path, "w") as f:
        f.write("not-json")
    d = SignalDedupe(path=path, window_sec=3600)
    assert d.should_emit("BTCUSDT", "Buy", 100.0, 110.0, 95.0) is True


def test_clear_removes_history(tmp_path_json):
    d = SignalDedupe(path=tmp_path_json, window_sec=3600)
    now = time.time()
    d.record("BTCUSDT", "Buy", 100.0, 110.0, 95.0, now_ts=now)
    d.clear("BTCUSDT")
    assert d.should_emit("BTCUSDT", "Buy", 100.0, 110.0, 95.0, now_ts=now + 10) is True
