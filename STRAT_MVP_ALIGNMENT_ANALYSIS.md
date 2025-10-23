# STRAT MVP Alignment Analysis

**Analysis Date**: 2025-10-22
**Analysis Type**: Quality Assessment with `--ultrathink`
**Focus**: MVP Specification vs Current Implementation

---

## Executive Summary

**Overall Alignment Score**: 7.2/10

**Critical Findings**:
- ✅ **Bar classification logic**: 95% aligned
- ⚠️ **Pattern detection**: 70% aligned with critical timing differences
- ❌ **Data storage**: 0% aligned - no database persistence
- ⚠️ **Scheduling**: 60% aligned - missing CRON-based intervals
- ✅ **Timezone handling**: 100% aligned
- ❌ **Backtesting**: 0% aligned - not implemented
- ⚠️ **Deduplication**: 80% aligned - in-memory only

**Priority Recommendations**:
1. **CRITICAL**: Fix 4-hour bar alignment (MVP specifies 240-minute multiplier, current uses hour=4)
2. **CRITICAL**: Implement database persistence for pattern state
3. **HIGH**: Add bar boundary validation and DST testing
4. **HIGH**: Implement CRON-based scheduling per timeframe
5. **MEDIUM**: Add backtesting harness

---

## 1. Bar Classification Logic

### MVP Specification
```typescript
3 (Outside): B.h > Prev.h && B.l < Prev.l
2U: B.h > Prev.h && B.l >= Prev.l
2D: B.l < Prev.l && B.h <= Prev.h
1 (Inside): B.h <= Prev.h && B.l >= Prev.l
```

### Current Implementation
```python
# strat_bot.py:69-76
if curr_high > prev_high and curr_low < prev_low:
    return 3  # Outside bar
elif curr_high <= prev_high and curr_low >= prev_low:
    return 1  # Inside bar
elif curr_high > prev_high and curr_low >= prev_low:
    return 2  # 2U (Up)
elif curr_high <= prev_high and curr_low < prev_low:
    return -2  # 2D (Down)
```

### Analysis
✅ **PERFECT ALIGNMENT**

**Differences**:
- Current uses `-2` for down bars vs MVP's `"2D"` string
- Functionally identical logic

**Quality**: **9.5/10**

**Issues**: None critical

**Recommendation**: Consider using string types (`"1"`, `"2U"`, `"2D"`, `"3"`) for consistency with MVP and better debugging clarity.

---

## 2. Pattern Detection - 3-2-2 Reversal

### MVP Specification
```
Definition:
- 8:00 AM bar: 3
- 9:00 AM bar: 2 (any side)
- 10:00 AM bar: 2 opposite direction
- Alert at 10:01 AM ET
- Target: high/low of bar BEFORE 8:00 AM (7:00 AM bar)

Detector Logic:
- Align 60-min bars to ET hour starts (8:00, 9:00, 10:00)
- Confirm type[8:00]==3
- Record direction of 9:00 (2U or 2D)
- At 10:00 close, confirm 2 opposite
- Derive target from 7:00 AM bar
```

### Current Implementation
```python
# strat_bot.py:257-352
def check_322_reversal(self, bars: List[Dict], ticker: str):
    # Extract bars at 8am, 9am, 10am by searching for hour==8, 9, 10
    target_hours = {8: None, 9: None, 10: None}

    for bar in bars:
        bar_time = datetime.fromtimestamp(bar['t'] / 1000, tz=self.est)
        bar_hour = bar_time.hour
        if bar_hour in target_hours and target_hours[bar_hour] is None:
            target_hours[bar_hour] = bar

    # Step 1: 8am must be 3-bar
    bar1_type = self.detect_bar_type(bar_8am, prev_bar)
    if bar1_type != 3:
        return None

    # Step 2: 9am is a 2-bar (any direction)
    bar2_type = self.detect_bar_type(bar_9am, bar_8am)
    if abs(bar2_type) != 2:
        return None

    # Step 3: 10am must be opposite direction 2-bar
    bar3_type = self.detect_bar_type(bar_10am, bar_9am)
    if abs(bar3_type) != 2:
        return None
    if (bar2_type > 0 and bar3_type > 0) or (bar2_type < 0 and bar3_type < 0):
        return None  # Must be opposite directions

    # Target: bar BEFORE 8am (finds hour==7 or closest before 8am)
    target_bar = None
    for bar in bars:
        bar_time = datetime.fromtimestamp(bar['t'] / 1000, tz=self.est)
        if bar_time.hour == 7:
            target_bar = bar
            break
```

### Analysis
⚠️ **70% ALIGNMENT**

**What Matches**:
- ✅ Pattern sequence: 3 → 2 → 2 (opposite)
- ✅ Uses 8am, 9am, 10am bars
- ✅ Target from 7am bar
- ✅ Opposite direction check

**Critical Differences**:

#### Issue #1: Bar Extraction Method
**MVP**: "Align 60-min bars to ET hour starts"
**Current**: Searches for bars where `hour==8`, `hour==9`, `hour==10`

**Problem**: Current implementation **assumes** Polygon returns bars aligned to clock hours. This is **NOT guaranteed**.

**Example Failure**:
```python
# If Polygon returns:
# Bar 1: 07:30 - 08:29 (hour==7 when extracted at timestamp start)
# Bar 2: 08:30 - 09:29 (hour==8)
# Bar 3: 09:30 - 10:29 (hour==9)

# Current code would miss the 8am bar entirely!
```

**MVP Solution**:
```typescript
function barBoundariesET(tf: "60m", ref: Date) {
  // Returns exact [startET, endET] for 8am bar
  // e.g., 2025-10-22 08:00:00 ET to 2025-10-22 08:59:59 ET
}
```

