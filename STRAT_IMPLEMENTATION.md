# STRAT Pattern Implementation - Battle-Tested

## Overview

This bot implements **battle-tested STRAT pattern detection** using Polygon.io REST API with proper timezone alignment for Eastern Time (ET) boundaries.

## Patterns Implemented

### 1. 🎯 1-3-1 Miyagi Pattern (12-Hour Timeframe)

**Timeframe**: 12-hour bars aligned to **08:00 and 20:00 ET**

**Pattern**: Inside → Outside → Inside (Compression-Expansion-Compression)

**API Approach**:
1. **Primary**: Direct 720-minute aggregates
   ```
   /v2/aggs/ticker/{SYMBOL}/range/720/minute/{FROM}/{TO}
   ```
2. **Fallback**: Compose from 60-minute bars if alignment is off

**Detection Logic**:
- Bar 1: Inside bar (H ≤ prevH AND L ≥ prevL)
- Bar 2: Outside bar (H > prevH AND L < prevL)  
- Bar 3: Inside bar (H ≤ prevH AND L ≥ prevL)
- Entry: Midpoint of Bar 3
- Direction: Wait for 4th bar (2U = PUTS bias, 2D = CALLS bias)

**Alert Times**: Within 30 minutes after 08:00 or 20:00 ET

### 2. ↩️ 2-2 Reversal (4-Hour Timeframe)

**Timeframe**: 4-hour bars at **04:00 and 08:00 ET**

**Pattern**: Directional → Opposite Direction

**API Approach**:
1. **Primary**: Direct 240-minute aggregates
   ```
   /v2/aggs/ticker/{SYMBOL}/range/240/minute/{FROM}/{TO}
   ```
2. **Fallback**: Compose from 60-minute bars

**Detection Logic**:
- 4:00 AM → 2-bar forms (either 2D or 2U)
- 8:00 AM → Opposite direction 2-bar
  - If 4am was 2D → 8am should be 2U
  - If 4am was 2U → 8am should be 2D
- **Requirement**: 8am bar must open inside the 4am bar's range

**Alert Times**: Within 30 minutes after 08:00 AM ET

### 3. 🔄 3-2-2 Reversal (60-Minute Timeframe)

**Timeframe**: 60-minute bars at **08:00, 09:00, and 10:00 AM ET**

**Pattern**: Outside → Directional → Opposite Direction

**API Approach**:
- Direct 60-minute bars
  ```
  /v2/aggs/ticker/{SYMBOL}/range/60/minute/{FROM}/{TO}
  ```

**Detection Logic**:
- 8:00 AM → 3-bar (outside bar)
- 9:00 AM → 2-bar (any direction)
- 10:00 AM → 2-bar opposite direction
  - If 9am was 2U → 10am should be 2D
  - If 9am was 2D → 10am should be 2U

**Alert Times**: Within 30 minutes after 10:00 AM ET

## File Structure

```
src/
├── bots/
│   └── strat_bot.py          # Main STRAT bot (updated with all patterns)
└── utils/
    ├── strat_12h.py          # 12-hour pattern detector
    ├── strat_12h_composer.py # 12-hour bar composer (ET alignment)
    ├── strat_4h.py           # 4-hour pattern detector
    └── strat_60m.py          # 60-minute pattern detector
```

## STRAT Type Classification

**Strict Rules** (used across all timeframes):

- **"3"** (Outside): H > prevH **AND** L < prevL
- **"2U"** (Up): H > prevH **AND** L ≥ prevL
- **"2D"** (Down): L < prevL **AND** H ≤ prevH
- **"1"** (Inside): H ≤ prevH **AND** L ≥ prevL

## Best Practice Approach

Following the battle-tested methodology:

### For each timeframe:
1. **Try direct aggregates first** (most efficient, single API call)
2. **Verify alignment** to ET boundaries
3. **Fall back to composition** from smaller bars if needed

### API Parameters:
```python
params = {
    'adjusted': 'true',    # Split-adjusted data
    'sort': 'asc',         # Chronological order
    'limit': '50000',      # Ensure all bars
    'apiKey': api_key
}
```

## Scanning Schedule

The bot scans every 5 minutes but only alerts during specific windows:

- **10:00-10:30 AM ET** → 3-2-2 Reversals
- **08:00-08:30 AM ET** → 2-2 Reversals & 1-3-1 Miyagi  
- **20:00-20:30 PM ET** → 1-3-1 Miyagi

## Discord Alerts

Each pattern type has custom embeds with:
- ✅ Pattern type and emoji
- ✅ Completion timestamp (ET timezone)
- ✅ Entry price
- ✅ Timeframe
- ✅ Bias/Direction
- ✅ Confidence score
- ✅ Pattern explanation
- ✅ Disclaimer footer

## Testing Results

**Verified on real market data:**
- ✅ SPY: 2× 1-3-1 Miyagi patterns
- ✅ AAPL: 1× 2-2 Reversal
- ✅ NVDA: 1× 3-2-2 Reversal + 2× 1-3-1 Miyagi

All timestamps properly aligned to ET boundaries (08:00, 20:00, 04:00, 09:00, 10:00).

## Key Features

1. **Proper ET Alignment**: All bars align to specified ET boundaries
2. **Best Practice API Usage**: Direct aggregates with composition fallback
3. **Timestamp Handling**: Robust pandas Timestamp to int milliseconds conversion
4. **Multi-Timeframe**: Three different timeframes (12h, 4h, 60m)
5. **Real-Time Detection**: Scans at appropriate times after bar close
6. **Deduplication**: Prevents duplicate alerts within 24 hours
7. **Database Ready**: Optional persistence for pattern history

## Deployment

Deployed to Render with auto-deployment on git push.

**Status**: ✅ Live and monitoring 403 stocks 24/7

