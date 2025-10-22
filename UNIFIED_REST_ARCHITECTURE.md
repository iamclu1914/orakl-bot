# Unified REST Architecture - Production Implementation Plan

## 🎯 Executive Summary

**Decision**: Migrate from hybrid Kafka+REST architecture to unified REST-only architecture for all bots.

**Rationale**:
- User has **Polygon Advanced tier** for both stocks and options (real-time data)
- Eliminates Confluent Cloud costs and Kafka operational complexity
- Unified codebase with single data source
- REST API provides sufficient latency with optimized polling (5-30s intervals)
- Leverage Polygon's **Option Chain Snapshot** endpoint for efficient flow detection

**Impact**:
- ✅ **Simplified architecture**: Single data source (REST API)
- ✅ **Cost reduction**: No Confluent Cloud subscription
- ✅ **Easier maintenance**: No Kafka consumer management
- ✅ **Sufficient performance**: 5-30s latency vs <1s Kafka (acceptable for use case)
- ⚠️ **Higher API usage**: More REST calls, but within Advanced tier limits
- ⚠️ **Requires optimization**: Smart polling and efficient endpoint usage

---

## 📊 Current Architecture Analysis

### Current State (Hybrid Kafka + REST)

**Kafka-based Options Flow (5 bots)**:
```
processed-flows topic (Confluent Cloud)
├── Golden Sweeps Bot (Kafka) - $1M+ premium
├── Sweeps Bot (Kafka) - $50K+ premium
├── Bullseye Bot (Kafka) - ATM trades
├── Scalps Bot (Kafka) - 0-7 DTE
└── ORAKL Flow Bot (Kafka) - $10K+ general flow

Characteristics:
✅ Latency: <1 second
✅ Pre-aggregated flow data
✅ No polling required
❌ Kafka infrastructure complexity
❌ Confluent Cloud costs
❌ Vendor dependency
```

**REST-based Stock Analysis (2+ bots)**:
```
Polygon REST API (Advanced Stocks tier)
├── Darkpool Bot (REST) - Block trades
├── Breakouts Bot (REST) - Price breakouts
└── Options bots (REST versions available but not used)

Characteristics:
✅ Simple implementation
✅ No infrastructure overhead
✅ Direct API access
✅ Production-proven (already deployed)
❌ Polling latency (60-120s)
❌ Limited to stock analysis
```

### Current Deployment State

**Production**: `main.py` → `BotManager`
- 7 active bots (5 options + 2 stocks)
- Uses REST API via `DataFetcher`
- **Kafka bots NOT currently in production** (run_kafka_bots.py exists but not deployed)

---

## 🏗️ Proposed Unified REST Architecture

### Architecture Overview

```
main.py
├── BotManager (Unified Orchestrator)
│   │
│   ├── Options Flow Bots (REST-based with Snapshot Polling)
│   │   ├── GoldenSweepsBot - $1M+ premium flow
│   │   ├── SweepsBot - $50K+ premium flow
│   │   ├── BullseyeBot - ATM high-probability setups
│   │   ├── ScalpsBot - 0-7 DTE short-term plays
│   │   └── OraklFlowBot - $10K+ general flow
│   │
│   └── Stock Analysis Bots (REST-based with Aggregates/Trades)
│       ├── DarkpoolBot - Block trade detection
│       └── BreakoutsBot - Price breakout patterns
│
└── DataFetcher (Enhanced REST Client)
    ├── Options Flow Detection
    │   ├── get_option_chain_snapshot() - Primary method
    │   ├── detect_unusual_flow() - Flow aggregation
    │   └── Volume change tracking
    │
    ├── Stock Analysis (Already Implemented)
    │   ├── get_stock_trades() - For darkpool detection
    │   ├── get_aggregates() - For breakouts
    │   └── get_stock_price() - Current pricing
    │
    └── Infrastructure
        ├── Rate limiting (5 req/sec Advanced tier)
        ├── Circuit breaker pattern
        ├── Exponential backoff
        ├── Caching (30-60s TTL)
        └── Connection pooling
```

### Key Design Decisions

**1. Primary Endpoint for Options Flow**: `/v3/snapshot/options/{underlyingAsset}`

**Why This Endpoint**:
- Gets ALL contracts for an underlying in **ONE API call**
- Returns: ticker, volume, OI, last price, Greeks, bid/ask
- Efficient vs fetching contracts individually (50+ calls → 1 call)
- Perfect for flow detection via volume comparison