**Recommendation**:
```python
def get_bar_for_hour(bars: List[Dict], target_hour: int, tz) -> Optional[Dict]:
    """Get bar that CONTAINS the target hour (e.g., 8:00 AM - 8:59:59 AM)"""
    for bar in bars:
        bar_start = datetime.fromtimestamp(bar['t'] / 1000, tz=tz)
        bar_end = bar_start + timedelta(minutes=60)

        target_time = bar_start.replace(hour=target_hour, minute=0, second=0)

        # Check if target hour falls within this bar's range
        if bar_start <= target_time < bar_end:
            return bar
    return None
```

#### Issue #2: Data Fetching
**MVP**: Fetch last 4-6 bars using specific date range
**Current**: Fetches from `7am to now` with 60-minute multiplier

```python
# strat_bot.py:571-577
start_time = now.replace(hour=7, minute=0) if now.hour >= 7 else now - timedelta(days=1)
df_60m = await self.data_fetcher.get_aggregates(
    ticker, 'minute', 60,
    start_time.strftime('%Y-%m-%d'),
    now.strftime('%Y-%m-%d')
)
```

**Analysis**: ✅ This is acceptable - fetches enough bars to find 7am, 8am, 9am, 10am

**Quality**: **7.0/10**

**Critical Risks**:
1. Bar alignment assumption may fail with Polygon's actual bar boundaries
2. No validation that returned bars actually align to clock hours
3. DST transitions not explicitly tested

---

## 3. Pattern Detection - 2-2 Reversal

### MVP Specification
```
Definition:
- 4:00 AM bar: 2 (directional)
- 8:00 AM bar: opens inside 4AM bar, then 2 opposite direction
- Alerts: 4:00 AM (heads-up), 8:00 AM (signal)
- Target: bar BEFORE 4:00 AM

Detector Logic:
- Align 4-hr bars to 00:00, 04:00, 08:00, 12:00, 16:00, 20:00 ET
- Use range/240/minute for 4-hour bars
- When 4:00 closes: check type==2, raise heads-up
- At 8:00 close: verify opened inside 4:00 range AND opposite 2-bar
```

### Current Implementation
```python
# strat_bot.py:354-464
def check_22_reversal(self, bars: List[Dict], ticker: str):
    # Find 4am and 8am bars
    data_4am, data_8am, data_before = None, None, None

    for bar in bars:
        bar_time = datetime.fromtimestamp(bar['t'] / 1000, tz=self.est)
        if bar_time.hour == 4:
            data_4am = bar
        elif bar_time.hour == 8:
            data_8am = bar
        elif bar_time.hour == 0:  # Bar before 4am
            data_before = bar

    # Step 1: 4am must be 2-bar
    bar1_type = self.detect_bar_type(data_4am, data_before)
    if abs(bar1_type) != 2:
        return None

    # Step 2: 8am opened inside 4am bar
    opened_inside = (data_8am['o'] <= data_4am['h'] and data_8am['o'] >= data_4am['l'])
    if not opened_inside:
        return None

    # Step 3: 8am is opposite 2-bar
    bar2_type = self.detect_bar_type(data_8am, data_4am)
    if abs(bar2_type) != 2:
        return None
    if (bar1_type > 0 and bar2_type > 0) or (bar1_type < 0 and bar2_type < 0):
        return None

# Data fetching:
# strat_bot.py:591-597
df_4h = await self.data_fetcher.get_aggregates(
    ticker, 'hour', 4,  # ⚠️ USES 'hour' WITH MULTIPLIER 4
    (now - timedelta(days=2)).strftime('%Y-%m-%d'),
    now.strftime('%Y-%m-%d')
)
```

### Analysis
❌ **CRITICAL MISALIGNMENT - 50%**

**Critical Issues**:

#### Issue #1: WRONG BAR TIMEFRAME
**MVP**: `range/240/minute` (4-hour bars using minute aggregation)
**Current**: `range/4/hour` (4-hour bars using hour aggregation)

**Problem**: Polygon's aggregation behavior may differ!

**MVP Approach**:
```
/v2/aggs/ticker/AAPL/range/240/minute/2025-10-22/2025-10-23
```

**Current Approach**:
```
/v2/aggs/ticker/AAPL/range/4/hour/2025-10-22/2025-10-23
```

**Impact**: Unknown - needs testing to confirm Polygon returns equivalent data

**Recommendation**: Use MVP's approach for consistency
```python
df_4h = await self.data_fetcher.get_aggregates(
    ticker, 'minute', 240,  # 240 minutes = 4 hours
    (now - timedelta(days=2)).strftime('%Y-%m-%d'),
    now.strftime('%Y-%m-%d')
)
```

#### Issue #2: Bar Alignment Assumption
**Same issue as 3-2-2 pattern**

Current assumes `hour==4` and `hour==8` align to 4-hour bar boundaries. This is **NOT guaranteed**.

**MVP Specifies**: Bars align to `00:00, 04:00, 08:00, 12:00, 16:00, 20:00 ET`

**Current Risk**: If Polygon returns bars like:
```
Bar 1: 02:00 - 05:59
Bar 2: 06:00 - 09:59
```

The pattern would fail to detect.

#### Issue #3: "Bar Before 4AM" Logic Fragile
```python
elif bar_time.hour == 0:  # Bar before 4am
    data_before = bar
```

**Problem**: Assumes `hour==0` (midnight) bar exists. With 4-hour bars, the "before 4am" bar is the `00:00 - 03:59` bar, which **starts at midnight** but may not have `hour==0` depending on timestamp interpretation.

**MVP Approach**: More robust
```typescript
// Find bar immediately preceding 4am bar in sequence
const prevBar = bars[bars.indexOf(bar_4am) - 1];
```

**Quality**: **5.0/10**

**Critical Risks**:
1. ❌ Wrong timeframe specification (`hour, 4` vs `minute, 240`)
2. ❌ Bar alignment assumptions
3. ❌ Fragile "bar before" logic

---

## 4. Pattern Detection - 1-3-1 Miyagi

