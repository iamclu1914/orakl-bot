# ORAKL Bot PRD Implementation Plan
## Adapted to Existing Codebase Architecture

This plan implements the PRD enhancements while preserving your current architecture (BaseAutoBot, bot_manager.py, etc.)

---

## 🎯 Implementation Priority & Timeline

### **Phase 1: Critical Wins (Days 1-2)** ✅ IMMEDIATE IMPACT

#### 1.1 Breakouts Bot - Market-Wide Scanning
**Current**: 109 stocks → **Target**: 5,000+ stocks
**Expected Impact**: 0-1 signals/day → 20-40 signals/day

**File**: `src/bots/breakouts_bot.py`

**Changes Required**:
```python
# BEFORE (line 36):
for symbol in self.watchlist:

# AFTER:
# Market-wide scan using SmartWatchlistManager (already implemented!)
# Just need to enable market mode
```

**Implementation**:
1. Already done! Watchlist manager fetches 5,000+ tickers
2. Just need to update `WATCHLIST_MODE=ALL_MARKET` in environment

**Estimated Time**: ✅ ALREADY COMPLETE

---

#### 1.2 Bullseye Bot - Relative Volume & Smart Money
**Current**: Absolute thresholds → **Target**: Relative + directional conviction
**Expected Impact**: 56% → 68-72% win rate

**File**: `src/bots/bullseye_bot.py`

**Method Additions**:
```python
async def calculate_relative_volume(self, symbol: str, current_volume: int) -> float:
    """Calculate volume vs 20-day baseline"""
    bars_20d = await self.fetcher.get_aggregates(
        symbol, 'day', 1,
        (datetime.now() - timedelta(days=25)).strftime('%Y-%m-%d'),
        datetime.now().strftime('%Y-%m-%d')
    )

    if bars_20d.empty:
        return 1.0

    baseline_avg = bars_20d['volume'].mean()
    return current_volume / baseline_avg if baseline_avg > 0 else 1.0

def calculate_directional_conviction(self, call_premium: float, put_premium: float) -> Dict:
    """Require 80/20 directional split"""
    total = call_premium + put_premium
    if total == 0:
        return {'conviction': 0, 'direction': 'NEUTRAL', 'passes': False}

    call_pct = call_premium / total
    put_pct = put_premium / total

    if call_pct >= 0.80:
        return {'conviction': call_pct, 'direction': 'BULLISH', 'passes': True}
    elif put_pct >= 0.80:
        return {'conviction': put_pct, 'direction': 'BEARISH', 'passes': True}
    else:
        return {'conviction': max(call_pct, put_pct), 'direction': 'MIXED', 'passes': False}

def filter_smart_money(self, trades_df: pd.DataFrame) -> pd.DataFrame:
    """Filter for $10k+ average trades"""
    trades_df['premium'] = trades_df['price'] * trades_df['size'] * 100
    return trades_df[trades_df['premium'] >= 10_000]
```

**Update scan() method** (line 46):
```python
async def _scan_intraday_momentum(self, symbol: str) -> List[Dict]:
    """Enhanced with relative volume and smart money filtering"""

    # Get options trades
    trades = await self.fetcher.get_options_trades(symbol)
    if trades.empty:
        return []

    # Calculate relative volume
    current_volume = trades['volume'].sum()
    volume_ratio = await self.calculate_relative_volume(symbol, current_volume)

    # Require 3x minimum
    if volume_ratio < 3.0:
        return []

    # Filter smart money only
    smart_trades = self.filter_smart_money(trades)
    if smart_trades.empty:
        return []

    # Calculate directional conviction
    call_premium = smart_trades[smart_trades['type'] == 'CALL']['premium'].sum()
    put_premium = smart_trades[smart_trades['type'] == 'PUT']['premium'].sum()

    conviction = self.calculate_directional_conviction(call_premium, put_premium)

    # Require 80/20 split
    if not conviction['passes']:
        return []

    # Rest of existing logic with new filters applied...
```

**Estimated Time**: 2-3 hours

---

### **Phase 2: Pattern Enhancements (Days 3-5)** 📈 QUALITY + DIVERSITY

#### 2.1 STRAT Bot - Add Miyagi, 3-2-2, 2-2 Patterns
**File**: `src/bots/strat_bot.py`

**Current scan() structure** (line 24):
```python
async def scan_and_post(self):
    """Scan for STRAT patterns"""
    # Currently only does basic pattern detection
```

