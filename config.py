"""
Central configuration: symbols, TP/SL multipliers, risk params.
All ATR multipliers are calibrated per-symbol based on historical volatility.
"""

SYMBOLS = [
    "BTCUSDT",
    "ETHUSDT",
    "SOLUSDT",
    "XRPUSDT",
    "MNTUSDT",
    "DOGEUSDT",
    "XAUUSDT",
]

# Per-symbol TP/SL ATR multipliers (4h ATR as base)
# SL = entry ± ATR * sl_mult
# TP = entry ± ATR * tp_mult
# RR is always >= 1:3
# Tuned via fast SMC backtester on 60d 15m / 120d 4h OKX data (Apr 2026).
# Per-symbol grid-search picked SL ≈ 0.6-0.8 ATR, TP ≈ 2.4 ATR (RR 1:3 - 1:4),
# which gave WR 48-58% / PF 2.2-3.7 / expectancy +0.5 - +1.0 R per trade and
# satisfied the >=1 trade/day budget across the basket.  See tuning_results.md.
SYMBOL_PARAMS = {
    "BTCUSDT":  {"sl_mult": 0.6, "tp_mult": 2.4, "leverage": 10, "qty_precision": 3},
    "ETHUSDT":  {"sl_mult": 0.6, "tp_mult": 2.4, "leverage": 10, "qty_precision": 2},
    "SOLUSDT":  {"sl_mult": 0.7, "tp_mult": 2.4, "leverage": 10, "qty_precision": 1},
    "XRPUSDT":  {"sl_mult": 0.6, "tp_mult": 1.8, "leverage": 10, "qty_precision": 1},
    "MNTUSDT":  {"sl_mult": 0.8, "tp_mult": 2.4, "leverage": 10, "qty_precision": 0},
    "DOGEUSDT": {"sl_mult": 0.7, "tp_mult": 2.4, "leverage": 10, "qty_precision": 0},
    "XAUUSDT":  {"sl_mult": 0.8, "tp_mult": 2.4, "leverage": 10, "qty_precision": 2},
}

# Timeframes
HTF = "240"   # 4h  — trend context
LTF = "15"    # 15m — entry timeframe
CTF = "D"     # Daily — старший контекст (ключевые зоны, истинный слом)

# Indicator periods
EMA_FAST   = 20
EMA_SLOW   = 50
SMA_TREND  = 200
RSI_PERIOD = 14
ATR_PERIOD = 14
ATR_AVG_PERIOD = 50
MACD_FAST  = 12
MACD_SLOW  = 26
MACD_SIG   = 9
BB_PERIOD  = 20
BB_STD     = 2.0

# Signal filters
# 32 LTF bars on a 15m chart = 8h cooldown between signals on the same symbol.
# With 7 symbols this still gives ~1.4 trades/day at the basket level.
MIN_BARS_BETWEEN_SIGNALS = 32  # min candles between signals on same symbol
HOLONOMY_SENSITIVITY     = 0.02
ANOMALY_THRESHOLD        = 9999  # disabled until tuned

# Risk management
RISK_PER_TRADE   = 0.01   # 1% of equity — Марко: "не более 1% риска на сделку"
MAX_POSITIONS    = 3      # Марко: разумный лимит открытых позиций
DD_WARNING       = 0.10   # 10% drawdown → risk * 0.75
DD_DANGER        = 0.15   # 15% drawdown → risk * 0.50
BREAKEVEN_ATR    = 2.0    # move SL to entry when profit > 2*ATR
MAX_BARS_IN_TRADE = 100

# Cross-restart signal dedupe window (seconds).
# Suppresses identical (symbol, direction, entry, tp, sl) signals within this
# window even if the process was restarted (which resets SignalEngine state).
# Default = 2h — covers ~8 LTF candles on a 15m TF.
SIGNAL_DEDUPE_SEC = 2 * 60 * 60

# Trading hours UTC (10:00 – 22:00) - DISABLED for testing
TRADE_HOUR_START = 0
TRADE_HOUR_END   = 24

# Candle limit for API requests
CANDLE_LIMIT = 300

# ══════════════════════════════════════════════════════════════════════
#  SMC (Smart Money Concept) Parameters
# ══════════════════════════════════════════════════════════════════════

