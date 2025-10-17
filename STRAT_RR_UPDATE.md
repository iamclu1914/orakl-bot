# STRAT Bot Risk/Reward Update

## 📊 Fixed 2:1 R:R Implementation

The STRAT bot now uses a **fixed 2:1 risk/reward ratio** for all signals.

### What Changed:

#### Before:
- Targets were based on specific price levels (9am bar highs/lows, midpoints, etc.)
- R:R varied based on pattern structure
- Could be 0.5:1, 1:1, 1.5:1, or any ratio

#### After:
- All targets are calculated as **2x the risk distance**
- Every signal has exactly **2:1 R:R**
- More consistent profit targets

### How It Works:

1. **Entry**: Pattern completion price
2. **Stop**: Pattern invalidation level
3. **Risk**: Distance from entry to stop
4. **Target**: Entry ± (Risk × 2)

### Examples:

**Bullish Signal:**
- Entry: $100
- Stop: $98 (risk = $2)
- Target: $104 (2 × $2 = $4 profit)
- R:R: 2:1

**Bearish Signal:**
- Entry: $100
- Stop: $102 (risk = $2)
- Target: $96 (2 × $2 = $4 profit)
- R:R: 2:1

### Benefits:

1. **Consistent Expectations**: Always know your profit target
2. **Better Risk Management**: Fixed 2:1 ensures profitable edge
3. **Cleaner Exits**: No ambiguity about where to take profits
4. **Professional Standard**: 2:1 is a common institutional minimum

All STRAT patterns (3-2-2, 2-2, and 1-3-1) now follow this 2:1 rule!