### MVP Specification
```
Definition:
- Sequence: 1 → 3 → 1 (three bars)
- 4th bar determines trade: 2U → PUTS, 2D → CALLS
- Alerts: 8:00 AM and 8:00 PM ET
- Entry: midpoint of 3rd candle ((high3 + low3) / 2)

Detector Logic:
- Align 12-hr bars to 08:00–19:59 ET and 20:00–07:59 ET
- Use range/720/minute for 12-hour bars
- Scan rolling windows for 1-3-1 pattern
- Wait for 4th bar to close
- Entry = (bar3.h + bar3.l) / 2
```

### Current Implementation
```python
# strat_bot.py:466-542
def check_131_miyagi(self, bars: List[Dict], ticker: str):
    if len(bars) < 4:
        return None

    # Check last 4 bars for 1-3-1 pattern
    candle1, candle2, candle3, candle4 = bars[-4], bars[-3], bars[-2], bars[-1]

    # Classify each bar
    type1 = self.detect_bar_type(candle1, bars[-5] if len(bars) >= 5 else candle1)
    type2 = self.detect_bar_type(candle2, candle1)
    type3 = self.detect_bar_type(candle3, candle2)
    type4 = self.detect_bar_type(candle4, candle3)

    # Must have 1-3-1 pattern
    if not (type1 == 1 and type2 == 3 and type3 == 1):
        return None

    # Calculate midpoint of 3rd candle
    midpoint = (candle3['h'] + candle3['l']) / 2

    # 4th candle determines direction
    if type4 == 2:  # 2U → PUTS
        # Bearish reversal expected
        return {
            'type': 'PUT',
            'entry': midpoint,
            'stop': candle3['h'],
            'target': candle3['l'] - 2 * (candle3['h'] - midpoint),
            # ...
        }
    elif type4 == -2:  # 2D → CALLS
        # Bullish reversal expected
        return {
            'type': 'CALL',
            'entry': midpoint,
            'stop': candle3['l'],
            'target': candle3['h'] + 2 * (midpoint - candle3['l']),
            # ...
        }

# Data fetching:
# strat_bot.py:552-556
df_12h = await self.data_fetcher.get_aggregates(
    ticker, 'hour', 12,  # ⚠️ USES 'hour' WITH MULTIPLIER 12
    (now - timedelta(days=5)).strftime('%Y-%m-%d'),
    now.strftime('%Y-%m-%d')
)
```

### Analysis
⚠️ **75% ALIGNMENT**

**What Matches**:
- ✅ Pattern logic: 1 → 3 → 1
- ✅ 4th bar direction determines trade
- ✅ Entry at midpoint of 3rd candle
- ✅ 2:1 R/R calculation

**Critical Differences**:

#### Issue #1: Timeframe Specification
**MVP**: `range/720/minute` (12-hour using minute aggregation)
**Current**: `range/12/hour` (12-hour using hour aggregation)

**Same issue as 2-2 pattern** - needs testing to confirm equivalence.

**Recommendation**: Use `'minute', 720` for consistency.

#### Issue #2: Bar Alignment
**MVP**: "Align 12-hr bars to 08:00–19:59 ET and 20:00–07:59 ET"

**Current**: Uses `bars[-4], bars[-3], bars[-2], bars[-1]` (last 4 bars)

**Analysis**: Current approach is more flexible - doesn't assume specific clock times. This is **BETTER** than MVP for 12-hour bars since they can complete at any time.

**Quality**: **7.5/10**

**Minor Risks**:
1. ⚠️ Timeframe specification (`hour, 12` vs `minute, 720`)
2. ✅ No clock hour assumptions (good!)

---

## 5. Scheduling & Timing

### MVP Specification
```
CRON Jobs (all ET):
- 60-min bars: at :59 each hour (09:59, 10:59, ...)
- 4-hr bars: 03:59, 07:59, 11:59, 15:59, 19:59, 23:59
- 12-hr bars: 07:59, 19:59

Alert times (post-bar by 1–2 min):
- 3-2-2: 10:01 AM ET
- 2-2: 4:00 AM (heads-up), 8:00 AM (signal)
- Miyagi: 8:00 AM & 8:00 PM

Dynamic scan intervals during alert windows
```

### Current Implementation
```python
# strat_bot.py:729-743
async def get_next_scan_interval(self):
    """Calculate optimal scan interval based on current time"""
    now = datetime.now(self.est)

    # Scan more frequently during ALL alert windows (1 minute intervals)
    # 1-3-1 Miyagi: 8:00 AM and 8:00 PM
    # 2-2 Reversal: 4:00 AM and 8:00 AM
    # 3-2-2 Reversal: 10:01 AM
    alert_hours = [4, 8, 10, 20]
    if now.hour in alert_hours and now.minute <= 15:
        return 60  # 1 minute during alert windows
    elif now.hour == 19 and now.minute >= 55:  # Pre-alert window
        return 120  # 2 minutes before alert time
    else:
        return 300  # Default 5 minutes throughout the day

# Pattern-specific alert timing
# strat_bot.py:215-246
def should_alert_pattern(self, pattern_type: str, signal: Dict) -> bool:
    """Check if pattern should be alerted based on time windows"""
    now = datetime.now(self.est)
    alert_window = 5  # minutes

    if pattern_type == '1-3-1 Miyagi':
        return ((current_hour == 8 and current_minute < alert_window) or
                (current_hour == 20 and current_minute < alert_window))

    elif pattern_type == '2-2 Reversal':
        return ((current_hour == 4 and current_minute < alert_window) or
                (current_hour == 8 and current_minute < alert_window))

    elif pattern_type == '3-2-2 Reversal':
        return (current_hour == 10 and current_minute >= 1 and current_minute < (1 + alert_window))
```

### Analysis
⚠️ **60% ALIGNMENT**

**What Matches**:
- ✅ Pattern-specific alert windows
- ✅ Dynamic scan intervals during alert times
- ✅ 3-2-2 alerts at 10:01 AM
- ✅ 2-2 alerts at 4AM and 8AM
- ✅ Miyagi alerts at 8AM and 8PM