**New scan_and_post() enhancement**:
```python
async def scan_and_post(self):
    """Enhanced multi-pattern STRAT detection"""
    logger.info(f"{self.name} scanning for patterns")

    is_open = await self.data_fetcher.is_market_open()
    if not is_open:
        return

    et_tz = pytz.timezone('US/Eastern')
    now_et = datetime.now(et_tz)

    for symbol in self.watchlist:
        try:
            signals = []

            # Regular STRAT patterns (always)
            regular = await self._scan_regular_strat(symbol)
            if regular:
                signals.append(regular)

            # Miyagi (only at 3:45 PM/AM ET)
            if (now_et.hour == 15 and now_et.minute == 45) or \
               (now_et.hour == 3 and now_et.minute == 45):
                miyagi = await self._scan_miyagi_pattern(symbol)
                if miyagi:
                    signals.append(miyagi)

            # 3-2-2 Reversal (8-11 AM ET, at :05 past hour)
            if now_et.hour in [8, 9, 10, 11] and now_et.minute == 5:
                reversal_322 = await self._scan_322_reversal(symbol)
                if reversal_322:
                    signals.append(reversal_322)

            # 2-2 Reversal (8-9:30 AM ET, at :15 and :45)
            if (now_et.hour == 8 or (now_et.hour == 9 and now_et.minute <= 30)) and \
               now_et.minute in [15, 45]:
                reversal_22 = await self._scan_22_reversal(symbol)
                if reversal_22:
                    signals.append(reversal_22)

            # Post highest confidence signal
            if signals:
                best_signal = max(signals, key=lambda x: x.get('confidence_score', 0))
                await self._post_signal(best_signal)

        except Exception as e:
            logger.error(f"{self.name} error scanning {symbol}: {e}")
```

