# WebSocket Implementation Status

## Current Issue

Polygon WebSocket has these limitations for free/starter tiers:
1. **Options WebSocket requires Premium subscription** ($299+/month)
2. **Free tier only has delayed stock data** (15-minute delay)
3. **Starter tier ($99/month) has real-time stocks but NO options**

## Alternative Solutions

### Option 1: Optimized REST API (RECOMMENDED FOR NOW)
Keep using REST API but optimize significantly:
- **Parallel chunking**: Process 10 symbols at a time (vs sequential)
- **Smart caching**: Cache stock prices for 60s to reduce API calls
- **Adaptive scanning**: Skip symbols with low volume during off-hours
- **Result**: 5-10x faster scans, no timeouts

### Option 2: Upgrade to Polygon Premium
- Cost: $299/month
- Benefit: Real-time options + stocks WebSocket streaming
- Instant alerts (<1s latency)

### Option 3: Alternative Data Provider
- **Tradier** (free tier): WebSocket for stocks + options
- **Alpaca** (free tier): WebSocket for stocks only
- **IBKR TWS API**: Real-time if you have funded account

## Index Whale Bot (REST Flow)

The updated `IndexWhaleBot` now uses Polygon’s REST endpoints (no WebSocket dependency) to
poll `SPY`, `QQQ`, and `IWM` every ~30 seconds. It reconstructs high-pressure flow using
`detect_unusual_flow()`, classifies patterns (continuation, flip, laddering, divergence), and pushes
alerts to `INDEX_WHALE_WEBHOOK`.

**Configuration**
- `INDEX_WHALE_WEBHOOK`
- `INDEX_WHALE_WATCHLIST` (defaults to `SPY,QQQ,IWM`)
- `INDEX_WHALE_INTERVAL` (seconds between scans, default `30`)
- `INDEX_WHALE_MIN_PREMIUM`, `INDEX_WHALE_MIN_VOLUME_DELTA`, `INDEX_WHALE_MAX_PERCENT_OTM`
- `INDEX_WHALE_OPEN_*` / `INDEX_WHALE_CLOSE_*` to control the trading session window (defaults 09:30 – 16:15 ET)

**Detection Criteria**
- Single-leg, ask-side trades (price at/near ask)
- Out-of-the-money contracts with `%OTM ≤ 0.5%`
- Day volume greater than open interest (`Vol > OI`)
- DTE ≥ 1 (built for 1–5 DTE scalps)
- Pattern tracker tags flips, laddering, continuation bursts, and flow/price divergence

`BotManager` launches the REST bot automatically alongside the other scanners—no Polygon premium
tier required.

## Recommendation

**If you are still on REST-only access**: keep using the optimized REST API until Polygon options streaming is available. The REST flow already:
1. Eliminates timeout issues
2. Runs 5–10× faster scans
3. Generates alerts within minutes
4. Costs $0 (uses existing Polygon API key)

Upgrade to Polygon Premium when you are ready for true real-time streaming across the full watchlist.

## Files Status

WebSocket files created but NOT usable without Premium subscription:
- `src/websocket_base.py`
- `src/bots/*_ws.py`
- `run_websocket_bots.py`

These remain in codebase for future upgrade when you get Premium tier.