**Critical Differences**:

#### Issue #1: No CRON-Based Bar Fetching
**MVP**: Separate jobs per timeframe run at specific times (e.g., :59 each hour)
**Current**: Continuous polling with dynamic intervals

**Pros of Current Approach**:
- Simpler implementation
- More flexible
- Works with Render Background Worker

**Cons**:
- Less precise - may miss exact bar close times
- Higher API call volume during non-alert hours
- No explicit "fetch → classify → detect → alert" pipeline

**Recommendation**: Current approach is acceptable for MVP, but consider CRON-based scheduling for production:

```python
# Example CRON-based approach
@cron("59 * * * *")  # Every hour at :59
async def fetch_60min_bars():
    for symbol in watchlist:
        bars = await fetch_bars(symbol, '60m', last_n=6)
        classify_and_store(bars)
        detect_322_pattern(bars)

@cron("59 3,7,11,15,19,23 * * *")  # 4-hour intervals
async def fetch_4h_bars():
    for symbol in watchlist:
        bars = await fetch_bars(symbol, '4h', last_n=6)
        classify_and_store(bars)
        detect_22_pattern(bars)
```

#### Issue #2: No Bar Boundary Alignment
**MVP**: Explicitly computes bar boundaries with timezone utilities
**Current**: Relies on Polygon returning aligned bars

**MVP Approach**:
```typescript
export function barBoundariesET(tf: "60m"|"4h"|"12h", ref: Date) {
  // Returns exact [startET, endET] for each bar
}
```

**Recommendation**: Add bar boundary validation
```python
def validate_bar_alignment(bar: Dict, expected_hour: int, timeframe_minutes: int, tz) -> bool:
    """Verify bar aligns to expected clock hour"""
    bar_start = datetime.fromtimestamp(bar['t'] / 1000, tz=tz)
    expected_start = bar_start.replace(hour=expected_hour, minute=0, second=0, microsecond=0)

    # Allow up to 1-minute tolerance for bar start time
    time_diff = abs((bar_start - expected_start).total_seconds())
    return time_diff < 60
```

**Quality**: **6.0/10**

**Risks**:
1. No explicit bar boundary computation
2. Polling-based vs event-driven (CRON)
3. May miss exact bar close times

---

## 6. Data Model & Storage

### MVP Specification
```
Tables/Collections:
1. bars_{60|240|720}: Store raw OHLCV data per timeframe
2. strat_classified_bars: Store classified bar types
3. patterns: Store detected patterns with metadata
4. alerts: Store sent alerts with deduplication
5. runs: Job audit logs

Indexes:
- (symbol, timeframe, tStartUtc) for bars
- dedupKey unique index on alerts
```

### Current Implementation
```python
# strat_bot.py:29-34
self.detected_today = {}  # In-memory dict for deduplication
self.pattern_states = {}  # In-memory dict for pattern tracking
```

### Analysis
❌ **0% ALIGNMENT - CRITICAL GAP**

**What's Missing**:
1. ❌ No database persistence
2. ❌ No bar storage
3. ❌ No classified bar storage
4. ❌ No pattern history
5. ❌ No alert history (beyond current day)
6. ❌ No job audit logs

**Impact**:
- **Critical**: Bot restarts lose all state
- **Critical**: No historical pattern analysis
- **High**: Cannot backtest
- **High**: Cannot analyze alert effectiveness
- **Medium**: No audit trail for debugging

**Recommendation**: Implement database layer

```python
# Example schema (SQLAlchemy)
class Bar(Base):
    __tablename__ = 'bars'
    id = Column(Integer, primary_key=True)
    symbol = Column(String, index=True)
    timeframe = Column(Enum('60m', '4h', '12h'), index=True)
    t_start_utc = Column(DateTime(timezone=True), index=True)
    t_end_utc = Column(DateTime(timezone=True))
    open = Column(Float)
    high = Column(Float)
    low = Column(Float)
    close = Column(Float)
    volume = Column(Float)

    __table_args__ = (
        Index('ix_bars_symbol_tf_time', 'symbol', 'timeframe', 't_start_utc'),
    )

class ClassifiedBar(Base):
    __tablename__ = 'strat_classified_bars'
    id = Column(Integer, primary_key=True)
    bar_id = Column(Integer, ForeignKey('bars.id'))
    type = Column(Enum('1', '2U', '2D', '3'))
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)

class Pattern(Base):
    __tablename__ = 'patterns'
    id = Column(Integer, primary_key=True)
    symbol = Column(String, index=True)
    pattern = Column(Enum('3-2-2', '2-2', '1-3-1'))
    timeframe = Column(Enum('60m', '4h', '12h'))
    completion_bar_start_utc = Column(DateTime(timezone=True))
    meta = Column(JSON)  # Store pattern-specific data
    confidence = Column(Float)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)

class Alert(Base):
    __tablename__ = 'alerts'
    id = Column(Integer, primary_key=True)
    pattern_id = Column(Integer, ForeignKey('patterns.id'))
    symbol = Column(String)
    pattern = Column(String)
    timeframe = Column(String)
    alert_ts_utc = Column(DateTime(timezone=True))
    payload = Column(JSON)
    dedup_key = Column(String, unique=True, index=True)
    sent_at = Column(DateTime(timezone=True), default=datetime.utcnow)

class JobRun(Base):
    __tablename__ = 'job_runs'
    id = Column(Integer, primary_key=True)
    job_type = Column(Enum('60m', '4h', '12h'))
    started_at = Column(DateTime(timezone=True))
    ended_at = Column(DateTime(timezone=True))
    symbols_scanned = Column(Integer)
    patterns_found = Column(Integer)
    alerts_sent = Column(Integer)
    errors = Column(JSON)
    status = Column(Enum('success', 'partial', 'failed'))
```

**Quality**: **0.0/10** (not implemented)

**Priority**: **CRITICAL** - Required for production reliability

---