**Add new pattern methods** (append to file):
```python
async def _scan_miyagi_pattern(self, symbol: str) -> Optional[Dict]:
    """12H Miyagi (1-3-1 with 50% retracement)"""
    bars_12h = await self.data_fetcher.get_aggregates(
        symbol, 'hour', 12,
        (datetime.now() - timedelta(days=3)).strftime('%Y-%m-%d'),
        datetime.now().strftime('%Y-%m-%d')
    )

    if len(bars_12h) < 4:
        return None

    # Identify last 4 bars
    patterns = []
    for i in range(-4, 0):
        bar_type = self._identify_bar_type(
            bars_12h.iloc[i],
            bars_12h.iloc[i-1] if i > -4 else None
        )
        patterns.append(bar_type)

    # Check for 1-3-1 sequence
    if patterns[0] == '1' and patterns[1] == '3' and patterns[2] == '1':
        # Calculate 50% retracement of 3rd bar
        candle_3 = bars_12h.iloc[-2]
        trigger_level = (candle_3['high'] + candle_3['low']) / 2

        # Check 4th candle position
        current = bars_12h.iloc[-1]
        fourth_type = patterns[3]

        if fourth_type in ['2U', '2D']:
            if fourth_type == '2U' and current['close'] > trigger_level:
                direction = 'PUT'  # Reversal down
            elif fourth_type == '2D' and current['close'] < trigger_level:
                direction = 'CALL'  # Reversal up
            else:
                return None

            return {
                'ticker': symbol,
                'pattern_type': 'MIYAGI_12H',
                'direction': direction,
                'trigger_level': trigger_level,
                'current_price': current['close'],
                'fourth_candle': fourth_type,
                'miyagi_score': 75,
                'confidence_score': 0.75
            }

    return None

async def _scan_322_reversal(self, symbol: str) -> Optional[Dict]:
    """60M 3-2-2 Reversal (first 3 hours)"""
    et_tz = pytz.timezone('US/Eastern')
    now_et = datetime.now(et_tz)

    # Get 60-minute bars
    bars_60m = await self.data_fetcher.get_aggregates(
        symbol, 'minute', 60,
        now_et.replace(hour=8, minute=0).strftime('%Y-%m-%d'),
        now_et.strftime('%Y-%m-%d')
    )

    if len(bars_60m) < 3:
        return None

    # Extract 8AM, 9AM, 10AM bars
    bars_by_hour = {}
    for _, bar in bars_60m.iterrows():
        bar_hour = pd.to_datetime(bar['timestamp']).tz_localize('UTC').tz_convert(et_tz).hour
        if bar_hour in [8, 9, 10]:
            bars_by_hour[bar_hour] = bar

    if not all(h in bars_by_hour for h in [8, 9, 10]):
        return None

    # Identify patterns
    type_8 = self._identify_bar_type(bars_by_hour[8], None)
    type_9 = self._identify_bar_type(bars_by_hour[9], bars_by_hour[8])
    type_10 = self._identify_bar_type(bars_by_hour[10], bars_by_hour[9])

    # Valid 3-2-2: Outside (3) → Directional (2U/2D) → Opposite (2D/2U)
    if type_8 == '3' and type_9 in ['2U', '2D']:
        if (type_9 == '2U' and type_10 == '2D') or (type_9 == '2D' and type_10 == '2U'):
            direction = 'CALL' if type_10 == '2U' else 'PUT'

            # Set levels
            if direction == 'CALL':
                entry = bars_by_hour[9]['high']
                target = bars_by_hour[8]['high']
                stop = bars_by_hour[10]['low']
            else:
                entry = bars_by_hour[9]['low']
                target = bars_by_hour[8]['low']
                stop = bars_by_hour[10]['high']

            rr_ratio = abs(target - entry) / abs(entry - stop) if abs(entry - stop) > 0 else 0

            return {
                'ticker': symbol,
                'pattern_type': '3-2-2_REVERSAL',
                'direction': direction,
                'entry_price': entry,
                'target': target,
                'stop': stop,
                'risk_reward': rr_ratio,
                'reversal_score': 70,
                'confidence_score': 0.70,
                'bars': f"{type_8}-{type_9}-{type_10}"
            }

    return None

async def _scan_22_reversal(self, symbol: str) -> Optional[Dict]:
    """4H 2-2 Reversal Retrigger (pre-market setup)"""
    et_tz = pytz.timezone('US/Eastern')

    # Get 4-hour bars
    bars_4h = await self.data_fetcher.get_aggregates(
        symbol, 'hour', 4,
        (datetime.now() - timedelta(days=2)).strftime('%Y-%m-%d'),
        datetime.now().strftime('%Y-%m-%d')
    )

    if len(bars_4h) < 2:
        return None

    # Find 4AM and 8AM bars
    bar_4am = None
    bar_8am = None

    for _, bar in bars_4h.iterrows():
        bar_hour = pd.to_datetime(bar['timestamp']).tz_localize('UTC').tz_convert(et_tz).hour
        if bar_hour == 4:
            bar_4am = bar
        elif bar_hour == 8:
            bar_8am = bar

    if bar_4am is None or bar_8am is None:
        return None

    # Check if 4AM is 2U or 2D
    type_4am = self._identify_bar_type(bar_4am, None)

    if type_4am in ['2U', '2D']:
        # Check if 8AM opens INSIDE 4AM range
        if bar_8am['open'] <= bar_4am['high'] and bar_8am['open'] >= bar_4am['low']:
            if type_4am == '2D':
                direction = 'CALL'
                trigger = bar_4am['high']
                target = trigger * 1.02
                stop = bar_4am['low']
            else:
                direction = 'PUT'
                trigger = bar_4am['low']
                target = trigger * 0.98
                stop = bar_4am['high']

            return {
                'ticker': symbol,
                'pattern_type': '2-2_REVERSAL',
                'direction': direction,
                'trigger_price': trigger,
                'target': target,
                'stop': stop,
                'reversal_score': 68,
                'confidence_score': 0.68,
                'setup': f"{type_4am} reversal"
            }

    return None

def _identify_bar_type(self, current_bar: pd.Series, prev_bar: Optional[pd.Series]) -> str:
    """Identify STRAT bar type (1, 2U, 2D, 3)"""
    if prev_bar is None:
        return 'UNKNOWN'

    # Outside bar (3)
    if current_bar['high'] > prev_bar['high'] and current_bar['low'] < prev_bar['low']:
        return '3'

    # Inside bar (1)
    elif current_bar['high'] <= prev_bar['high'] and current_bar['low'] >= prev_bar['low']:
        return '1'

    # Up bar (2U)
    elif current_bar['high'] > prev_bar['high'] and current_bar['low'] >= prev_bar['low']:
        return '2U'

    # Down bar (2D)
    elif current_bar['high'] <= prev_bar['high'] and current_bar['low'] < prev_bar['low']:
        return '2D'

    return 'UNKNOWN'
```

**Estimated Time**: 4-6 hours

---

#### 2.2 Golden Sweeps Bot - Multi-Exchange + Urgency
**File**: `src/bots/golden_sweeps_bot.py`

