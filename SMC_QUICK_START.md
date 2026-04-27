# SMC Strategy Quick Start Guide

## What is SMC?

Smart Money Concept (SMC) is an institutional trading methodology that focuses on:
- **Structure**: Market trend (BOS/CHoCH)
- **Liquidity**: Equal highs/lows sweeps
- **Order Blocks**: Institutional accumulation zones
- **Fair Value Gaps**: Price inefficiencies
- **Premium/Discount**: Optimal entry zones

## Quick Start

### 1. Enable SMC Strategy

Edit `config.py`:
```python
ENABLE_SMC = True  # Use SMC strategy
```

### 2. Run the Bot

```bash
python bot.py
```

The bot will:
- Scan 7 symbols every 15 minutes
- Apply SMC filters to each signal
- Only enter trades in correct Premium/Discount zones
- Send Telegram notifications for signals

### 3. Test SMC Detectors

```bash
# Test single symbol
python test_smc_integration.py --symbol BTCUSDT --detectors-only

# Test all symbols
python test_smc_integration.py --all --detectors-only
```

### 4. Compare Classic vs SMC

```bash
# Compare strategies on BTCUSDT
python test_smc_integration.py --symbol BTCUSDT

# Compare on all symbols
python test_smc_integration.py --all
```

## SMC Filter Pipeline

The bot applies 4 SMC filters in sequence:

### 1. Structure Break (BOS) - OPTIONAL ℹ️
- Detects market trend (bullish/bearish/ranging)
- Logs trend but doesn't reject signals
- Helps with signal quality

### 2. Liquidity Sweep - OPTIONAL ℹ️
- Detects equal highs/lows sweeps
- Logs sweeps but doesn't reject signals
- Increases signal priority when present

### 3. Premium/Discount Zone - **REQUIRED** ⚠️
- **Long ONLY in discount zone (<0.5)**
- **Short ONLY in premium zone (>0.5)**
- **REJECTS signals in wrong zone**

### 4. Entry Zone (OB or FVG) - OPTIONAL ℹ️
- Checks if price is in Order Block or FVG
- Logs entry zone but doesn't reject
- Increases signal quality when present

## Configuration Parameters

All SMC parameters are in `config.py`:

```python
# Enable/disable SMC
ENABLE_SMC = True

# Structure detection
SWING_LOOKBACK = 50              # candles for swing detection
LIQUIDITY_TOLERANCE = 0.002      # 0.2% for equal highs/lows
LIQUIDITY_SWEEP_LOOKBACK = 10    # candles to check for sweeps

# Fair Value Gap
FVG_MIN_SIZE_ATR = 0.3           # minimum FVG size (ATR units)
FVG_EXPIRY_CANDLES = 100         # candles before FVG expires

# Order Block
OB_IMPULSE_THRESHOLD = 2.0       # minimum ATR for impulse
OB_EXPIRY_CANDLES = 100          # candles before OB expires

# Premium/Discount
PREMIUM_DISCOUNT_THRESHOLD = 0.5  # 0.5 = middle of range
```

## Understanding SMC Logs

When SMC is enabled, you'll see logs like:

```
[BTCUSDT] SMC: BOS✗(ranging) Sweep✗ Discount✓(0.35) OB✓ (45ms)
```

This means:
- ❌ No BOS (market is ranging)
- ❌ No liquidity sweep detected
- ✅ Price in discount zone (0.35 = 35% of range)
- ✅ Price in Order Block
- ⏱️ Analysis took 45ms

## Signal Example

```
🚀 SIGNAL  BTCUSDT  LONG 🟢
Entry:      73500.00
Take Profit:75200.00  (+2.31%)
Stop Loss:  72800.00  (-0.95%)
RR:         1:2.43
Qty:        0.015
ATR(4h):    700.00
Reason:     SMC Buy | BOS✓ Sweep✓ Discount✓(0.35) OB✓ | ATR=700.00
```

## Switching to Classic Strategy

To use the original EMA+RSI+ATR strategy:

1. Edit `config.py`:
```python
ENABLE_SMC = False
```

2. Restart the bot:
```bash
python bot.py
```

The bot will use classic strategy without any SMC filters.

## Troubleshooting

### No Signals Generated

This is normal! SMC strategy is more selective:
- Requires correct Premium/Discount zone
- Waits for optimal market structure
- Filters out low-quality setups

Classic strategy might generate 5-10 signals/day, SMC might generate 1-3 signals/day with higher quality.

### "Price not in discount zone"

This means:
- Bot wanted to go LONG
- But price is in premium zone (>0.5)
- Signal rejected (correct behavior)

Wait for price to move into discount zone (<0.5) for long entries.

### "Price not in premium zone"

This means:
- Bot wanted to go SHORT
- But price is in discount zone (<0.5)
- Signal rejected (correct behavior)

Wait for price to move into premium zone (>0.5) for short entries.

## Performance

- **Analysis Time**: <100ms per symbol
- **Total Time (7 symbols)**: <5 minutes
- **Memory Usage**: Minimal
- **API Calls**: No additional calls

## Support

For issues or questions:
1. Check logs in `logs/rocketbot.log`
2. Run test script: `python test_smc_integration.py --symbol BTCUSDT`
3. Verify configuration in `config.py`

## Advanced Usage

### Strict SMC Mode (Future Enhancement)

To require ALL SMC filters (not just Premium/Discount):

```python
# In config.py (future feature)
ENABLE_STRICT_SMC = True  # Requires BOS + Sweep + Zone + Entry
```

### Custom Thresholds

Adjust thresholds based on your risk tolerance:

```python
# More aggressive (more signals)
PREMIUM_DISCOUNT_THRESHOLD = 0.4  # Long at 40%, Short at 60%
FVG_MIN_SIZE_ATR = 0.2            # Smaller FVGs

# More conservative (fewer signals)
PREMIUM_DISCOUNT_THRESHOLD = 0.5  # Long at 50%, Short at 50%
FVG_MIN_SIZE_ATR = 0.5            # Larger FVGs only
```

---

**Happy Trading! 🚀**
