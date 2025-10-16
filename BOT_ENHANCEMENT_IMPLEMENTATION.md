# ORAKL Bot Suite - Complete Enhancement Implementation Guide

## Overview
This document provides the complete implementation plan for upgrading all 9 bots based on the PRD specifications to achieve 68-75% win rates.

---

## 🎯 Bot 1: STRAT Pattern Bot

### Current State
- Basic STRAT pattern detection (1, 2U, 2D, 3)
- Single timeframe scanning

### Required Enhancements

#### 1. Add Miyagi Pattern (12H 1-3-1)
```python
async def scan_miyagi_pattern(self, symbol: str) -> Optional[Dict]:
    """
    Detect 12H Miyagi setup (1-3-1 with 50% retracement)
    Scan Times: 3:45 PM ET and 3:45 AM ET
    """
    # Get 12-hour bars (last 5 bars)
    bars_12h = await self.data_fetcher.get_aggregates(
        symbol, 'hour', 12,
        (datetime.now() - timedelta(days=3)).strftime('%Y-%m-%d'),
        datetime.now().strftime('%Y-%m-%d')
    )

    if len(bars_12h) < 4:
        return None

    # Identify pattern sequence
    patterns = []
    for i in range(-4, 0):
        bar_type = self._identify_bar_type(bars_12h.iloc[i], bars_12h.iloc[i-1] if i > -4 else None)
        patterns.append(bar_type)

    # Check for 1-3-1 sequence
    if patterns[0] == '1' and patterns[1] == '3' and patterns[2] == '1':
        # Calculate 50% retracement level of candle #3
        candle_3 = bars_12h.iloc[-2]
        trigger_level = (candle_3['high'] + candle_3['low']) / 2

        # Check 4th candle (current)
        current = bars_12h.iloc[-1]
        fourth_type = patterns[3]

        if fourth_type in ['2U', '2D']:
            # Determine direction based on 4th candle relative to trigger
            if fourth_type == '2U' and current['close'] > trigger_level:
                direction = 'PUT'  # Expecting reversal down
            elif fourth_type == '2D' and current['close'] < trigger_level:
                direction = 'CALL'  # Expecting reversal up
            else:
                return None

            return {
                'pattern_type': 'MIYAGI_12H',
                'sequence': '1-3-1',
                'direction': direction,
                'trigger_level': trigger_level,
                'current_price': current['close'],
                'fourth_candle': fourth_type,
                'confidence_score': 0.75
            }

    return None
```

#### 2. Add 3-2-2 Reversal (60-Minute)
```python
async def scan_322_reversal(self, symbol: str) -> Optional[Dict]:
    """
    Detect 3-2-2 reversal on 60-minute timeframe
    Scan Times: 8:05, 9:05, 10:05, 11:05 AM ET
    First 3 hours of trading only
    """
    et_tz = pytz.timezone('US/Eastern')
    now_et = datetime.now(et_tz)

    # Only scan during valid hours
    if now_et.hour not in [8, 9, 10, 11]:
        return None

    # Get 60-minute bars for first 3 hours
    bars_60m = await self.data_fetcher.get_aggregates(
        symbol, 'minute', 60,
        now_et.replace(hour=8, minute=0).strftime('%Y-%m-%d %H:%M'),
        now_et.strftime('%Y-%m-%d %H:%M')
    )

    if len(bars_60m) < 3:
        return None

    # Map to hour windows: 8AM, 9AM, 10AM
    hour_8 = bars_60m[bars_60m.index.hour == 8].iloc[-1] if len(bars_60m[bars_60m.index.hour == 8]) > 0 else None
    hour_9 = bars_60m[bars_60m.index.hour == 9].iloc[-1] if len(bars_60m[bars_60m.index.hour == 9]) > 0 else None
    hour_10 = bars_60m[bars_60m.index.hour == 10].iloc[-1] if len(bars_60m[bars_60m.index.hour == 10]) > 0 else None

    if not (hour_8 is not None and hour_9 is not None and hour_10 is not None):
        return None

    # Identify bar types
    type_8 = self._identify_bar_type(hour_8, None)  # First bar
    type_9 = self._identify_bar_type(hour_9, hour_8)
    type_10 = self._identify_bar_type(hour_10, hour_9)

    # Valid 3-2-2 pattern:
    # 8AM: 3 (outside)
    # 9AM: 2U or 2D
    # 10AM: Opposite 2 (2D if 9AM was 2U, or 2U if 9AM was 2D)

    if type_8 == '3' and type_9 in ['2U', '2D']:
        if (type_9 == '2U' and type_10 == '2D') or (type_9 == '2D' and type_10 == '2U'):
            # Reversal confirmed
            direction = 'CALL' if type_10 == '2U' else 'PUT'

            # Calculate entry, target, stop
            if direction == 'CALL':
                entry = hour_9['high']  # Break of 9AM high
                target = hour_8['high']  # Target 8AM high
                stop = hour_10['low']    # Stop below 10AM low
            else:
                entry = hour_9['low']
                target = hour_8['low']
                stop = hour_10['high']

            rr_ratio = abs(target - entry) / abs(entry - stop) if abs(entry - stop) > 0 else 0

            return {
                'pattern_type': '3-2-2_REVERSAL',
                'timeframe': '60-minute',
                'direction': direction,
                'entry': entry,
                'target': target,
                'stop': stop,
                'risk_reward': rr_ratio,
                'bars': {'8AM': type_8, '9AM': type_9, '10AM': type_10},
                'confidence_score': 0.70
            }

    return None
```

