"""
Backtest для сравнения Classic vs SMC стратегий.
Тестирует обе стратегии на одних и тех же данных.
"""
import os
import sys
from datetime import datetime, timedelta
from dotenv import load_dotenv
import pandas as pd
import numpy as np
from typing import List, Dict, Tuple

from config import SYMBOLS, HTF, LTF, CTF, SYMBOL_PARAMS, RISK_PER_TRADE, ENABLE_SMC, MIN_BARS_BETWEEN_SIGNALS
from bybit_client import BybitClient
from indicators import compute_all
from signal_engine import SignalEngine
from logger import log

load_dotenv()


class BacktestResult:
    def __init__(self, strategy_name: str, rr: float):
        self.strategy_name = strategy_name
        self.rr = rr
        self.trades: List[Dict] = []
        self.wins = 0
        self.losses = 0
        self.total_profit = 0.0
        self.total_loss = 0.0
        self.max_drawdown = 0.0
        self.win_rate = 0.0
        self.profit_factor = 0.0
        self.expectancy = 0.0
        
    def add_trade(self, profit_pct: float, win: bool):
        self.trades.append({"profit_pct": profit_pct, "win": win})
        if win:
            self.wins += 1
            self.total_profit += profit_pct
        else:
            self.losses += 1
            self.total_loss += abs(profit_pct)
    
    def calculate_metrics(self):
        total = self.wins + self.losses
        if total == 0:
            return
        
        self.win_rate = self.wins / total * 100
        self.profit_factor = self.total_profit / self.total_loss if self.total_loss > 0 else 0
        self.expectancy = (self.total_profit - self.total_loss) / total
        
        # Расчет максимальной просадки
        equity = 100.0
        peak = equity
        max_dd = 0.0
        
        for trade in self.trades:
            equity += trade["profit_pct"]
            if equity > peak:
                peak = equity
            dd = (peak - equity) / peak * 100
            if dd > max_dd:
                max_dd = dd
        
        self.max_drawdown = max_dd
    
    def __str__(self):
        return (
            f"{self.strategy_name} RR 1:{self.rr:.1f} | "
            f"Trades: {len(self.trades)} | "
            f"WR: {self.win_rate:.1f}% | "
            f"PF: {self.profit_factor:.2f} | "
            f"Expectancy: {self.expectancy:.2f}% | "
            f"MaxDD: {self.max_drawdown:.1f}%"
        )


def detect_smc_signals(
    engine: SignalEngine,
    df_htf: pd.DataFrame,
    df_ltf: pd.DataFrame,
    symbol: str,
    instrument: dict,
    df_ctf: pd.DataFrame | None = None,
) -> List[Dict]:
    """
    Генерация SMC сигналов.
    Возвращает список сигналов: [{direction, entry_idx, entry_price, atr}]
    """
    signals = []
    
    if len(df_htf) < 210 or len(df_ltf) < 50:
        return signals
    
    # Проходим по LTF свечам
    i = 50
    max_i = int(len(df_ltf) * 0.8)
    while i < max_i:
        # Создаем срезы данных до текущей свечи
        htf_end = int(i * len(df_htf) / len(df_ltf)) + 1
        ctf_end = None if df_ctf is None else max(1, int(i * len(df_ctf) / len(df_ltf)) + 1)
        df_htf_slice = df_htf.iloc[:htf_end].copy()
        df_ltf_slice = df_ltf.iloc[:i + 1].copy()
        df_ctf_slice = None if df_ctf is None else df_ctf.iloc[:ctf_end].copy()

        if len(df_htf_slice) < 210:
            i += 1
            continue

        # Пробуем сгенерировать сигнал
        try:
            sig = engine.analyze(
                symbol=symbol,
                df_htf=df_htf_slice,
                df_ltf=df_ltf_slice,
                df_ctf=df_ctf_slice,
                equity=1000.0,
                drawdown=0.0,
                open_count=0,
                instrument=instrument,
            )

            if sig:
                signals.append({
                    "direction": sig.direction,
                    "entry_idx": i,
                    "entry_price": sig.entry,
                    "atr": sig.atr,
                })
                i += max(1, MIN_BARS_BETWEEN_SIGNALS)
                continue
        except Exception:
            # Игнорируем ошибки в процессе генерации
            pass

        i += 1
    
    return signals