## 7. Confidence Scoring

### MVP Specification
```
Base 100-pt model:
- Volume vs 20-bar median (0-30): min(30, 30 * vol/medianVol)
- Trend alignment (0-30): agree with 20-EMA slope and HTF bias
- Pattern clarity (0-25): wicks not excessive; clean opposites
- Volatility regime (0-15): ATR% in "normal" band (1-3%)

Convert to percentage: confidence_pct = total_points / 100
```

### Current Implementation
```python
# strat_bot.py:79-213
async def calculate_dynamic_confidence(self, ticker: str, pattern_type: str,
                                      pattern_data: Dict, bars: List[Dict]) -> float:
    """
    Calculate dynamic confidence score based on multiple factors:
    - Volume strength (30%)
    - Trend alignment (30%)
    - Pattern clarity (25%)
    - Volatility regime (15%)
    """
    confidence = 0.0

    # 1. Volume Strength (30%)
    if len(bars) >= 20:
        recent_volumes = [b.get('v', 0) for b in bars[-20:]]
        median_vol = np.median([v for v in recent_volumes if v > 0])
        current_vol = bars[-1].get('v', 0)

        if median_vol > 0:
            vol_ratio = current_vol / median_vol
            vol_score = min(30, 30 * vol_ratio)
            confidence += vol_score

    # 2. Trend Alignment (30%)
    if len(bars) >= 20:
        closes = [b['c'] for b in bars[-20:]]
        ema20 = sum(closes) / len(closes)  # Simple average as proxy
        current_price = bars[-1]['c']

        # Check if pattern aligns with trend
        trend_up = current_price > ema20
        pattern_bullish = pattern_data.get('type') == 'CALL'

        if (trend_up and pattern_bullish) or (not trend_up and not pattern_bullish):
            confidence += 30
        else:
            confidence += 10  # Partial credit for counter-trend

    # 3. Pattern Clarity (25%)
    # Check wick sizes and bar cleanliness
    bar1 = pattern_data.get('bar1', {})
    bar2 = pattern_data.get('bar2', {})
    bar3 = pattern_data.get('bar3', {})

    clarity_score = 25

    for bar in [bar1, bar2, bar3]:
        if bar:
            body_size = abs(bar.get('c', 0) - bar.get('o', 0))
            range_size = bar.get('h', 0) - bar.get('l', 0)

            if range_size > 0:
                body_ratio = body_size / range_size
                if body_ratio < 0.5:  # Large wicks
                    clarity_score -= 5

    confidence += max(0, clarity_score)

    # 4. Volatility Regime (15%)
    if len(bars) >= 14:
        # Calculate ATR (Average True Range)
        true_ranges = []
        for i in range(1, min(14, len(bars))):
            high = bars[i].get('h', 0)
            low = bars[i].get('l', 0)
            prev_close = bars[i-1].get('c', 0)

            tr = max(
                high - low,
                abs(high - prev_close),
                abs(low - prev_close)
            )
            true_ranges.append(tr)

        if true_ranges:
            atr = sum(true_ranges) / len(true_ranges)
            current_price = bars[-1].get('c', 1)
            atr_pct = (atr / current_price) * 100 if current_price > 0 else 0

            # Ideal range: 1-3%
            if 1.0 <= atr_pct <= 3.0:
                confidence += 15
            elif 0.5 <= atr_pct < 1.0 or 3.0 < atr_pct <= 4.0:
                confidence += 10
            else:
                confidence += 5

    # Convert to percentage (0-1 scale)
    return min(1.0, confidence / 100)
```

### Analysis
✅ **95% ALIGNMENT - EXCELLENT**

**What Matches**:
- ✅ Volume vs 20-bar median (30%)
- ✅ Trend alignment with EMA (30%)
- ✅ Pattern clarity with wick analysis (25%)
- ✅ Volatility regime with ATR% (15%)
- ✅ Returns percentage (0-1 scale)

**Minor Differences**:
- Current uses simple average for EMA (should use exponential)
- ATR calculation is approximate (should use 14-period ATR)

**Quality**: **9.5/10**

**Recommendation**: Minor improvements
```python
# Use proper EMA
def calculate_ema(prices: List[float], period: int) -> float:
    multiplier = 2 / (period + 1)
    ema = prices[0]
    for price in prices[1:]:
        ema = (price - ema) * multiplier + ema
    return ema
```

---

## 8. Deduplication

### MVP Specification
```
dedupKey = hash(symbol + pattern + timeframe + tradingDateET)
Store with unique index in alerts table
Check before sending: if exists, skip
```

### Current Implementation
```python
# strat_bot.py:710-714
key = f"{ticker}_{signal['pattern']}_{datetime.now(self.est).date()}"
if key not in self.detected_today:
    self.send_alert(signal)
    signals_found.append(signal)
    self.detected_today[key] = True
```

### Analysis
⚠️ **80% ALIGNMENT**

**What Matches**:
- ✅ Dedup key format: `{symbol}_{pattern}_{date}`
- ✅ Check before sending
- ✅ Per-day deduplication

**Critical Differences**:
- ❌ In-memory only (lost on restart)
- ❌ No timeframe in dedup key
- ❌ No database persistence

**MVP Approach**:
```python
# Database-backed deduplication
def check_duplicate_alert(symbol: str, pattern: str, timeframe: str, trading_date: date) -> bool:
    dedup_key = f"{symbol}|{pattern}|{timeframe}|{trading_date.isoformat()}"

    exists = session.query(Alert).filter(Alert.dedup_key == dedup_key).first()
    return exists is not None

def create_alert(symbol: str, pattern: str, timeframe: str, payload: dict):
    trading_date = datetime.now(pytz.timezone('America/New_York')).date()
    dedup_key = f"{symbol}|{pattern}|{timeframe}|{trading_date.isoformat()}"

    if check_duplicate_alert(symbol, pattern, timeframe, trading_date):
        logger.info(f"Duplicate alert skipped: {dedup_key}")
        return

    alert = Alert(
        symbol=symbol,
        pattern=pattern,
        timeframe=timeframe,
        dedup_key=dedup_key,
        payload=payload,
        alert_ts_utc=datetime.utcnow()
    )
    session.add(alert)
    session.commit()
```

