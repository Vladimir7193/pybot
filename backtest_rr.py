"""
Backtest для определения оптимального Risk/Reward соотношения.
Тестирует разные RR от 1:1 до 1:6 на исторических данных.
"""
import os
import sys
from datetime import datetime, timedelta
from dotenv import load_dotenv
import pandas as pd
import numpy as np
from typing import List, Dict, Tuple

from config import SYMBOLS, HTF, LTF, SYMBOL_PARAMS, RISK_PER_TRADE
from bybit_client import BybitClient
from indicators import compute_all
from logger import log

load_dotenv()


class BacktestResult:
    def __init__(self, rr: float):
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
        equity = 100.0  # начальный капитал
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
            f"RR 1:{self.rr:.1f} | "
            f"Trades: {len(self.trades)} | "
            f"WR: {self.win_rate:.1f}% | "
            f"PF: {self.profit_factor:.2f} | "
            f"Expectancy: {self.expectancy:.2f}% | "
            f"MaxDD: {self.max_drawdown:.1f}%"
        )


def detect_simple_signals(df_htf: pd.DataFrame, df_ltf: pd.DataFrame) -> List[Dict]:
    """
    Упрощенная генерация сигналов на основе трендовой логики.
    Возвращает список сигналов: [{direction, entry_idx, entry_price, atr}]
    """
    signals = []
    
    if len(df_htf) < 210 or len(df_ltf) < 50:
        return signals
    
    # Проходим по LTF свечам (оставляем последние 20% для тестирования выходов)
    for i in range(50, int(len(df_ltf) * 0.8)):
        htf_idx = int(i * len(df_htf) / len(df_ltf))
        if htf_idx >= len(df_htf) - 2:
            continue
            
        htf = df_htf.iloc[htf_idx]
        ltf = df_ltf.iloc[i]
        
        # Пропускаем если нет данных
        if pd.isna(htf["atr"]) or pd.isna(htf["holonomy"]):
            continue
        
        price = float(ltf["close"])
        atr_val = float(htf["atr"])
        holonomy = float(htf["holonomy"])
        
        # Фильтр по holonomy
        if abs(holonomy) < 0.05:
            continue
        
        # HTF тренд
        ema20 = float(htf["ema20"])
        ema50 = float(htf["ema50"])
        sma200 = float(htf["sma200"]) if not pd.isna(htf["sma200"]) else 0.0
        rsi = float(htf["rsi"])
        htf_price = float(htf["close"])
        
        bullish = (htf_price > sma200 and htf_price > ema20 > ema50 and rsi > 50)
        bearish = (htf_price < sma200 and htf_price < ema20 < ema50 and rsi < 50)
        
        if not bullish and not bearish:
            continue
        
        # LTF подтверждение
        ltf_holonomy = float(ltf["holonomy"])
        ltf_rsi = float(ltf["rsi"])
        
        if bullish and (ltf_holonomy < 0 or ltf_rsi < 45):
            continue
        if bearish and (ltf_holonomy > 0 or ltf_rsi > 55):
            continue
        
        direction = "Buy" if bullish else "Sell"
        
        signals.append({
            "direction": direction,
            "entry_idx": i,
            "entry_price": price,
            "atr": atr_val,
        })
    
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
    max_bars = 100  # максимум 100 свечей держим позицию
    for i in range(entry_idx + 1, min(entry_idx + max_bars, len(df_ltf))):
        candle = df_ltf.iloc[i]
        high = float(candle["high"])
        low = float(candle["low"])
        
        if direction == "Buy":
            # Проверка SL
            if low <= sl_price:
                loss_pct = -RISK_PER_TRADE * 100  # -1%
                return False, loss_pct
            # Проверка TP
            if high >= tp_price:
                profit_pct = RISK_PER_TRADE * 100 * rr  # +RR%
                return True, profit_pct
        else:  # Sell
            # Проверка SL
            if high >= sl_price:
                loss_pct = -RISK_PER_TRADE * 100  # -1%
                return False, loss_pct
            # Проверка TP
            if low <= tp_price:
                profit_pct = RISK_PER_TRADE * 100 * rr  # +RR%
                return True, profit_pct
    
    # Если не закрылась за max_bars, закрываем по рынку (считаем как 0)
    return False, -RISK_PER_TRADE * 100 * 0.5  # половина риска