def simulate_trade(
    signal: Dict,
    df_ltf: pd.DataFrame,
    rr: float,
    sl_mult: float,
) -> Tuple[bool, float]:
    """
    Симулирует сделку с заданным RR.
    Возвращает (win, profit_pct)
    """
    entry_idx = signal["entry_idx"]
    entry_price = signal["entry_price"]
    atr = signal["atr"]
    direction = signal["direction"]
    
    # Расчет SL и TP
    sl_dist = atr * sl_mult
    tp_dist = sl_dist * rr
    
    if direction == "Buy":
        sl_price = entry_price - sl_dist
        tp_price = entry_price + tp_dist
    else:
        sl_price = entry_price + sl_dist
        tp_price = entry_price - tp_dist
    
    # Проверяем следующие свечи
    max_bars = 100
    for i in range(entry_idx + 1, min(entry_idx + max_bars, len(df_ltf))):
        candle = df_ltf.iloc[i]
        high = float(candle["high"])
        low = float(candle["low"])
        
        if direction == "Buy":
            if low <= sl_price:
                loss_pct = -RISK_PER_TRADE * 100
                return False, loss_pct
            if high >= tp_price:
                profit_pct = RISK_PER_TRADE * 100 * rr
                return True, profit_pct
        else:
            if high >= sl_price:
                loss_pct = -RISK_PER_TRADE * 100
                return False, loss_pct
            if low <= tp_price:
                profit_pct = RISK_PER_TRADE * 100 * rr
                return True, profit_pct
    
    # Если не закрылась, считаем половину риска
    return False, -RISK_PER_TRADE * 100 * 0.5


def backtest_symbol(
    client: BybitClient,
    symbol: str,
    rr_values: List[float],
    use_smc: bool,
) -> Dict[float, BacktestResult]:
    """
    Бэктест одного символа.
    """
    strategy_name = "SMC" if use_smc else "Classic"
    log.info(f"\n{'='*60}")
    log.info(f"  Backtesting {symbol} ({strategy_name})")
    log.info(f"{'='*60}")
    
    params = SYMBOL_PARAMS[symbol]
    
    # Загружаем данные
    try:
        df_htf = client.get_klines(symbol, HTF, limit=1000)
        df_ltf = client.get_klines(symbol, LTF, limit=1000)
        df_ctf = client.get_klines(symbol, CTF, limit=400)
    except Exception as e:
        log.error(f"[{symbol}] Failed to load data: {e}")
        return {}
    
    if df_htf.empty or df_ltf.empty:
        log.warning(f"[{symbol}] Empty data")
        return {}
    
    # Вычисляем индикаторы
    df_htf = compute_all(df_htf)
    df_ltf = compute_all(df_ltf)
    df_ctf = compute_all(df_ctf) if df_ctf is not None and not df_ctf.empty else None
    
    log.info(f"[{symbol}] HTF: {len(df_htf)}, LTF: {len(df_ltf)}, CTF: {len(df_ctf) if df_ctf is not None else 0}")
    
    # Получаем instrument info
    try:
        instrument = client.get_instrument_info(symbol)
    except Exception as e:
        log.warning(f"[{symbol}] Instrument info failed: {e}")
        return {}
    
    # Создаем signal engine
    engine = SignalEngine(equity_fn=lambda: 1000.0, max_positions=3)
    
    # Генерируем сигналы
    signals = detect_smc_signals(engine, df_htf, df_ltf, symbol, instrument, df_ctf=df_ctf)
    log.info(f"[{symbol}] Generated {len(signals)} signals")
    
    if len(signals) == 0:
        return {}
    
    # Тестируем каждое RR
    results = {}
    for rr in rr_values:
        result = BacktestResult(strategy_name, rr)
        
        for signal in signals:
            win, profit_pct = simulate_trade(
                signal, df_ltf, rr, params["sl_mult"]
            )
            result.add_trade(profit_pct, win)
        
        result.calculate_metrics()
        results[rr] = result
        log.info(f"  {result}")
    
    return results