**Alternative Considered**: `/v3/trades/{optionsTicker}`
- ❌ Requires knowing specific contract ticker beforehand
- ❌ Must poll each contract individually
- ❌ 1000x more API calls
- ❌ Not suitable for flow scanning

**2. Polling Strategy**: Adaptive intervals based on market activity

```python
# Intelligent polling intervals
MARKET_OPEN_FIRST_HOUR = 5s   # High frequency during opening volatility
MARKET_HOURS_NORMAL = 15s      # Standard real-time feel
MARKET_LAST_HOUR = 10s         # Increased frequency at close
AFTER_HOURS = 60s              # Reduced when markets closed
```

**3. Flow Detection Algorithm**: Volume delta analysis

```python
# Pseudocode for flow detection
current_snapshot = get_option_chain_snapshot(ticker)
previous_snapshot = cache.get(ticker)

for contract in current_snapshot:
    volume_delta = contract.volume - previous_snapshot[contract].volume

    if volume_delta >= THRESHOLD:
        # Flow detected!
        premium = volume_delta * contract.last_price * 100

        if premium >= MIN_PREMIUM:
            alert_to_discord(contract, premium, volume_delta)
```

**4. Caching Strategy**: Multi-layer caching

```python
# Layer 1: In-memory volume tracking (5-15s snapshots)
volume_cache = {
    'AAPL': {
        'O:AAPL250117C00200000': {'volume': 1500, 'timestamp': ...},
        'O:AAPL250117P00200000': {'volume': 800, 'timestamp': ...}
    }
}

# Layer 2: API response caching (30-60s TTL)
@cached(ttl_seconds=30)
async def get_option_chain_snapshot(ticker):
    # Polygon API call cached for 30s
    ...

# Layer 3: Market data caching (5-15min for price/OI)
@cached(ttl_seconds=300)
async def get_underlying_price(ticker):
    ...
```

---

## 📋 Polygon REST API Endpoint Mapping

### Options Flow Detection

| Endpoint | Use Case | Frequency | Priority |
|----------|----------|-----------|----------|
| **`/v3/snapshot/options/{underlyingAsset}`** | **Primary flow detection** | 5-30s | **CRITICAL** |
| `/v3/reference/options/contracts` | Contract discovery (initial load) | Once/day | Medium |
| `/v3/trades/{optionsTicker}` | Detailed trade analysis (optional) | On-demand | Low |
| `/v2/aggs/ticker/{optionsTicker}/range/...` | Historical aggregation | On-demand | Low |

### Stock Analysis (Already Implemented)

| Endpoint | Use Case | Frequency | Priority |
|----------|----------|-----------|----------|
| `/v3/trades/{stockTicker}` | Darkpool block detection | 90s | High |
| `/v2/aggs/ticker/{stockTicker}/range/...` | Breakout pattern detection | 120s | High |
| `/v2/aggs/ticker/{ticker}/prev` | Current price | 30s (cached) | High |
| `/v2/snapshot/locale/us/markets/stocks/tickers` | Market-wide scan | Optional | Medium |

### Supporting Endpoints

| Endpoint | Use Case | Frequency | Priority |
|----------|----------|-----------|----------|
| `/v1/marketstatus/now` | Market hours check | 60s | Medium |
| `/v3/reference/tickers/{ticker}` | Ticker details | Once/day | Low |
| `/vX/snapshot/locale/us/markets/stocks/tickers` | Full market snapshot | Optional | Low |

---

## 🔧 Implementation Plan

### Phase 1: Enhanced DataFetcher (Week 1)

**Objective**: Add efficient options flow detection methods

**Tasks**:
1. **Add Option Chain Snapshot Method**
   ```python
   async def get_option_chain_snapshot(
       self,
       underlying: str,
       contract_type: Optional[str] = None  # 'call', 'put', or None for both
   ) -> Dict:
       """
       Get complete snapshot of all options contracts for an underlying.

       Uses: /v3/snapshot/options/{underlyingAsset}
       Returns: All contracts with volume, OI, Greeks, last trade
       """
       endpoint = f"/v3/snapshot/options/{underlying}"
       params = {}

       if contract_type:
           params['contract_type'] = contract_type

       data = await self._make_request(endpoint, params)

       if data and 'results' in data:
           return data['results']
       return []
   ```