**Add methods** (append after existing methods):
```python
def detect_multi_exchange(self, trades_df: pd.DataFrame) -> int:
    """Count unique exchanges hit"""
    if 'exchange' not in trades_df.columns:
        return 1
    return trades_df['exchange'].nunique()

def calculate_urgency(self, trades_df: pd.DataFrame) -> Dict:
    """Calculate execution urgency"""
    time_span = (trades_df['timestamp'].max() - trades_df['timestamp'].min()).total_seconds()
    total_contracts = trades_df['volume'].sum()

    contracts_per_sec = total_contracts / max(time_span, 1)

    if contracts_per_sec >= 200:
        return {'urgency': 'VERY HIGH', 'score': 1.0, 'cps': contracts_per_sec}
    elif contracts_per_sec >= 100:
        return {'urgency': 'HIGH', 'score': 0.8, 'cps': contracts_per_sec}
    elif contracts_per_sec >= 50:
        return {'urgency': 'MEDIUM', 'score': 0.6, 'cps': contracts_per_sec}
    else:
        return {'urgency': 'LOW', 'score': 0.4, 'cps': contracts_per_sec}

def is_smart_strike(self, strike: float, current_price: float, option_type: str) -> bool:
    """Filter lottery tickets (>5% OTM)"""
    distance_pct = abs((strike - current_price) / current_price) * 100

    if option_type == 'CALL' and strike > current_price and distance_pct > 5:
        return False
    elif option_type == 'PUT' and strike < current_price and distance_pct > 5:
        return False

    return True
```

**Update _scan_golden_sweeps()** (line 129):
```python
async def _scan_golden_sweeps(self, symbol: str) -> List[Dict]:
    """Enhanced with multi-exchange, urgency, and smart strike filtering"""
    sweeps = []

    # Get trades
    trades = await self.fetcher.get_options_trades(symbol)
    if trades.empty:
        return sweeps

    # Filter recent
    recent = trades[trades['timestamp'] > datetime.now() - timedelta(minutes=15)]

    for (contract, opt_type, strike, expiration), group in recent.groupby(
        ['contract', 'type', 'strike', 'expiration']
    ):
        total_premium = group['premium'].sum()

        # $1M minimum
        if total_premium < self.MIN_GOLDEN_PREMIUM:
            continue

        # Multi-exchange check (3+ exchanges)
        exchanges_hit = self.detect_multi_exchange(group)
        if exchanges_hit < 3:
            continue

        # Urgency check
        urgency_data = self.calculate_urgency(group)
        if urgency_data['urgency'] == 'LOW':
            continue

        # Smart strike check
        current_price = await self.fetcher.get_stock_price(symbol)
        if not self.is_smart_strike(strike, current_price, opt_type):
            continue

        # All checks passed
        sweep = {
            'ticker': symbol,
            'type': opt_type,
            'strike': strike,
            'expiration': expiration,
            'premium': total_premium,
            'volume': group['volume'].sum(),
            'exchanges_hit': exchanges_hit,
            'urgency': urgency_data['urgency'],
            'contracts_per_second': urgency_data['cps'],
            'golden_score': 85,  # Boosted for passing all filters
            # ... rest of existing fields
        }
        sweeps.append(sweep)

    return sweeps
```

**Estimated Time**: 2-3 hours

---

### **Phase 3: Remaining Bots (Days 6-10)** 🔧 COMPLETENESS

#### 3.1 Scalps Bot - R/R Ratio Filter
#### 3.2 Unusual Activity Bot - Multi-Factor Scoring
#### 3.3 Sweeps Bot - Relative Size
#### 3.4 Darkpool Bot - Clustering
#### 3.5 ORAKL Flow Bot - Smart Money Patterns

---

## 📊 Expected Results After Full Implementation

| Bot | Current Win Rate | Target Win Rate | Current Signals/Day | Target Signals/Day |
|-----|------------------|-----------------|---------------------|-------------------|
| Breakouts | 52% | 65-70% | 0-1 | 20-40 |
| Bullseye | 56% | 68-72% | 1-3 | 4-8 |
| Golden Sweeps | 76% | 78-82% | 0-2 | 3-6 |
| STRAT | 60% | 70-75% | 2-5 | 5-10 |
| **TOTAL** | **~56%** | **~70%** | **5-15** | **35-65** |

---

## 🚀 Recommended Execution Order

1. ✅ **Watchlist Expansion** (DONE - already implemented!)
2. **Bullseye Bot** (2-3 hours) - Quality improvement
3. **STRAT Bot** (4-6 hours) - Pattern diversity
4. **Golden Sweeps Bot** (2-3 hours) - Higher conviction
5. Remaining bots (Phase 3)

**Total Phase 1-2 Time**: 8-12 hours of focused work
**Expected Impact**: 5-15 → 35-50 signals/day at 68-72% win rate

---

Would you like me to:
1. **Start implementing Phase 1 (Bullseye Bot)** right now?
2. **Create detailed code for all remaining bots** (Scalps, Unusual Activity, etc.)?
3. **Test the STRAT bot enhancements** on historical data first?