#### 3. Add 2-2 Reversal Retrigger (4-Hour)
```python
async def scan_22_reversal(self, symbol: str) -> Optional[Dict]:
    """
    Detect 2-2 reversal retrigger on 4-hour timeframe
    Scan Times: 8:15, 8:45, 9:15 AM ET (pre-market setup)
    """
    et_tz = pytz.timezone('US/Eastern')
    now_et = datetime.now(et_tz)

    # Only scan during pre-market/open hours
    if not (8 <= now_et.hour <= 9 and now_et.minute <= 30):
        return None

    # Get 4-hour bars (include overnight)
    bars_4h = await self.data_fetcher.get_aggregates(
        symbol, 'hour', 4,
        (now_et - timedelta(days=2)).strftime('%Y-%m-%d'),
        now_et.strftime('%Y-%m-%d')
    )

    if len(bars_4h) < 2:
        return None

    # Get 4AM bar and 8AM bar
    bar_4am = bars_4h[bars_4h.index.hour == 4].iloc[-1] if len(bars_4h[bars_4h.index.hour == 4]) > 0 else None
    bar_8am = bars_4h[bars_4h.index.hour == 8].iloc[-1] if len(bars_4h[bars_4h.index.hour == 8]) > 0 else None

    if bar_4am is None or bar_8am is None:
        return None

    # 4AM must be 2U or 2D
    type_4am = self._identify_bar_type(bar_4am, None)

    if type_4am in ['2U', '2D']:
        # Check if 8AM opens INSIDE 4AM bar
        if bar_8am['open'] <= bar_4am['high'] and bar_8am['open'] >= bar_4am['low']:
            # Reversal setup detected
            if type_4am == '2D':
                # Expecting reversal UP
                direction = 'CALL'
                trigger = bar_4am['high']
                target = trigger * 1.02  # 2% target
                stop = bar_4am['low']
            else:  # 2U
                # Expecting reversal DOWN
                direction = 'PUT'
                trigger = bar_4am['low']
                target = trigger * 0.98  # 2% target
                stop = bar_4am['high']

            return {
                'pattern_type': '2-2_REVERSAL',
                'timeframe': '4-hour',
                'direction': direction,
                'trigger': trigger,
                'target': target,
                'stop': stop,
                'setup': f"{type_4am} -> {direction}",
                'confidence_score': 0.68
            }

    return None
```

### Scanning Schedule
```python
# In strat_bot.py main loop
async def run_scheduled_scans(self):
    """Run scans on schedule"""
    while True:
        et_tz = pytz.timezone('US/Eastern')
        now_et = datetime.now(et_tz)

        # Miyagi scans (3:45 PM and 3:45 AM)
        if (now_et.hour == 15 and now_et.minute == 45) or \
           (now_et.hour == 3 and now_et.minute == 45):
            await self.scan_all_miyagi()

        # 3-2-2 scans (8:05, 9:05, 10:05, 11:05 AM)
        if now_et.hour in [8, 9, 10, 11] and now_et.minute == 5:
            await self.scan_all_322()

        # 2-2 scans (8:15, 8:45, 9:15 AM)
        if now_et.hour in [8, 9] and now_et.minute in [15, 45]:
            await self.scan_all_22()

        # Regular STRAT every 15 minutes
        if now_et.minute % 15 == 0:
            await self.scan_all_regular_strat()

        await asyncio.sleep(60)  # Check every minute
```

---

## 💎 Bot 2: Golden Sweeps Bot

### Required Enhancements