**Quality**: **8.0/10** (logic correct, needs persistence)

**Priority**: **HIGH** - Add database backing

---

## 9. Timezone Handling

### MVP Specification
```
Timezone: all logic in America/New_York
Polygon timestamps are UTC → convert consistently
Use timezone library (luxon, date-fns-tz)
Unit tests for DST transitions
```

### Current Implementation
```python
# strat_bot.py:32
self.est = pytz.timezone('America/New_York')

# Usage throughout:
bar_time = datetime.fromtimestamp(bar['t'] / 1000, tz=self.est)
now = datetime.now(self.est)
```

### Analysis
✅ **100% ALIGNMENT - PERFECT**

**What Matches**:
- ✅ Uses `America/New_York` timezone
- ✅ Consistent timezone conversion from Polygon UTC timestamps
- ✅ Uses `pytz` (Python equivalent of timezone libraries)

**Missing**:
- ⚠️ No DST transition unit tests

**Quality**: **10.0/10**

**Recommendation**: Add DST tests
```python
def test_dst_spring_forward():
    """Test pattern detection during DST spring forward (2AM → 3AM)"""
    # March 9, 2025: 2:00 AM → 3:00 AM
    bars = fetch_bars_for_date('AAPL', '2025-03-09', timeframe='60m')
    # Verify no missing 2AM hour
    hours = [datetime.fromtimestamp(b['t']/1000, tz=pytz.timezone('America/New_York')).hour
             for b in bars]
    assert 2 not in hours  # 2AM doesn't exist on this day
    assert 3 in hours

def test_dst_fall_back():
    """Test pattern detection during DST fall back (1AM occurs twice)"""
    # November 2, 2025: 2:00 AM → 1:00 AM
    bars = fetch_bars_for_date('AAPL', '2025-11-02', timeframe='60m')
    # Verify 1AM appears twice (before/after DST change)
    hours = [datetime.fromtimestamp(b['t']/1000, tz=pytz.timezone('America/New_York')).hour
             for b in bars]
    assert hours.count(1) == 2  # 1AM appears twice
```

---

## 10. Backtesting

### MVP Specification
```
For each symbol and timeframe:
1. Pull multi-week span (30-90 days)
2. Roll through bars, classify, detect
3. Emit "virtual alerts" with entry/stop/target
4. Compute stats: hit rate, avg R:R, time-to-target
5. Calibrate confidence bins
```

### Current Implementation
```python
# NOT IMPLEMENTED
```

### Analysis
❌ **0% ALIGNMENT - NOT IMPLEMENTED**

**Impact**:
- Cannot validate pattern effectiveness
- Cannot calibrate confidence scores
- Cannot optimize entry/stop/target rules
- Cannot test strategy before live trading

**Recommendation**: Implement backtesting harness

```python
class STRATBacktester:
    """Backtest STRAT patterns over historical data"""

    async def backtest_pattern(self, symbol: str, pattern: str,
                                start_date: str, end_date: str) -> Dict:
        """
        Backtest a specific pattern over date range

        Returns:
            {
                'total_signals': int,
                'winning_trades': int,
                'losing_trades': int,
                'hit_rate': float,
                'avg_rr_achieved': float,
                'avg_time_to_target_hours': float,
                'confidence_distribution': {...},
                'trades': [...]
            }
        """
        # Fetch historical bars
        bars = await self.fetch_historical_bars(symbol, pattern, start_date, end_date)

        # Classify and detect patterns
        signals = []
        for i in range(len(bars) - 4):
            signal = self.detect_pattern(bars[i:i+5], pattern)
            if signal:
                signals.append(signal)

        # Simulate trades
        trades = []
        for signal in signals:
            entry = signal['entry']
            stop = signal['stop']
            target = signal['target']

            # Find actual outcome in future bars
            outcome = self.simulate_trade(signal, bars)
            trades.append(outcome)

        # Calculate statistics
        winning = [t for t in trades if t['result'] == 'win']
        losing = [t for t in trades if t['result'] == 'loss']

        return {
            'total_signals': len(signals),
            'winning_trades': len(winning),
            'losing_trades': len(losing),
            'hit_rate': len(winning) / len(trades) if trades else 0,
            'avg_rr_achieved': np.mean([t['rr_achieved'] for t in trades]),
            'avg_time_to_target_hours': np.mean([t['hours_to_close'] for t in trades]),
            'trades': trades
        }
```

**Quality**: **0.0/10** (not implemented)

**Priority**: **MEDIUM** - Important for validation but not blocking

---

## 11. Quality & Guardrails

### MVP Specification
```
1. Inside check uses <= and >= (be consistent)
2. Open-inside check uses actual open price vs range
3. Treat doji/flat highs carefully
4. Handle missing bars (skip symbols)
```

### Current Implementation

#### ✅ Inside Check Consistency
```python
# strat_bot.py:71
elif curr_high <= prev_high and curr_low >= prev_low:
    return 1  # Inside bar
```
**Analysis**: Perfect - uses `<=` and `>=`

#### ✅ Open-Inside Check
```python
# strat_bot.py:393 (2-2 pattern)
opened_inside = (data_8am['o'] <= data_4am['h'] and data_8am['o'] >= data_4am['l'])
```
**Analysis**: Perfect - uses actual open price

#### ✅ Bar Validation
```python
# strat_bot.py:38-56
def validate_bar(self, bar: Dict) -> bool:
    """Validate a bar has all required fields and valid data"""
    required_fields = ['h', 'l', 'o', 'c']

    for field in required_fields:
        if field not in bar:
            return False
        value = bar[field]
        if value is None or value < 0:
            return False

    high, low, open_price, close = bar['h'], bar['l'], bar['o'], bar['c']

    if high < low:
        return False
    if not (low <= open_price <= high) or not (low <= close <= high):
        return False

    return True
```
**Analysis**: Excellent - validates all OHLC constraints

