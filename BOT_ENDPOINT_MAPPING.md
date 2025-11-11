# Bot Endpoint Mapping - REST Architecture

Complete mapping of each bot to its required Polygon REST API endpoints and logic.

---

## Options Flow Bots (5 bots)

### 1. Golden Sweeps Bot (golden_sweeps_bot.py)

**Purpose**: Detect $1M+ premium institutional sweeps

**Primary Endpoint**: `/v3/snapshot/options/{underlyingAsset}`
**Method**: `fetcher.detect_unusual_flow(underlying, min_premium=1000000)`

**Bot Logic**:
```python
flows = await fetcher.detect_unusual_flow(
    underlying=symbol,
    min_premium=1000000  # $1M threshold
)

# Then apply bot-specific filters:
for flow in flows:
    # Multi-exchange detection
    # Urgency calculation
    # Smart strike filtering (≤5% OTM/ITM)
    # Volume ratio analysis
    # Score calculation
```

**Additional Endpoints Needed**:
- `get_stock_price()` - For current price context
- `calculate_volume_ratio()` - Via EnhancedAnalyzer

**Filter Criteria**:
- Premium ≥ $1M
- Multi-exchange (3+ venues) - NOT AVAILABLE in snapshot, **REMOVE**
- Urgency check (contracts/second) - NOT AVAILABLE, **REMOVE**
- Strike ≤5% OTM/ITM
- Volume ratio > baseline
- Score ≥ 65

**Implementation Notes**:
- Multi-exchange and urgency require trade-level data (not in snapshot)
- **Decision**: Remove those filters, rely on premium + strike + volume
- Snapshot provides: volume, OI, Greeks, price - sufficient for quality signals

---

### 2. Sweeps Bot (sweeps_bot.py)

**Purpose**: Detect $50K+ premium sweeps

**Primary Endpoint**: `/v3/snapshot/options/{underlyingAsset}`
**Method**: `fetcher.detect_unusual_flow(underlying, min_premium=50000)`

**Bot Logic**:
```python
flows = await fetcher.detect_unusual_flow(
    underlying=symbol,
    min_premium=50000  # $50K threshold
)

# Apply filters:
for flow in flows:
    # Volume/OI ratio check
    # Strike distance check
    # Score calculation
```

**Additional Endpoints**:
- `get_stock_price()` - Current price
- Volume ratio analysis

**Filter Criteria**:
- Premium ≥ $50K
- Volume/OI ratio if available
- Score ≥ 60

---

### 3. Bullseye Bot (bullseye_bot.py)

**Purpose**: ATM high-probability setups

**Primary Endpoint**: `/v3/snapshot/options/{underlyingAsset}`
**Method**: `fetcher.detect_unusual_flow(underlying, min_premium=5000)`

**Bot Logic**:
```python
flows = await fetcher.detect_unusual_flow(
    underlying=symbol,
    min_premium=5000  # $5K threshold
)

# Apply ATM filters:
for flow in flows:
    strike_distance = abs((flow['strike'] - underlying_price) / underlying_price) * 100

    if strike_distance > 5.0:  # Must be within 5% of spot
        continue

    # Check delta (0.4-0.6 for ATM)
    if 0.4 <= abs(flow['delta']) <= 0.6:
        # This is truly ATM
        calculate_score()
```

**Additional Endpoints**:
- `get_stock_price()` - For ATM calculation
- Greeks analysis (delta provided in snapshot)

**Filter Criteria**:
- Premium ≥ $5K
- Strike within 5% of spot price
- Delta 0.4-0.6 (true ATM)
- Score ≥ 70

**Key Feature**: Delta-based ATM detection (snapshot provides Greeks)

---

### 4. Scalps Bot (scalps_bot.py)

**Purpose**: 0-7 DTE short-term plays

**Primary Endpoint**: `/v3/snapshot/options/{underlyingAsset}`
**Method**: `fetcher.detect_unusual_flow(underlying, min_premium=2000)`

