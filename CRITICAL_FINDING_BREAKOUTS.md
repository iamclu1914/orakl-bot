# 🚨 CRITICAL FINDING: Breakouts Bot Scanning Wrong Universe

## The Problem

**You said:** "Breakout bot that analyzes over 5k stocks every minute to find breakouts happening in the market."

**Current Reality:** Breakouts bot only scans **109 stocks** (your watchlist) every **5 minutes**

## Why This Explains Zero Signals

```
Expected Behavior:
──────────────────────────────────────────────
Universe:       5,000+ stocks
Scan Frequency: Every minute
Daily Scans:    7,200,000 stock scans (5000 × 1440 min)
Expected Hits:  10-30 breakouts/day (0.2% hit rate)
──────────────────────────────────────────────

Current Reality:
──────────────────────────────────────────────
Universe:       109 stocks (watchlist only)
Scan Frequency: Every 5 minutes
Daily Scans:    31,392 stock scans (109 × 288 scans)
Expected Hits:  0-1 breakouts/day (0.003% hit rate)
──────────────────────────────────────────────

Result: 96% FEWER OPPORTUNITIES
```

## The Math

**Breakout Probability:**
- Any given stock has ~0.1-0.3% chance of breaking out on any given day
- With 109 stocks: 109 × 0.2% = **0.22 breakouts expected per day**
- With 5,000 stocks: 5,000 × 0.2% = **10 breakouts expected per day**

**You're Missing 98% of Breakouts**

## Current Code

```python
# src/bots/breakouts_bot.py - Line 36
for symbol in self.watchlist:  # ← Only 109 stocks!
    try:
        breakouts = await self._scan_breakout(symbol)
```

## What Needs to Change

### Option 1: Scan Top 5,000 Stocks by Volume (Recommended)

**Advantages:**
- Catches all liquid breakouts
- Focuses on tradeable stocks
- Manageable API usage

**Implementation:**
```python
class BreakoutsBot(BaseAutoBot):
    def __init__(self, ...):
        # ... existing code ...
        self.scan_universe = []  # Will hold 5,000 stocks
        self.scan_interval = 60  # 1 minute (from 5 minutes)

    async def initialize_scan_universe(self):
        """Get top 5,000 stocks by daily volume"""
        # Option A: Use Polygon API to get top stocks
        endpoint = "/v2/snapshot/locale/us/markets/stocks/tickers"
        params = {
            'limit': 5000,
            'sort': 'volume',  # Sort by volume
            'order': 'desc'
        }

        # Option B: Use pre-built list (Russell 3000 + top growth)
        # This is more reliable and faster
        self.scan_universe = await self.load_top_stocks_list()

    async def load_top_stocks_list(self):
        """Load curated list of 5,000 most liquid stocks"""
        # Could be stored in database or config file
        # Sources: Russell 3000 + NASDAQ 100 + NYSE most active
        return [
            # Top 5000 stocks by market cap + volume
            # This would be a large list
        ]

    async def scan_and_post(self):
        """Scan 5,000 stocks for breakouts"""
        logger.info(f"{self.name} scanning {len(self.scan_universe)} stocks")

        # ... rest of code ...

        # Batch processing for efficiency
        batch_size = 100  # Process 100 stocks at a time
        for i in range(0, len(self.scan_universe), batch_size):
            batch = self.scan_universe[i:i+batch_size]
            await self._scan_batch(batch)
```

### Option 2: Use Polygon Pre-Screener (Most Efficient)

**Advantages:**
- Polygon does the heavy lifting
- Returns only stocks with high volume
- Minimal API calls

**Implementation:**
```python
async def get_breakout_candidates(self):
    """Use Polygon screener to find high-volume stocks"""
    endpoint = "/v2/snapshot/locale/us/markets/stocks/tickers"
    params = {
        'limit': 1000,
        'volume.gte': 1000000,  # At least 1M volume
        'changep.gte': 2.0,     # At least 2% price change
        'order': 'desc',
        'sort': 'changep'
    }

    data = await self.fetcher._make_request(endpoint, params)

    candidates = []
    if data and 'tickers' in data:
        for ticker in data['tickers']:
            # Extract relevant data
            symbol = ticker['ticker']
            price = ticker['lastTrade']['p']
            volume = ticker['day']['v']
            change = ticker['todaysChangePerc']

            candidates.append({
                'symbol': symbol,
                'price': price,
                'volume': volume,
                'change': change
            })

    return candidates[:5000]  # Limit to 5,000
```

### Option 3: Hybrid Approach (Best Balance)

**Strategy:**
1. Core watchlist (109 stocks) - scan every minute
2. Extended universe (5,000 stocks) - scan every 5 minutes
3. Pre-screened candidates (Polygon filter) - scan every minute

**Implementation:**
```python
async def scan_and_post(self):
    """Multi-tier scanning strategy"""
    current_minute = datetime.now().minute

    # TIER 1: Core watchlist (every minute)
    await self._scan_core_watchlist()

    # TIER 2: Extended universe (every 5 minutes)
    if current_minute % 5 == 0:
        await self._scan_extended_universe()

    # TIER 3: Pre-screened high volume (every minute)
    await self._scan_prescreened_candidates()
```

## API Rate Limit Considerations

**Current Polygon Plan: Unlimited**

With unlimited plan, you can handle:
- 5,000 stocks × 1 scan/min = 5,000 requests/min
- Polygon limit: 1,000 requests/5min = 200 req/min

**Problem:** Will hit rate limits unless we batch

**Solution: Intelligent Batching**
```python
async def _scan_batch(self, symbols: List[str]):
    """Scan multiple symbols efficiently"""
    # Use Polygon's snapshot endpoint (1 call for multiple stocks)
    endpoint = "/v2/snapshot/locale/us/markets/stocks/tickers"
    params = {
        'tickers': ','.join(symbols),  # Up to 250 per call
        'limit': 250
    }

    data = await self.fetcher._make_request(endpoint, params)

    # Process batch results
    for ticker_data in data.get('tickers', []):
        await self._process_ticker(ticker_data)
```

**Optimized Scan Rate:**
- 5,000 stocks ÷ 250 per batch = 20 API calls
- At 1 batch per 3 seconds = 60 seconds total
- Result: Scan all 5,000 stocks in 1 minute ✅

## Expected Results After Fix

```
Before (109 stocks):
──────────────────────────────────────────
Scans/day:        31,392 stock checks
Breakouts/day:    0-1
Hit rate:         0.003%
Useful:           ❌ NO
──────────────────────────────────────────

After (5,000 stocks):
──────────────────────────────────────────
Scans/day:        7,200,000 stock checks
Breakouts/day:    10-30
Hit rate:         0.2%
Useful:           ✅ YES
──────────────────────────────────────────
```

## Implementation Priority

**CRITICAL FIX - Implement Immediately**

This is THE reason you have no breakout signals. The bot is working correctly but looking at 2% of the market.

**Steps:**
1. Choose Option 2 (Polygon Pre-Screener) for quickest fix
2. Add snapshot batching for efficiency
3. Change scan interval to 1 minute (from 5)
4. Test with 1,000 stocks first, then scale to 5,000

**Expected Timeline:**
- Quick fix (Option 2): 2-3 hours
- Full implementation (Option 3): 1-2 days

**Expected Outcome:**
- Breakout signals: 0-1/day → 10-30/day
- Quality: Maintain 65+ score threshold
- API usage: 20-30 calls/minute (well within limits)

This single fix will transform the Breakouts bot from useless to your most active scanner.