#### ⚠️ Doji Handling
**Issue**: No special handling for doji bars (open == close)

**Recommendation**: Add doji detection
```python
def is_doji(bar: Dict, threshold: float = 0.001) -> bool:
    """Check if bar is a doji (open ≈ close)"""
    if bar['h'] == bar['l']:
        return True  # Flat bar

    body_size = abs(bar['c'] - bar['o'])
    range_size = bar['h'] - bar['l']

    return (body_size / range_size) < threshold if range_size > 0 else True
```

#### ✅ Missing Bar Handling
```python
# strat_bot.py:267-269
valid_bars = [b for b in bars if self.validate_bar(b)]
if len(valid_bars) < 4:
    return None
```
**Analysis**: Good - skips patterns if insufficient bars

**Quality**: **9.0/10**

**Minor Gaps**:
- No explicit doji handling
- No logging for why patterns were skipped

---

## 12. REST Call Budgeting

### MVP Specification
```
1. Batch symbols in chunks (50/minute)
2. Cache latest bars in memory
3. Only refetch last 1-2 bars per run
```

### Current Implementation
```python
# No explicit batching or caching beyond scan loop
# strat_bot.py:690
for ticker in watchlist:
    try:
        signals = await self.scan_ticker(ticker)
        # ... process signals
```

### Analysis
⚠️ **30% ALIGNMENT**

**What's Missing**:
1. ❌ No symbol batching (processes all symbols every scan)
2. ❌ No in-memory bar caching
3. ❌ Refetches all bars every scan (not just last 1-2)

**Current Approach**:
```python
# Fetches ALL bars every scan
df_60m = await self.data_fetcher.get_aggregates(
    ticker, 'minute', 60,
    start_time.strftime('%Y-%m-%d'),
    now.strftime('%Y-%m-%d')
)
```

**MVP Approach**:
```python
class BarCache:
    """In-memory cache for latest bars"""

    def __init__(self):
        self.cache = {}  # {(symbol, timeframe): [bars]}

    async def get_bars(self, symbol: str, timeframe: str,
                       data_fetcher: DataFetcher, n_bars: int = 6) -> List[Dict]:
        """Get bars, using cache when possible"""
        cache_key = (symbol, timeframe)

        if cache_key in self.cache:
            cached_bars = self.cache[cache_key]

            # Only fetch the latest bar
            latest = await data_fetcher.get_aggregates(
                symbol, timeframe, multiplier,
                (datetime.now() - timedelta(hours=1)).strftime('%Y-%m-%d'),
                datetime.now().strftime('%Y-%m-%d')
            )

            if not latest.empty:
                new_bar = latest.iloc[-1].to_dict()

                # Append to cache and keep last n_bars
                cached_bars.append(new_bar)
                cached_bars = cached_bars[-n_bars:]
                self.cache[cache_key] = cached_bars

                return cached_bars

        # Cache miss - fetch full window
        bars = await data_fetcher.get_aggregates(
            symbol, timeframe, multiplier,
            (datetime.now() - timedelta(days=5)).strftime('%Y-%m-%d'),
            datetime.now().strftime('%Y-%m-%d')
        )

        if not bars.empty:
            bars_list = bars.to_dict('records')[-n_bars:]
            self.cache[cache_key] = bars_list
            return bars_list

        return []

# Symbol batching
async def scan_batch(symbols: List[str], batch_size: int = 50):
    """Scan symbols in batches to respect rate limits"""
    for i in range(0, len(symbols), batch_size):
        batch = symbols[i:i+batch_size]

        # Process batch
        tasks = [scan_ticker(symbol) for symbol in batch]
        await asyncio.gather(*tasks)

        # Rate limit: wait 1 minute between batches
        if i + batch_size < len(symbols):
            await asyncio.sleep(60)
```

**Quality**: **3.0/10**

**Impact**: High API call volume, inefficient

**Priority**: **MEDIUM** - Important for scaling but not blocking

---

## Critical Issues Summary

### 🚨 CRITICAL (Must Fix Before Production)

#### 1. Data Persistence (Priority #1)
**Issue**: No database - all state lost on restart
**Impact**: Cannot recover from crashes, no historical analysis
**Effort**: High (2-3 days)
**Recommendation**: Implement PostgreSQL with schema from Section 6

#### 2. 4-Hour Bar Timeframe Specification (Priority #2)
**Issue**: Using `hour, 4` instead of MVP's `minute, 240`
**Impact**: Unknown - may produce incorrect bars
**Effort**: Low (15 minutes)
**Recommendation**: Test both approaches, standardize to `minute, 240`

```python
# CURRENT (may be wrong)
df_4h = await self.data_fetcher.get_aggregates(ticker, 'hour', 4, ...)

# MVP (correct)
df_4h = await self.data_fetcher.get_aggregates(ticker, 'minute', 240, ...)
```

#### 3. Bar Alignment Validation (Priority #3)
**Issue**: Assumes Polygon returns clock-aligned bars
**Impact**: Patterns may fail to detect if bars misaligned
**Effort**: Medium (1 day)
**Recommendation**: Add bar boundary validation and logging

```python
def validate_bar_boundaries(bars: List[Dict], expected_hours: List[int],
                           timeframe_minutes: int, tz) -> Dict[int, Dict]:
    """Validate bars align to expected clock hours"""
    aligned_bars = {}

    for bar in bars:
        bar_start = datetime.fromtimestamp(bar['t'] / 1000, tz=tz)
        bar_hour = bar_start.hour

        if bar_hour in expected_hours:
            # Check alignment
            expected_start = bar_start.replace(minute=0, second=0, microsecond=0)
            time_diff = abs((bar_start - expected_start).total_seconds())

            if time_diff < 60:  # Within 1 minute
                aligned_bars[bar_hour] = bar
            else:
                logger.warning(f"Bar misaligned: hour={bar_hour}, "
                             f"expected={expected_start}, actual={bar_start}")

    return aligned_bars
```