**Bot Logic**:
```python
flows = await fetcher.detect_unusual_flow(
    underlying=symbol,
    min_premium=2000  # $2K threshold for scalps
)

# Apply DTE filters:
for flow in flows:
    exp_date = datetime.strptime(flow['expiration'], '%Y-%m-%d')
    dte = (exp_date - datetime.now()).days

    if dte > 7:  # Must be 0-7 days
        continue

    # Additional scalp criteria
    if dte <= 2:  # Very short term
        boost_score()
```

**Additional Endpoints**:
- `get_stock_price()` - Current price
- Expiration date parsing (provided in snapshot)

**Filter Criteria**:
- Premium ≥ $2K
- DTE ≤ 7 days
- Prefer DTE ≤ 2 (gamma scalp territory)
- Score ≥ 65

**Key Feature**: Time decay plays, gamma scalps

---

## Stock Analysis Bots (2 bots)

### 6. Darkpool Bot (darkpool_bot.py)

**Purpose**: 10K+ share block trades

**Primary Endpoint**: `/v3/trades/{stockTicker}`
**Method**: `fetcher.get_stock_trades(symbol, limit=1000)`

**Bot Logic**:
```python
trades = await fetcher.get_stock_trades(symbol, limit=1000)

# Filter for blocks:
for trade in trades:
    if trade['size'] >= 10000:  # Block threshold
        if trade['size'] >= avg_size * 5:  # 5x average
            if dollar_value >= 100000:  # $100K+ notional
                # This is a block trade
                check_key_levels()
                check_directional_bias()
                calculate_block_score()
```

**Additional Endpoints**:
- `get_stock_price()` - Current price
- `get_financials()` - 52-week high/low
- `get_30_day_avg_volume()` - Volume context

**Filter Criteria**:
- Size ≥ 10K shares
- Size ≥ 5x average trade size
- Dollar value ≥ $100K
- Score ≥ 60

**Polling Interval**: 90 seconds (already optimal)

---

### 7. Breakouts Bot (breakouts_bot.py)

**Purpose**: Price breakouts with volume confirmation

**Primary Endpoint**: `/v2/aggs/ticker/{stockTicker}/range/1/day/{from}/{to}`
**Method**: Already using aggregates correctly

**Bot Logic**:
```python
# Get 20-day bars
candles = await fetcher._get_aggregates(symbol, ...)

# Calculate support/resistance
resistance = max(recent_highs)
support = min(recent_lows)

# Volume surge check
volume_surge = current_volume / avg_volume

if current_price > resistance * 1.005:  # Bullish breakout
    if volume_surge >= 2.0:  # Volume confirmation
        alert()
```

**Additional Endpoints**:
- `get_stock_price()` - Current price
- Technical indicators (RSI, MAs)

**Filter Criteria**:
- Price > resistance (0.5%+) OR < support (0.5%+)
- Volume surge ≥ 2x average
- Multiple resistance/support touches
- Score ≥ 65

**Polling Interval**: 120 seconds (already optimal)

---

## Implementation Strategy

### Phase 1: Update Options Bots (Priority Order)

**1. Sweeps Bot** (Medium complexity)
- Similar to Golden Sweeps but lower threshold
- Tests premium filtering at $50K level

**2. Golden Sweeps Bot** (Complex)
- Remove multi-exchange/urgency filters (not available)
- Keep strike distance, volume ratio
- Most critical bot ($1M+ signals)

**3. Bullseye Bot** (Delta-focused)
- ATM detection via strike distance + delta
- Tests Greek data usage

**4. Scalps Bot** (DTE-focused)
- DTE filtering from expiration dates
- Tests time-based logic

### Phase 2: Stock Bots

**No changes needed** - Already using optimal endpoints:
- Darkpool: `get_stock_trades()`
- Breakouts: `get_aggregates()`

---

## Endpoint Efficiency Analysis

### OLD Approach (Per-Bot)

```python
# Step 1: Get contracts list
contracts = await get_options_chain(symbol)  # 1 API call

# Step 2: Loop through each contract
for contract in contracts[:50]:
    bars = await get_aggs(contract.ticker, ...)  # 50 API calls!

# Total: 51 API calls per symbol per bot!
```

### NEW Approach (Unified)