2. **Add Flow Detection Logic**
   ```python
   async def detect_unusual_flow(
       self,
       underlying: str,
       min_premium: float = 10000,
       min_volume_delta: int = 100
   ) -> List[Dict]:
       """
       Detect unusual options flow by comparing volume deltas.

       Algorithm:
       1. Get current snapshot
       2. Compare with previous snapshot (cached)
       3. Calculate volume delta per contract
       4. Filter by premium threshold
       5. Return flow signals
       """
       current_snapshot = await self.get_option_chain_snapshot(underlying)
       previous_snapshot = await self.volume_cache.get(underlying) or {}

       flows = []
       for contract in current_snapshot:
           ticker = contract['ticker']
           current_volume = contract.get('day', {}).get('volume', 0)
           previous_volume = previous_snapshot.get(ticker, {}).get('volume', 0)

           volume_delta = current_volume - previous_volume

           if volume_delta >= min_volume_delta:
               last_price = contract.get('day', {}).get('close', 0)
               premium = volume_delta * last_price * 100

               if premium >= min_premium:
                   flows.append({
                       'ticker': ticker,
                       'underlying': underlying,
                       'type': 'CALL' if 'C' in ticker else 'PUT',
                       'strike': contract.get('details', {}).get('strike_price', 0),
                       'expiration': contract.get('details', {}).get('expiration_date', ''),
                       'volume_delta': volume_delta,
                       'total_volume': current_volume,
                       'open_interest': contract.get('open_interest', 0),
                       'last_price': last_price,
                       'premium': premium,
                       'implied_volatility': contract.get('implied_volatility', 0),
                       'delta': contract.get('greeks', {}).get('delta', 0),
                       'underlying_price': contract.get('underlying_asset', {}).get('price', 0),
                       'timestamp': datetime.now()
                   })

       # Update cache with current snapshot
       await self.volume_cache.set(underlying, {
           c['ticker']: {'volume': c.get('day', {}).get('volume', 0)}
           for c in current_snapshot
       })

       return flows
   ```

3. **Add Volume Cache Manager**
   ```python
   class VolumeCache:
       """In-memory cache for tracking volume changes"""

       def __init__(self):
           self.cache: Dict[str, Dict] = {}
           self.timestamps: Dict[str, datetime] = {}

       async def get(self, ticker: str) -> Optional[Dict]:
           """Get previous snapshot for ticker"""
           if ticker in self.cache:
               # Check if cache is still fresh (< 2 minutes)
               if datetime.now() - self.timestamps[ticker] < timedelta(minutes=2):
                   return self.cache[ticker]
           return None

       async def set(self, ticker: str, snapshot: Dict):
           """Store snapshot for ticker"""
           self.cache[ticker] = snapshot
           self.timestamps[ticker] = datetime.now()

       async def cleanup(self):
           """Remove stale entries (> 5 minutes)"""
           cutoff = datetime.now() - timedelta(minutes=5)
           stale_keys = [
               k for k, v in self.timestamps.items()
               if v < cutoff
           ]
           for key in stale_keys:
               self.cache.pop(key, None)
               self.timestamps.pop(key, None)
   ```

**Expected Outcome**: DataFetcher can efficiently detect options flow using snapshots

---

### Phase 2: Update Options Bots (Week 1-2)

**Objective**: Modify existing REST bot implementations to use new snapshot-based flow detection

**Tasks**:
1. **Update Golden Sweeps Bot (REST version)**
   - Change from `get_options_trades()` to `detect_unusual_flow()`
   - Filter for `premium >= $1M`
   - Polling interval: 10-15 seconds

2. **Update Sweeps Bot (REST version)**
   - Use `detect_unusual_flow(min_premium=50000)`
   - Polling interval: 15 seconds

3. **Update Bullseye Bot (REST version)**
   - Filter for ATM contracts (strike within 5% of spot)
   - Use delta-based filtering (`abs(delta) > 0.4`)
   - Polling interval: 15 seconds

4. **Update Scalps Bot (REST version)**
   - Filter for DTE <= 7 days
   - Focus on near-term expirations
   - Polling interval: 20 seconds

5. **Update ORAKL Flow Bot (REST version)**
   - General flow detection ($10K+ premium)
   - Polling interval: 20 seconds