#### 1. Multi-Exchange Detection
```python
def detect_multi_exchange_sweep(self, trades_df: pd.DataFrame) -> bool:
    """
    Check if sweep hit 3+ exchanges
    Exchange IDs: CBOE=312, ISE=313, PHLX=316, etc.
    """
    exchanges_hit = trades_df['exchange'].nunique()
    return exchanges_hit >= 3
```

#### 2. Urgency Scoring
```python
def calculate_urgency_score(self, trades_df: pd.DataFrame) -> Dict:
    """
    Calculate execution urgency
    """
    time_span = (trades_df['timestamp'].max() - trades_df['timestamp'].min()).total_seconds()
    total_contracts = trades_df['size'].sum()

    contracts_per_second = total_contracts / max(time_span, 1)

    # Urgency thresholds
    if contracts_per_second >= 200:
        urgency = 'VERY HIGH'
        score = 1.0
    elif contracts_per_second >= 100:
        urgency = 'HIGH'
        score = 0.8
    elif contracts_per_second >= 50:
        urgency = 'MEDIUM'
        score = 0.6
    else:
        urgency = 'LOW'
        score = 0.4

    return {
        'urgency': urgency,
        'score': score,
        'contracts_per_second': contracts_per_second,
        'execution_time': time_span
    }
```

#### 3. Opening vs Closing Position Detection
```python
async def is_opening_position(self, contract: str, volume: int) -> bool:
    """
    Detect if this is opening position (not closing)
    """
    # Get open interest for contract
    # If volume > 50% of OI, likely opening new position
    # Simplified: use average trade size as proxy

    avg_trade_size_usd = self.total_premium / self.num_trades

    # Large avg trade ($100k+) suggests institutional opening
    if avg_trade_size_usd >= 100_000:
        return True

    return False
```

#### 4. Smart Strike Selection Filter
```python
def is_smart_strike(self, strike: float, current_price: float, option_type: str) -> bool:
    """
    Filter out lottery ticket far OTM options
    Smart strikes: ≤5% OTM
    """
    strike_distance_pct = abs((strike - current_price) / current_price) * 100

    # Allow ≤5% OTM
    if option_type == 'CALL':
        # For calls, strike above current = OTM
        if strike > current_price and strike_distance_pct > 5:
            return False
    else:  # PUT
        # For puts, strike below current = OTM
        if strike < current_price and strike_distance_pct > 5:
            return False

    return True
```

### Enhanced scan() method
```python
async def scan(self, symbol: str) -> Optional[Dict]:
    """Enhanced golden sweep detection"""
    # Get options trades (last 5 minutes)
    trades = await self.fetcher.get_options_trades(symbol)

    if trades.empty:
        return None

    # Filter recent trades
    cutoff = datetime.now() - timedelta(minutes=5)
    recent = trades[trades['timestamp'] > cutoff]

    # Group by contract
    for contract, group in recent.groupby('contract'):
        total_premium = (group['price'] * group['size'] * 100).sum()

        # Check $1M minimum
        if total_premium < 1_000_000:
            continue

        # Multi-exchange check
        if not self.detect_multi_exchange_sweep(group):
            continue

        # Urgency check
        urgency_data = self.calculate_urgency_score(group)
        if urgency_data['urgency'] == 'LOW':
            continue

        # Opening position check
        if not await self.is_opening_position(contract, group['size'].sum()):
            continue

        # Smart strike check
        strike = self._parse_strike_from_contract(contract)
        current_price = await self.fetcher.get_stock_price(symbol)
        option_type = 'CALL' if 'C' in contract else 'PUT'

        if not self.is_smart_strike(strike, current_price, option_type):
            continue

        # All checks passed - Golden Sweep confirmed
        return {
            'symbol': symbol,
            'contract': contract,
            'premium': total_premium,
            'urgency': urgency_data['urgency'],
            'exchanges_hit': group['exchange'].nunique(),
            'execution_time': urgency_data['execution_time'],
            'strike': strike,
            'option_type': option_type,
            'confidence_score': 0.80,
            'pattern_confirmed': True,
            'smart_money': True
        }

    return None
```

---

## 🎯 Bot 3: Bullseye Bot

### Required Enhancements

#### 1. Baseline Relative Volume
```python
async def calculate_relative_volume(self, symbol: str, current_volume: int) -> float:
    """
    Calculate volume relative to 20-day baseline
    """
    # Get 20-day bars
    bars = await self.fetcher.get_aggregates(
        symbol, 'day', 1,
        (datetime.now() - timedelta(days=25)).strftime('%Y-%m-%d'),
        datetime.now().strftime('%Y-%m-%d')
    )

    if bars.empty:
        return 1.0

    baseline_avg_volume = bars['volume'].mean()

    if baseline_avg_volume > 0:
        volume_ratio = current_volume / baseline_avg_volume
    else:
        volume_ratio = 1.0

    return volume_ratio
```

