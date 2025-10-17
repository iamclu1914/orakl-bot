# ORAKL Bot Trading Schedule

## Bot Operating Hours

### Regular Market Hours Bots (9:30 AM - 4:00 PM EST, Monday-Friday)
These bots only scan during regular trading hours:

- **Orakl Flow Bot** - Repeat & dominant options flow
- **Bullseye Bot** - AI intraday momentum signals
- **Scalps Bot** - Quick scalp opportunities using The Strat
- **Sweeps Bot** - Large options sweeps ($50k+ premium)
- **Golden Sweeps Bot** - Million dollar options sweeps
- **Darkpool Bot** - Large block trades and darkpool activity
- **Breakouts Bot** - Stock breakout patterns
- **Unusual Volume Bot** - Stocks with 3x+ average volume

### 24/7 Weekday Bot
This bot scans continuously on trading days:

- **STRAT Pattern Bot** - Scans 24/7 Monday-Friday (excluding weekends and holidays)
  - 3-2-2 Reversal patterns (60-minute timeframe)
  - 2-2 Reversal Retrigger (4-hour timeframe)
  - 1-3-1 Miyagi patterns (12-hour timeframe)

## Trading Calendar

### Market Hours
- **Pre-market**: 4:00 AM - 9:30 AM EST
- **Regular Hours**: 9:30 AM - 4:00 PM EST ✅ (Bot scanning active)
- **After-hours**: 4:00 PM - 8:00 PM EST

### Non-Trading Days (All bots pause)
- Saturdays & Sundays
- US Market Holidays:
  - New Year's Day
  - Martin Luther King Jr. Day
  - Presidents' Day
  - Good Friday
  - Memorial Day
  - Juneteenth
  - Independence Day
  - Labor Day
  - Thanksgiving
  - Christmas

## Schedule Summary

| Bot | Mon-Fri | Weekends | Holidays | Hours |
|-----|---------|----------|----------|--------|
| Orakl Flow | ✅ | ❌ | ❌ | 9:30am-4pm |
| Bullseye | ✅ | ❌ | ❌ | 9:30am-4pm |
| Scalps | ✅ | ❌ | ❌ | 9:30am-4pm |
| Sweeps | ✅ | ❌ | ❌ | 9:30am-4pm |
| Golden Sweeps | ✅ | ❌ | ❌ | 9:30am-4pm |
| Darkpool | ✅ | ❌ | ❌ | 9:30am-4pm |
| Breakouts | ✅ | ❌ | ❌ | 9:30am-4pm |
| Unusual Volume | ✅ | ❌ | ❌ | 9:30am-4pm |
| STRAT Pattern | ✅ | ❌ | ❌ | 24/7 on trading days |

## Implementation Details

- All bots (except STRAT) check `MarketHours.is_market_open()` before scanning
- STRAT bot checks `MarketHours.is_trading_day()` to exclude weekends/holidays
- Market hours utility includes comprehensive US market holiday calendar
- Bots will log "Market closed, skipping scan" outside of hours
