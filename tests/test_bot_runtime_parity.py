from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from types import SimpleNamespace

import pandas as pd

import bot
import bot_paper


def _make_df(rows: int = 260) -> pd.DataFrame:
    close = [100 + i * 0.1 for i in range(rows)]
    return pd.DataFrame({
        "open": close,
        "high": [c + 1 for c in close],
        "low": [c - 1 for c in close],
        "close": close,
        "atr": [2.0] * rows,
        "atr_avg": [2.0] * rows,
        "holonomy": [0.2] * rows,
        "anomaly": [1.0] * rows,
        "ema20": [c - 0.2 for c in close],
        "ema50": [c - 0.5 for c in close],
        "sma200": [c - 1.0 for c in close],
        "rsi": [60.0] * rows,
        "ts": list(range(rows)),
    })


class FakeClient:
    def __init__(self):
        self.instrument = {"min_qty": 0.001, "qty_step": 0.001, "price_tick": 0.01}
        self.frames = {
            bot.HTF: _make_df(320),
            bot.LTF: _make_df(140),
            bot.CTF: _make_df(120),
        }

    def get_klines(self, symbol, interval, limit=0):
        return self.frames[interval].copy()

    def get_instrument_info(self, symbol):
        return dict(self.instrument)

    def place_order(self, *args, **kwargs):
        return "order-1"


class RecordingEngine:
    def __init__(self):
        self.calls = []

    def analyze(self, **kwargs):
        self.calls.append(kwargs)
        return None


class FakePM:
    count = 1

    def has(self, symbol):
        return False


class FakeNotifier:
    def __init__(self):
        self.messages = []

    def error(self, msg):
        self.messages.append(("error", msg))

    def signal(self, **kwargs):
        self.messages.append(("signal", kwargs))


def test_live_and_paper_pass_same_market_context(monkeypatch):
    client = FakeClient()
    live_engine = RecordingEngine()
    paper_engine = RecordingEngine()
    notifier = FakeNotifier()

    monkeypatch.setattr(bot, "compute_all", lambda df: df)
    monkeypatch.setattr(bot_paper, "compute_all", lambda df: df)
    monkeypatch.setattr(bot, "is_trading_hour", lambda: True)
    monkeypatch.setattr(bot_paper, "is_trading_hour", lambda: True)

    bot._process_symbol("BTCUSDT", client, notifier, live_engine, FakePM(), 1000.0, 0.15)
    bot_paper._process_symbol("BTCUSDT", client, notifier, paper_engine, 1000.0, 0.0, 0)

    live_call = live_engine.calls[-1]
    paper_call = paper_engine.calls[-1]

    assert live_call["symbol"] == paper_call["symbol"] == "BTCUSDT"
    assert list(live_call["df_htf"].columns) == list(paper_call["df_htf"].columns)
    assert len(live_call["df_htf"]) == len(paper_call["df_htf"])
    assert len(live_call["df_ltf"]) == len(paper_call["df_ltf"])
    assert len(live_call["df_ctf"]) == len(paper_call["df_ctf"])
    assert live_call["instrument"] == paper_call["instrument"] == client.instrument
    assert live_call["equity"] == paper_call["equity"] == 1000.0
    assert live_call["drawdown"] == 0.15
    assert paper_call["drawdown"] == 0.0
    assert live_call["open_count"] == 1
    assert paper_call["open_count"] == 0