**Bot Template** (Shared Pattern):
```python
class GoldenSweepsBot(BaseAutoBot):
    def __init__(self, webhook_url: str, watchlist: List[str],
                 fetcher: DataFetcher, analyzer: OptionsAnalyzer):
        super().__init__(webhook_url, "Golden Sweeps Bot", scan_interval=15)
        self.watchlist = watchlist
        self.fetcher = fetcher
        self.analyzer = analyzer
        self.MIN_PREMIUM = 1000000  # $1M

    async def _scan_symbol(self, symbol: str) -> List[Dict]:
        """Scan for $1M+ premium flows"""
        flows = await self.fetcher.detect_unusual_flow(
            underlying=symbol,
            min_premium=self.MIN_PREMIUM,
            min_volume_delta=10  # At least 10 contracts
        )

        # Additional filtering/scoring
        filtered_flows = []
        for flow in flows:
            score = self.analyzer.calculate_flow_score(flow)
            if score >= 65:
                filtered_flows.append({**flow, 'score': score})

        return filtered_flows

    async def _post_signal(self, flow: Dict):
        """Post flow signal to Discord"""
        embed = self.create_flow_embed(flow)
        await self.post_to_discord(embed)
```

**Expected Outcome**: All 5 options bots use unified REST snapshot approach

---

### Phase 3: Cleanup & Optimization (Week 2)

**Objective**: Remove Kafka dependencies and optimize performance

**Tasks**:
1. **Remove Kafka Configuration**
   - Delete `run_kafka_bots.py`
   - Delete `src/kafka_base.py`
   - Delete all `*_kafka.py` bot files (7 files)
   - Remove Kafka env vars from `.env.example`
   - Update `.gitignore` if needed

2. **Remove Kafka Dependencies**
   - Remove from `requirements.txt`:
     ```
     kafka-python>=2.0.2
     python-snappy>=0.6.1
     ```

3. **Update BotManager**
   - Ensure all 7 bots use REST versions
   - Verify polling intervals are optimized
   - Add adaptive polling logic (market hours detection)

4. **Optimize Polling Strategy**
   ```python
   async def _get_polling_interval(self) -> int:
       """Adaptive polling based on market activity"""
       if not MarketHours.is_market_open():
           return 60  # 1 minute when closed

       now = datetime.now()
       market_open = now.replace(hour=9, minute=30)
       market_close = now.replace(hour=16, minute=0)

       # First hour: high frequency
       if now < market_open + timedelta(hours=1):
           return self.scan_interval // 2  # 2x faster

       # Last hour: increased frequency
       if now > market_close - timedelta(hours=1):
           return int(self.scan_interval * 0.7)  # 1.5x faster

       # Normal hours: standard interval
       return self.scan_interval
   ```

5. **Documentation Updates**
   - Update README with new architecture
   - Add API usage guidelines
   - Document rate limit considerations
   - Remove Kafka setup instructions

**Expected Outcome**: Clean, unified REST-only codebase

---

### Phase 4: Testing & Validation (Week 2-3)

**Objective**: Ensure production readiness and quality

**Quality Gates**:
1. **Functional Testing**
   - ✅ All 7 bots detect signals correctly
   - ✅ Flow detection matches quality of Kafka implementation
   - ✅ No false positives/negatives
   - ✅ Discord webhooks working

2. **Performance Testing**
   - ✅ Polling intervals meet SLA (5-30s latency acceptable)
   - ✅ API rate limits not exceeded
   - ✅ Memory usage < 300 MB
   - ✅ No memory leaks over 24h operation

3. **Resilience Testing**
   - ✅ Handles API timeouts gracefully
   - ✅ Exponential backoff working
   - ✅ Circuit breaker prevents cascading failures
   - ✅ Bot auto-recovery after errors

4. **Alert Quality Validation**
   - ✅ Compare alert frequency: REST vs Kafka
   - ✅ Validate alert quality scores
   - ✅ No duplicate signals
   - ✅ Signal deduplication working

**Validation Checklist**:
```yaml
✅ Options Flow Detection
  - Golden Sweeps alerts for $1M+ premium
  - Sweeps alerts for $50K+ premium
  - Bullseye detects ATM high-probability setups
  - Scalps finds 0-7 DTE opportunities
  - ORAKL Flow catches $10K+ general flow

✅ Stock Analysis
  - Darkpool detects 10K+ share blocks
  - Breakouts catch price pattern breaks

✅ Infrastructure
  - Rate limiting prevents API throttling
  - Caching reduces redundant API calls
  - Error handling prevents bot crashes
  - Logging provides visibility
  - Metrics tracked for monitoring
```