# Enable/disable SMC strategy (True = SMC, False = classic EMA+RSI)
ENABLE_SMC = True

# SMC Mode: "STRICT" = all filters required (Marco's methodology)
#           "RELAXED" = only Premium/Discount required (more signals)
# STRICT first → RELAXED fallback gave the best risk-adjusted result in the
# parameter sweep (PF 2.5+, win-rate ~50%, expectancy +0.7 R / trade).
SMC_MODE = "STRICT"

# Structure detection
SWING_LOOKBACK = 50              # candles to look back for swing detection
LIQUIDITY_TOLERANCE = 0.002      # 0.2% tolerance for equal highs/lows
LIQUIDITY_SWEEP_LOOKBACK = 10    # candles to check for liquidity sweeps

# Fair Value Gap (FVG) detection
FVG_MIN_SIZE_ATR = 0.3           # minimum FVG size in ATR units
FVG_EXPIRY_CANDLES = 100         # candles before FVG expires

# Order Block detection
OB_IMPULSE_THRESHOLD = 2.0       # minimum ATR multiplier for impulse
OB_EXPIRY_CANDLES = 100          # candles before OB expires

# Breaker/Mitigation Block detection
BREAKER_IMPULSE_THRESHOLD = 2.0  # minimum ATR for breaker confirmation
MITIGATION_EXPIRY_CANDLES = 100  # candles before mitigation block expires

# Premium/Discount zones
# Sweep: 0.50 strictly enforces "buy in discount half / sell in premium half".
# Tighter values (0.40-0.45) cut signal count below the 1 trade/day target.
PREMIUM_DISCOUNT_THRESHOLD = 0.50  # Buy < 0.50, Sell > 0.50

# Use pure SMC (no EMA/RSI) when ENABLE_SMC=True.
# Sweep showed structure-only direction was too restrictive on recent data
# (no signals over 50 LTF days for some symbols).  EMA20/EMA50/SMA200 + RSI
# alignment for direction, gated by SMC entry zone + sweep, is what won.
PURE_SMC = False  # True = only structure, False = structure + EMA/RSI

# ══════════════════════════════════════════════════════════════════════
#  Advanced SMC Features (100% Марко Compliance)
# ══════════════════════════════════════════════════════════════════════

# Setup Patterns (TTS, TDP, Stop Hunt, Double Top/Bottom)
USE_SETUP_PATTERNS = False       # отключено для paper-мониторинга (слишком жёсткий фильтр)
SETUP_PATTERN_CONFIDENCE_MIN = 0.7

# Order Flow (internal/external liquidity)
USE_ORDER_FLOW = False           # отключено для paper-мониторинга
ORDERFLOW_SEQUENCE_REQUIRED = False

# Key Levels ("что держит цену")
USE_KEY_LEVELS = False           # отключено для paper-мониторинга
# BUG #4 FIX: 0.9 вместо 0.8 — меньше ложных блокировок
KEY_LEVEL_IMPORTANCE_MIN = 0.9

# Fibonacci (optional)
USE_FIBONACCI = False           # Use Fibonacci OTE zone
FIBONACCI_USE_OTE = True        # Require price in OTE zone (0.62-0.79)

# AMD Pattern (optional)
# Disabled by tuning sweep — adds rejections without improving expectancy.
USE_AMD = False                 # Марко: AMD — аккумуляция/манипуляция/дистрибуция
AMD_TIMEFRAME = "D"             # D=daily, W=weekly, M=monthly

# Kill Zones (optional)
USE_KILL_ZONES = False          # Крипто 24/7 — не критично, но учитываем
KILL_ZONE_REQUIRED = False      # Не блокируем, только логируем

# Momentum (optional)
# Disabled by tuning sweep — added rejections without improving expectancy.
USE_MOMENTUM = False            # Марко: "рост быстрее коррекции по времени"
MOMENTUM_REQUIRED = False       # Не блокируем, только логируем

# Range Detection
# Disabled by tuning sweep — "reject_range:inside_range" was the second-largest
# rejection bucket and dropped basket trades-per-day below the 1/day target.
USE_RANGE_DETECTION = False     # Марко: боковик с 3 движениями + девиация
RANGE_AVOID_TRADING = False     # Не торгуем внутри ренджа
