# SMC STRICT Mode - Quick Start Guide

## What Changed?

Your bot now has **3 operating modes** for SMC strategy:

### 1. STRICT Mode (Márko's Methodology) ⭐ RECOMMENDED
```python
# config.py
ENABLE_SMC = True
SMC_MODE = "STRICT"
PURE_SMC = True
```

**What it does:**
- ✅ Uses ONLY structure (no EMA/RSI)
- ✅ ALL 4 filters REQUIRED:
  - BOS (Break of Structure)
  - Liquidity Sweep
  - Premium/Discount Zone
  - Entry Zone (Breaker/Mitigation/OB/FVG)
- ✅ 100% compliant with Márko's strategy
- ⚠️ Fewer signals (high quality only)

### 2. RELAXED Mode (More Signals)
```python
# config.py
ENABLE_SMC = True
SMC_MODE = "RELAXED"
PURE_SMC = False
```

**What it does:**
- ✅ Uses EMA+RSI for trend
- ✅ Only Premium/Discount REQUIRED
- ✅ Other filters optional
- ⚠️ More signals but less strict

### 3. Classic Mode (Original Strategy)
```python
# config.py
ENABLE_SMC = False
```

**What it does:**
- ✅ Original EMA+RSI+ATR strategy
- ✅ No SMC filters
- ✅ Backward compatible

---

## How to Use

### Step 1: Choose Your Mode

Edit `pybot/config.py`:

```python
# For Márko's methodology (recommended):
ENABLE_SMC = True
SMC_MODE = "STRICT"
PURE_SMC = True

# OR for more signals:
ENABLE_SMC = True
SMC_MODE = "RELAXED"
PURE_SMC = False

# OR for classic strategy:
ENABLE_SMC = False
```

### Step 2: Run Paper Trading Bot

```bash
cd pybot
python bot_paper.py
```

### Step 3: Monitor Logs

Watch for signals in logs:
```
[BTCUSDT] SMC STRICT: BOS✓ Sweep✓ Discount✓(0.35) Breaker✓ (245ms)
🚀 SIGNAL BTCUSDT LONG 🟢
  Entry: 95234.50
  Take Profit: 98456.20 (+3.38%)
  Stop Loss: 94123.10 (-1.17%)
  RR: 1:3.00
  Reason: SMC-STRICT Buy | BOS✓ Sweep✓ Discount✓(0.35) Breaker✓ | ATR=1234.56
```

### Step 4: Compare Modes (Optional)

Test both modes to see difference:
```bash
python test_mode_comparison.py
```

---

## What's New?

### 1. Breaker Blocks (Highest Priority)
- Order Blocks that were broken impulsively
- Changes polarity (bullish OB → bearish breaker)
- Strongest entry zones

### 2. Mitigation Blocks (Second Priority)
- Failed swings that didn't break structure
- SMS (unsuccessful swing)
- Good entry zones

### 3. Entry Zone Priority
1. **Breaker Block** (best)
2. **Mitigation Block** (good)
3. **Order Block** (standard)
4. **Fair Value Gap** (acceptable)

### 4. Pure Structure Trading
- No EMA/RSI when `PURE_SMC = True`
- Uses only BOS/CHoCH for trend
- True Smart Money Concept

---

## Signal Quality Expectations

### STRICT Mode:
- **Signals per day:** 0-2 (very selective)
- **Win rate target:** 40-50%
- **Risk/Reward:** 1:3 minimum
- **Quality:** Highest (all filters pass)

### RELAXED Mode:
- **Signals per day:** 2-5 (more frequent)
- **Win rate target:** 30-40%
- **Risk/Reward:** 1:3 minimum
- **Quality:** Good (Premium/Discount only)

### Classic Mode:
- **Signals per day:** 5-10 (frequent)
- **Win rate target:** 20-30%
- **Risk/Reward:** 1:1 to 1:3
- **Quality:** Variable (backtest showed unprofitable)

---

## Troubleshooting

### No Signals Generated?

**STRICT mode is very selective.** This is normal. Check logs:

```
[BTCUSDT] SMC STRICT: BOS✗(ranging) Sweep✗ Discount✓(0.35) NoZone
```

This means:
- ❌ No BOS (market is ranging)
- ❌ No liquidity sweep
- ✅ Price in discount zone
- ❌ No entry zone found

**Solution:** Wait for better market conditions or use RELAXED mode.

### Too Many Signals?

Switch to STRICT mode:
```python
SMC_MODE = "STRICT"
```

### Want to Mix EMA+RSI with SMC?

Set `PURE_SMC = False`:
```python
PURE_SMC = False
```

This uses EMA+RSI for trend, then applies SMC filters.

---

## Recommended Settings

### For Live Trading (Conservative):
```python
ENABLE_SMC = True
SMC_MODE = "STRICT"
PURE_SMC = True
RISK_PER_TRADE = 0.01  # 1%
MAX_POSITIONS = 3
```

### For Paper Trading (Testing):
```python
ENABLE_SMC = True
SMC_MODE = "RELAXED"
PURE_SMC = False
RISK_PER_TRADE = 0.01
MAX_POSITIONS = 3
```

### For Backtesting (Comparison):
Test both modes and compare results.

---

## Next Steps

1. ✅ **Paper trade with STRICT mode** for 1-2 weeks
2. ✅ **Monitor signal quality** (win rate, RR)
3. ✅ **Compare with RELAXED mode** if needed
4. ✅ **Go live** when confident

---

## Support

- **Implementation Report:** `SMC_STRICT_MODE_IMPLEMENTATION.md`
- **Compliance Analysis:** `SMC_STRATEGY_COMPLIANCE_ANALYSIS.md`
- **Test Scripts:** `test_strict_mode.py`, `test_mode_comparison.py`
- **Video Transcript:** `iUGBUboEXzM.txt` (Márko's strategy)

---

## Summary

✅ STRICT mode = Márko's methodology (100% compliant)  
✅ RELAXED mode = More signals (less strict)  
✅ PURE_SMC = No EMA/RSI mixing  
✅ Breaker/Mitigation blocks integrated  
✅ All tests passing  

**Start with STRICT mode for highest quality signals!**