#### 2. Directional Conviction Score
```python
def calculate_directional_conviction(self, call_premium: float, put_premium: float) -> Dict:
    """
    Calculate directional conviction (need 80/20 split minimum)
    """
    total = call_premium + put_premium

    if total == 0:
        return {'conviction': 0, 'direction': 'NEUTRAL'}

    call_pct = call_premium / total
    put_pct = put_premium / total

    # Check for 80/20 split
    if call_pct >= 0.80:
        return {
            'conviction': call_pct,
            'direction': 'BULLISH',
            'split': f"{call_pct*100:.0f}/{put_pct*100:.0f}",
            'passes': True
        }
    elif put_pct >= 0.80:
        return {
            'conviction': put_pct,
            'direction': 'BEARISH',
            'split': f"{call_pct*100:.0f}/{put_pct*100:.0f}",
            'passes': True
        }
    else:
        return {
            'conviction': max(call_pct, put_pct),
            'direction': 'MIXED',
            'split': f"{call_pct*100:.0f}/{put_pct*100:.0f}",
            'passes': False
        }
```

#### 3. Smart Money Filter
```python
def filter_smart_money(self, trades_df: pd.DataFrame) -> pd.DataFrame:
    """
    Filter for smart money trades (avg size $10k+)
    """
    # Calculate premium per trade
    trades_df['premium'] = trades_df['price'] * trades_df['size'] * 100

    # Filter for $10k+ trades
    smart_money = trades_df[trades_df['premium'] >= 10_000]

    return smart_money
```

#### 4. ATM/Near-Money Strike Filter
```python
def is_atm_or_near_money(self, strike: float, current_price: float) -> bool:
    """
    Only alert on ATM or near-money strikes
    """
    distance_pct = abs((strike - current_price) / current_price) * 100

    # ATM: within 2% of current price
    # Near-money: within 5% of current price
    return distance_pct <= 5.0
```

### Enhanced scan() method
```python
async def scan(self, symbol: str) -> Optional[Dict]:
    """Enhanced unusual activity detection"""
    # Get current price
    current_price = await self.fetcher.get_stock_price(symbol)

    # Get options trades (last 30 minutes)
    trades = await self.fetcher.get_options_trades(symbol)

    if trades.empty:
        return None

    # Calculate relative volume
    current_volume = trades['size'].sum()
    volume_ratio = await self.calculate_relative_volume(symbol, current_volume)

    # Check 3x minimum
    if volume_ratio < 3.0:
        return None

    # Filter for smart money only
    smart_trades = self.filter_smart_money(trades)

    if smart_trades.empty:
        return None

    # Calculate directional conviction
    call_premium = smart_trades[smart_trades['type'] == 'CALL']['premium'].sum()
    put_premium = smart_trades[smart_trades['type'] == 'PUT']['premium'].sum()

    conviction_data = self.calculate_directional_conviction(call_premium, put_premium)

    # Require 80/20 split
    if not conviction_data['passes']:
        return None

    # Check strike selection
    atm_trades = []
    for _, trade in smart_trades.iterrows():
        if self.is_atm_or_near_money(trade['strike'], current_price):
            atm_trades.append(trade)

    if not atm_trades:
        return None

    # Calculate average trade size
    avg_trade_size = smart_trades['premium'].mean()

    return {
        'symbol': symbol,
        'volume_ratio': volume_ratio,
        'direction': conviction_data['direction'],
        'conviction': conviction_data['conviction'],
        'split': conviction_data['split'],
        'total_premium': call_premium + put_premium,
        'avg_trade_size': avg_trade_size,
        'smart_money': avg_trade_size >= 10_000,
        'confidence_score': 0.70,
        'price_aligned': True
    }
```

---

Due to character limits, I'll create a separate implementation file for the remaining bots (Breakouts, Scalps, Unusual Activity, Sweeps, Darkpool, ORAKL Flow).

Would you like me to:
1. Continue with the remaining bot implementations in a new file?
2. Start implementing these changes directly into the existing bot files?
3. Create a prioritized implementation order (which bots to upgrade first for maximum impact)?

Given your unlimited Polygon API access, I recommend implementing in this order for maximum signal generation:
1. **Breakouts Bot** (market-wide scanning = 20-40 signals/day immediately)
2. **Bullseye Bot** (relative volume + smart money = quality improvement)
3. **Golden Sweeps Bot** (multi-exchange + urgency = fewer but higher conviction)
4. **STRAT Bot** (new patterns = diversified signal types)

Which approach would you prefer?