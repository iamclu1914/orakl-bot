# CRITICAL Performance Fix - Concurrent Scanning

## Problem
Bots were timing out after 18+ minutes because they were scanning 109 stocks **sequentially**:
- 109 stocks × ~10 seconds each = 1090 seconds (18+ minutes)
- This exceeded all timeouts and crashed the service
- Service was restarting every 1-2 minutes

## Solution: Concurrent Processing
Implemented parallel scanning for all bots:

### 1. Base Bot Enhancement (`src/bots/base_bot.py`)
- Added default concurrent `scan_and_post()` implementation
- Processes stocks in chunks of 20 concurrently
- Small delays between chunks to avoid rate limits
- Safe error handling per symbol

### 2. Updated All Bots to Use Concurrent Scanning
- ✅ Orakl Flow Bot
- ✅ Darkpool Bot  
- ✅ Breakouts Bot
- ✅ Golden Sweeps Bot
- ✅ Sweeps Bot
- ✅ Scalps Bot (already had concurrent implementation)
- ✅ Bullseye Bot (already had concurrent implementation)

### 3. Adjusted Timeouts
- Old: 109 × 10s = 1090s timeout
- New: 6 chunks × 30s + buffer = 240s timeout
- With concurrent processing, scans complete in 2-3 minutes instead of 18+

## Performance Improvement
- **Before**: 18+ minutes per scan (sequential)
- **After**: 2-3 minutes per scan (concurrent)
- **Speedup**: ~6-9x faster

## Implementation Details
Each bot now:
1. Splits watchlist into chunks of 20 symbols
2. Processes each chunk concurrently
3. Waits 0.5s between chunks
4. Collects all signals
5. Posts signals after scan completes

## Deployment
This is a CRITICAL fix that will prevent the service from crashing.