def main():
    log.info("="*60)
    log.info("  SMC vs Classic Strategy Backtest")
    log.info("="*60)
    
    # Подключение к Bybit
    api_key = os.getenv("BYBIT_API_KEY", "")
    api_secret = os.getenv("BYBIT_API_SECRET", "")
    testnet = os.getenv("BYBIT_TESTNET", "false").lower() == "true"
    
    client = BybitClient(api_key, api_secret, testnet)
    
    # Тестируемые RR
    rr_values = [1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0]
    
    # Тестируем на 3 символах
    test_symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    
    # Результаты для обеих стратегий
    smc_aggregated = {rr: BacktestResult("SMC", rr) for rr in rr_values}
    classic_aggregated = {rr: BacktestResult("Classic", rr) for rr in rr_values}
    
    # Тестируем SMC стратегию
    log.info(f"\n{'#'*60}")
    log.info("  TESTING SMC STRATEGY")
    log.info(f"{'#'*60}")
    
    # Временно включаем SMC
    import config
    original_enable_smc = config.ENABLE_SMC
    config.ENABLE_SMC = True
    
    for symbol in test_symbols:
        results = backtest_symbol(client, symbol, rr_values, use_smc=True)
        for rr, result in results.items():
            for trade in result.trades:
                smc_aggregated[rr].add_trade(trade["profit_pct"], trade["win"])
    
    # Тестируем Classic стратегию
    log.info(f"\n{'#'*60}")
    log.info("  TESTING CLASSIC STRATEGY")
    log.info(f"{'#'*60}")
    
    config.ENABLE_SMC = False
    
    for symbol in test_symbols:
        results = backtest_symbol(client, symbol, rr_values, use_smc=False)
        for rr, result in results.items():
            for trade in result.trades:
                classic_aggregated[rr].add_trade(trade["profit_pct"], trade["win"])
    
    # Восстанавливаем настройку
    config.ENABLE_SMC = original_enable_smc
    
    # Финальное сравнение
    log.info(f"\n{'='*60}")
    log.info("  COMPARISON: SMC vs Classic")
    log.info(f"{'='*60}")
    
    comparison_data = []
    
    for rr in rr_values:
        smc_result = smc_aggregated[rr]
        classic_result = classic_aggregated[rr]
        
        smc_result.calculate_metrics()
        classic_result.calculate_metrics()
        
        log.info(f"\nRR 1:{rr:.1f}:")
        log.info(f"  SMC:     {smc_result}")
        log.info(f"  Classic: {classic_result}")
        
        comparison_data.append({
            "RR": f"1:{rr:.1f}",
            "SMC_Trades": len(smc_result.trades),
            "SMC_WR_%": round(smc_result.win_rate, 1),
            "SMC_PF": round(smc_result.profit_factor, 2),
            "SMC_Exp_%": round(smc_result.expectancy, 2),
            "Classic_Trades": len(classic_result.trades),
            "Classic_WR_%": round(classic_result.win_rate, 1),
            "Classic_PF": round(classic_result.profit_factor, 2),
            "Classic_Exp_%": round(classic_result.expectancy, 2),
        })
    
    # Находим лучшие RR для каждой стратегии
    best_smc_rr = max(rr_values, key=lambda r: smc_aggregated[r].expectancy)
    best_classic_rr = max(rr_values, key=lambda r: classic_aggregated[r].expectancy)
    
    log.info(f"\n{'='*60}")
    log.info(f"  🏆 BEST RESULTS")
    log.info(f"{'='*60}")
    log.info(f"\nSMC Strategy:")
    log.info(f"  Best RR: 1:{best_smc_rr:.1f}")
    log.info(f"  {smc_aggregated[best_smc_rr]}")
    
    log.info(f"\nClassic Strategy:")
    log.info(f"  Best RR: 1:{best_classic_rr:.1f}")
    log.info(f"  {classic_aggregated[best_classic_rr]}")
    
    # Сохраняем результаты
    df_comparison = pd.DataFrame(comparison_data)
    csv_path = "pybot/backtest_smc_comparison.csv"
    df_comparison.to_csv(csv_path, index=False)
    log.info(f"\n📊 Results saved to: {csv_path}")


if __name__ == "__main__":
    main()