**Expected Outcome**: Production-ready unified REST architecture

---

## 🚀 Deployment Strategy

### Safe Migration Path

**Phased Rollout** (Risk Mitigation):

**Phase 1: Parallel Running** (Week 1)
- Keep Kafka bots running (if currently deployed)
- Deploy REST bots alongside
- Compare alert quality side-by-side
- Validate REST approach meets requirements

**Phase 2: Primary Switch** (Week 2)
- Switch primary production to REST bots
- Keep Kafka bots as backup (standby mode)
- Monitor for 48 hours
- Validate stability

**Phase 3: Full Cutover** (Week 2-3)
- Shutdown Kafka bots completely
- Remove Kafka infrastructure
- Delete Kafka bot code
- Update documentation

**Rollback Plan**:
- If REST bots fail: Immediately revert to Kafka
- Keep Kafka code for 2 weeks after cutover
- Maintain Kafka credentials for emergency recovery

### Render Deployment

**Environment Variables to Update**:
```bash
# Remove (Kafka-related)
# KAFKA_BOOTSTRAP_SERVERS=...
# KAFKA_CONSUMER_GROUP=...
# KAFKA_USERNAME=...
# KAFKA_PASSWORD=...

# Keep (REST API)
POLYGON_API_KEY=NnbFphaif6yWkufcTV8rOEDXRi2LefZN
WATCHLIST_MODE=ALL_MARKET

# Add (Polling optimization)
OPTIONS_POLLING_INTERVAL=15  # 15 seconds for options flow
STOCK_POLLING_INTERVAL=90    # 90 seconds for stock analysis
```

**Start Command** (unchanged):
```bash
python main.py
```

**Expected Resource Usage**:
- Memory: 200-300 MB (moderate increase from snapshot caching)
- CPU: Low (async I/O bound)
- API Calls: ~400-600/minute during market hours (within Advanced tier limits)

---

## 📊 Performance Analysis

### Latency Comparison

| Architecture | Average Latency | Best Case | Worst Case |
|--------------|----------------|-----------|------------|
| **Kafka** | <1s | <100ms | ~2s |
| **REST (Proposed)** | 5-30s | 5s | 60s |
| **Impact** | +5-30s delay | Acceptable for use case | Still real-time feel |

**Latency Breakdown (REST)**:
```
Polling Interval: 15s
API Response Time: 100-300ms
Processing Time: 50-100ms
Discord Webhook: 50-100ms
Total: 15.2-15.5s average
```

### API Usage Projections

**Advanced Tier Limits**: 5 requests/second = 300 requests/minute

**Estimated Usage** (400 symbols, 15s intervals):
```
Options Flow Detection:
- 400 symbols × 4 calls/minute = 1600 calls/minute
- EXCEEDS LIMIT! Need optimization...

Optimized Approach (Batching):
- Batch symbols into groups of 20
- Poll each group sequentially
- 20 groups × 4 calls/minute = 80 calls/minute ✅

Stock Analysis:
- 400 symbols × 0.67 calls/minute (90s interval) = 267 calls/minute
- Need to stagger or reduce watchlist

TOTAL: ~350 calls/minute (within 300 limit if optimized)
```

**Optimization Strategies**:
1. **Staggered Polling**: Offset scan times per bot
2. **Reduced Watchlist**: Focus on liquid symbols only (top 100-200)
3. **Smart Filtering**: Skip symbols with no recent volume
4. **Caching**: Aggressive response caching (30-60s)

### Cost Analysis

**Current (Kafka + REST)**:
- Confluent Cloud: ~$100-300/month
- Polygon Advanced: $199/month (stocks) + $199/month (options) = $398/month
- **Total**: ~$500-700/month

**Proposed (REST Only)**:
- Polygon Advanced: $398/month
- **Total**: $398/month

**Savings**: $100-300/month (15-40% cost reduction)

---

## ⚠️ Risks & Mitigations

### Risk 1: Rate Limiting

**Risk**: Exceed 5 req/sec limit and get throttled
**Impact**: HIGH - Bots stop working
**Probability**: MEDIUM - 350 calls/min is close to limit