### ⚠️ HIGH PRIORITY (Should Fix Soon)

#### 4. CRON-Based Scheduling
**Issue**: Polling vs event-driven bar fetching
**Impact**: Less precise, higher API usage
**Effort**: Medium (1-2 days)
**Recommendation**: Implement CRON jobs per timeframe

#### 5. "Bar Before" Logic Robustness
**Issue**: Searches for `hour==0` which may not exist
**Impact**: 2-2 pattern may fail to detect
**Effort**: Low (30 minutes)
**Recommendation**: Use sequential bar indexing

```python
# CURRENT (fragile)
for bar in bars:
    if bar_time.hour == 0:
        data_before = bar

# BETTER
bar_4am_index = bars.index(data_4am)
if bar_4am_index > 0:
    data_before = bars[bar_4am_index - 1]
```

#### 6. DST Testing
**Issue**: No unit tests for DST transitions
**Impact**: Patterns may break during DST changes
**Effort**: Low (1 day)
**Recommendation**: Add DST test cases (see Section 9)

### 📋 MEDIUM PRIORITY (Nice to Have)

#### 7. REST Call Optimization
**Issue**: No batching or caching
**Impact**: High API usage
**Effort**: Medium (1-2 days)
**Recommendation**: Implement bar caching and symbol batching

#### 8. Backtesting Harness
**Issue**: Cannot validate patterns before live trading
**Impact**: Unknown strategy effectiveness
**Effort**: High (3-5 days)
**Recommendation**: Build backtesting system (see Section 10)

#### 9. Doji Handling
**Issue**: No special treatment for doji bars
**Impact**: Minor - may affect clarity scoring
**Effort**: Low (1 hour)
**Recommendation**: Add doji detection

---

## Alignment Matrix

| Component | MVP | Current | Alignment | Priority | Effort |
|-----------|-----|---------|-----------|----------|--------|
| Bar Classification | String types | Integer types | 95% | Low | 1h |
| 3-2-2 Pattern Logic | Clock-aligned | Hour search | 70% | **CRITICAL** | 1d |
| 2-2 Pattern Logic | `minute, 240` | `hour, 4` | 50% | **CRITICAL** | 15m |
| 1-3-1 Pattern Logic | Clock-aligned | Rolling window | 75% | Medium | 4h |
| Timezone Handling | America/New_York | America/New_York | 100% | ✅ | 0 |
| Confidence Scoring | 100-pt model | 100-pt model | 95% | Low | 2h |
| Deduplication | DB-backed | In-memory | 80% | **HIGH** | 1d |
| Data Persistence | PostgreSQL | None | 0% | **CRITICAL** | 3d |
| Scheduling | CRON | Polling | 60% | **HIGH** | 2d |
| Bar Caching | Redis/memory | None | 0% | Medium | 2d |
| Backtesting | Full harness | None | 0% | Medium | 5d |
| DST Testing | Unit tests | None | 0% | **HIGH** | 1d |

---

## Overall Assessment

### ✅ What's Working Well

1. **Bar classification logic** - Mathematically correct
2. **Timezone handling** - Proper use of pytz
3. **Confidence scoring** - Solid 4-factor model
4. **Pattern-specific alert timing** - Correct windows
5. **Input validation** - Good bar validation

### ⚠️ Critical Risks

1. **No database** - All state lost on restart
2. **Bar alignment assumptions** - May break with Polygon's actual data
3. **Timeframe specification** - `hour, 4` vs `minute, 240` untested
4. **No DST tests** - May break during timezone changes
5. **Fragile "bar before" logic** - Assumes `hour==0` exists

### 📊 Quality Scores

- **Code Quality**: 7.5/10 (well-structured, good validation)
- **MVP Alignment**: 7.2/10 (core logic solid, infrastructure gaps)
- **Production Readiness**: 4.0/10 (critical persistence and testing gaps)
- **Correctness**: 8.0/10 (pattern logic correct, timing assumptions risky)

---

## Recommended Implementation Plan

### Phase 1: Critical Fixes (Week 1)
1. ✅ Fix 4-hour timeframe: `'minute', 240`
2. ✅ Add bar alignment validation and logging
3. ✅ Implement PostgreSQL database with schema
4. ✅ Add database-backed deduplication
5. ✅ Fix "bar before" logic to use sequential indexing

### Phase 2: High Priority (Week 2)
1. ✅ Implement CRON-based scheduling per timeframe
2. ✅ Add DST unit tests (spring forward, fall back)
3. ✅ Add bar boundary computation utilities
4. ✅ Implement job audit logging

### Phase 3: Optimization (Week 3)
1. ✅ Add in-memory bar caching
2. ✅ Implement symbol batching (50/minute)
3. ✅ Optimize confidence scoring (proper EMA, ATR)
4. ✅ Add pattern clarity logging

### Phase 4: Validation (Week 4)
1. ✅ Build backtesting harness
2. ✅ Run 90-day backtest on S&P 500
3. ✅ Calibrate confidence bins
4. ✅ Analyze hit rates and R:R

---

## Conclusion

**The MVP specification is SOLID and CORRECT.** The current implementation has **good core logic** but **critical infrastructure gaps**.

**Top 3 Actions**:
1. **Implement database persistence** (PostgreSQL with schema)
2. **Validate bar alignment** (add logging, fix timeframe specs)
3. **Add DST tests** (ensure timezone handling works year-round)

**Overall Verdict**: **Current implementation is ~70% aligned with MVP**, with critical gaps in persistence, testing, and bar alignment validation. Core pattern detection logic is sound but relies on unvalidated assumptions about Polygon's bar boundaries.

**Production Readiness**: **NOT READY** - requires database, testing, and alignment validation before live trading.