```python
# Single snapshot call gets everything
flows = await detect_unusual_flow(symbol, min_premium=10000)

# Total: 1 API call per symbol per bot!
# 51x more efficient!
```

### API Usage Projection

**5 Options Bots × 200 Symbols × 4 scans/minute**:
- OLD: 5 × 200 × 51 × 4 = **204,000 calls/minute** (IMPOSSIBLE!)
- NEW: 5 × 200 × 1 × 4 = **4,000 calls/minute** (still high, need optimization)

**Optimization via Staggered Polling**:
- Bot 1: Scan at :00, :15, :30, :45
- Bot 2: Scan at :03, :18, :33, :48
- Bot 3: Scan at :06, :21, :36, :51
- Bot 4: Scan at :09, :24, :39, :54
- Bot 5: Scan at :12, :27, :42, :57

**Result**: ~300 calls/minute (within limits!)

---

## Data Structure Mapping

### Snapshot Response → Flow Signal

```python
# Polygon /v3/snapshot/options/{underlying} returns:
{
    'ticker': 'O:AAPL250117C00200000',
    'day': {
        'volume': 1500,  # ← Use for volume_delta
        'close': 5.25,   # ← Use for premium calc
        'open': 5.10,
        'high': 5.50,
        'low': 5.00
    },
    'open_interest': 10000,  # ← Use for vol/OI ratio
    'implied_volatility': 0.35,
    'greeks': {
        'delta': 0.52,  # ← Use for ATM detection
        'gamma': 0.03,
        'theta': -0.15,
        'vega': 0.25
    },
    'details': {
        'strike_price': 200.0,      # ← Use for filters
        'expiration_date': '2025-01-17',  # ← Use for DTE
        'contract_type': 'call'      # ← Use for CALL/PUT
    },
    'underlying_asset': {
        'ticker': 'AAPL',
        'price': 195.50  # ← Use for spot price
    }
}

# Transformed to flow signal:
{
    'ticker': 'O:AAPL250117C00200000',
    'underlying': 'AAPL',
    'type': 'CALL',
    'strike': 200.0,
    'expiration': '2025-01-17',
    'volume_delta': 150,  # NEW volume - previous volume
    'total_volume': 1500,
    'open_interest': 10000,
    'vol_oi_ratio': 0.015,  # volume_delta / OI
    'last_price': 5.25,
    'premium': 78750.0,  # volume_delta * price * 100
    'implied_volatility': 0.35,
    'delta': 0.52,
    'gamma': 0.03,
    'theta': -0.15,
    'vega': 0.25,
    'underlying_price': 195.50,
    'timestamp': datetime(...)
}
```

---

## Quality Checklist

### Data Validation
- ✅ Price validation (DataValidator.validate_price)
- ✅ Volume validation (must be > 0)
- ✅ Strike validation (reasonable range)
- ✅ Expiration date parsing (YYYY-MM-DD format)
- ✅ Greeks validation (delta -1 to 1)

### Error Handling
- ✅ API timeout handling (exponential backoff)
- ✅ Rate limit handling (429 responses)
- ✅ Invalid data graceful skipping
- ✅ Missing fields default values
- ✅ Comprehensive logging

### Performance
- ✅ Volume cache with TTL
- ✅ Automatic cleanup task
- ✅ Staggered polling intervals
- ✅ Connection pooling
- ✅ Rate limiting (5 req/sec)

### Monitoring
- ✅ Cache hit rate tracking
- ✅ API call counting
- ✅ Error rate monitoring
- ✅ Flow detection metrics
- ✅ Bot health checks

---

## Summary

**Each Options Bot Uses**:
1. PRIMARY: `detect_unusual_flow()` - Single efficient call
2. CONTEXT: `get_stock_price()` - Underlying spot price
3. FILTERS: Bot-specific logic on flow signals

**Each Stock Bot Uses** (No changes):
1. Darkpool: `get_stock_trades()` + volume analysis
2. Breakouts: `get_aggregates()` + technical analysis

**Key Insight**: Options bots share the SAME primary endpoint but apply DIFFERENT filters to the flow signals. This is optimal architecture - fetch once, filter many ways.