def backtest_symbol(
    client: BybitClient,
    symbol: str,
    rr_values: List[float],
) -> Dict[float, BacktestResult]:
    """
    Бэктест одного символа с разными RR.
    """
    log.info(f"\n{'='*60}")
    log.info(f"  Backtesting {symbol}")
    log.info(f"{'='*60}")
    
    params = SYMBOL_PARAMS[symbol]
    
    # Загружаем исторические данные (максимум доступных)
    try:
        df_htf = client.get_klines(symbol, HTF, limit=1000)
        df_ltf = client.get_klines(symbol, LTF, limit=1000)
    except Exception as e:
        log.error(f"[{symbol}] Failed to load data: {e}")
        return {}
    
    if df_htf.empty or df_ltf.empty:
        log.warning(f"[{symbol}] Empty data")
        return {}
    
    # Вычисляем индикаторы
    df_htf = compute_all(df_htf)
    df_ltf = compute_all(df_ltf)
    
    log.info(f"[{symbol}] HTF candles: {len(df_htf)}, LTF candles: {len(df_ltf)}")
    
    # Генерируем сигналы
    signals = detect_simple_signals(df_htf, df_ltf)
    log.info(f"[{symbol}] Generated {len(signals)} signals")
    
    if len(signals) == 0:
        return {}
    
    # Тестируем каждое RR
    results = {}
    for rr in rr_values:
        result = BacktestResult(rr)
        
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
    log.info("  RR Optimization Backtest")
    log.info("="*60)
    
    # Подключение к Bybit
    api_key = os.getenv("BYBIT_API_KEY", "")
    api_secret = os.getenv("BYBIT_API_SECRET", "")
    testnet = os.getenv("BYBIT_TESTNET", "false").lower() == "true"
    
    client = BybitClient(api_key, api_secret, testnet)
    
    # Тестируемые RR
    rr_values = [1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0, 5.5, 6.0]
    
    # Выбираем несколько символов для теста (можно все, но будет долго)
    test_symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    
    # Агрегированные результаты по всем символам
    aggregated = {rr: BacktestResult(rr) for rr in rr_values}
    
    for symbol in test_symbols:
        results = backtest_symbol(client, symbol, rr_values)
        
        # Агрегируем результаты
        for rr, result in results.items():
            for trade in result.trades:
                aggregated[rr].add_trade(trade["profit_pct"], trade["win"])
    
    # Финальные метрики
    log.info(f"\n{'='*60}")
    log.info("  AGGREGATED RESULTS (All Symbols)")
    log.info(f"{'='*60}")
    
    best_rr = None
    best_expectancy = -999
    
    for rr in rr_values:
        result = aggregated[rr]
        result.calculate_metrics()
        log.info(f"  {result}")
        
        # Определяем лучший RR по expectancy
        if result.expectancy > best_expectancy:
            best_expectancy = result.expectancy
            best_rr = rr
    
    log.info(f"\n{'='*60}")
    log.info(f"  🏆 OPTIMAL RR: 1:{best_rr:.1f}")
    log.info(f"  Expectancy: {best_expectancy:.2f}%")
    log.info(f"  Win Rate: {aggregated[best_rr].win_rate:.1f}%")
    log.info(f"  Profit Factor: {aggregated[best_rr].profit_factor:.2f}")
    log.info(f"  Max Drawdown: {aggregated[best_rr].max_drawdown:.1f}%")
    log.info(f"{'='*60}")
    
    # Сохраняем результаты в CSV
    results_data = []
    for rr in rr_values:
        r = aggregated[rr]
        results_data.append({
            "RR": f"1:{rr:.1f}",
            "Trades": len(r.trades),
            "Wins": r.wins,
            "Losses": r.losses,
            "Win_Rate_%": round(r.win_rate, 1),
            "Profit_Factor": round(r.profit_factor, 2),
            "Expectancy_%": round(r.expectancy, 2),
            "Max_DD_%": round(r.max_drawdown, 1),
        })
    
    df_results = pd.DataFrame(results_data)
    csv_path = "pybot/backtest_rr_results.csv"
    df_results.to_csv(csv_path, index=False)
    log.info(f"\n📊 Results saved to: {csv_path}")


if __name__ == "__main__":
    main()