**Mitigation**:
- Implement strict rate limiter (already done in DataFetcher)
- Use aggressive caching (30-60s TTL)
- Reduce watchlist to top 200 liquid symbols
- Stagger bot polling intervals
- Monitor API usage in real-time

**Fallback**:
- Temporarily disable lower-priority bots
- Increase polling intervals during peak times

### Risk 2: Increased Latency

**Risk**: 15-30s latency vs <1s Kafka
**Impact**: MEDIUM - Slower alerts
**Probability**: HIGH - Inherent to polling

**Mitigation**:
- Optimize polling to 5-15s intervals
- Use snapshot endpoint (most efficient)
- Implement smart filtering (skip inactive symbols)
- Accept latency tradeoff for simplicity gain

**Validation**:
- User feedback on acceptable latency
- Compare alert usefulness (15s delay still actionable?)

### Risk 3: Alert Quality Degradation

**Risk**: REST approach misses flow that Kafka catches
**Impact**: HIGH - Defeats bot purpose
**Probability**: MEDIUM - Volume delta algorithm may differ from Kafka

**Mitigation**:
- Parallel running phase (validate REST = Kafka quality)
- Fine-tune volume delta thresholds
- Implement comprehensive logging for comparison
- Test extensively before full cutover

**Validation**:
- Side-by-side comparison for 1 week
- Alert quality metrics (precision/recall)

### Risk 4: API Outages

**Risk**: Polygon API downtime = all bots down
**Impact**: HIGH - Complete system failure
**Probability**: LOW - Polygon has 99.9% uptime SLA

**Mitigation**:
- Implement circuit breaker (already done)
- Exponential backoff retry (already done)
- Health monitoring and alerting
- Maintain WebSocket as emergency backup option

**Fallback**:
- WebSocket bots as hot standby
- Status page monitoring
- Auto-recovery mechanisms

---

## ✅ Success Criteria

**Go/No-Go Decision Points**:

**After Phase 1 (Enhanced DataFetcher)**:
- ✅ Option chain snapshot retrieval working
- ✅ Flow detection algorithm functional
- ✅ Volume delta calculations accurate
- ✅ No performance regressions

**After Phase 2 (Updated Bots)**:
- ✅ All 7 bots posting alerts
- ✅ Alert quality matches Kafka baseline (±10%)
- ✅ No false positives
- ✅ Polling intervals stable

**After Phase 3 (Cleanup)**:
- ✅ Kafka dependencies removed
- ✅ All bots using REST versions
- ✅ Documentation updated
- ✅ Code review passed

**After Phase 4 (Testing)**:
- ✅ 24-hour stability test passed
- ✅ API usage within limits
- ✅ Memory usage < 300 MB
- ✅ Error rate < 1%
- ✅ Alert quality validated

**Final Go-Live Criteria**:
- ✅ All success criteria met
- ✅ User approves migration
- ✅ Rollback plan tested
- ✅ Monitoring in place
- ✅ Production deployment successful

---

## 📈 Expected Outcomes

**Operational Benefits**:
- 40% cost reduction ($100-300/month saved)
- Simpler architecture (1 data source vs 2)
- Easier debugging (no Kafka layers)
- Unified bot codebase
- Reduced operational overhead

**Technical Benefits**:
- Single DataFetcher for all data
- Consistent error handling
- Unified caching strategy
- Easier testing and development
- Better visibility into data flow

**Potential Drawbacks**:
- 5-30s latency increase (vs <1s Kafka)
- Higher API usage (requires optimization)
- More complex polling logic
- Risk of rate limiting (mitigated)

**Net Assessment**: ✅ **Benefits outweigh drawbacks for this use case**

---

## 🎯 Recommendation

**Proceed with unified REST architecture migration** with the following approach:

1. **Start with Phase 1**: Implement enhanced DataFetcher with option chain snapshots
2. **Validate thoroughly**: Test flow detection quality vs Kafka
3. **Parallel running**: Deploy REST bots alongside Kafka initially
4. **Gradual cutover**: Switch to REST after validation period
5. **Monitor closely**: Watch API usage, alert quality, system stability
6. **Maintain rollback**: Keep Kafka option available for 2 weeks

**Timeline**: 2-3 weeks from start to production cutover

**Next Step**: Get user approval and begin Phase 1 implementation

