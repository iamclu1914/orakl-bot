# Render Resource Optimization

## Changes Made to Prevent SIGTERM

### 1. Staggered Bot Startup
- Added 5-second delays between starting each bot
- Prevents all 8 bots from scanning simultaneously at startup
- Reduces initial CPU/memory spike

### 2. Enhanced Signal Logging
- Added detailed logging when SIGTERM is received
- Logs memory usage and uptime at shutdown
- Helps diagnose if it's a resource limit issue

### 3. Previously Implemented
- Concurrent scanning in chunks of 10 symbols
- Aggressive heartbeat mechanism
- Auto-recovery on errors

## Expected Behavior
1. Bots start one by one with 5-second gaps
2. Initial resource usage spread over ~40 seconds
3. No simultaneous scanning spike
4. Better signal handling visibility

## If SIGTERM Persists

### Option 1: Reduce Active Bots
Set environment variables to disable some bots:
```
GOLDEN_SWEEPS_INTERVAL=0  # Disables Golden Sweeps Bot
BULLSEYE_INTERVAL=0       # Disables Bullseye Bot
```

### Option 2: Increase Scan Intervals
Double all intervals to reduce load:
```
GOLDEN_SWEEPS_INTERVAL=240
SWEEPS_INTERVAL=360
SCALPS_INTERVAL=240
```

### Option 3: Use Smaller Watchlist
Change to STATIC mode with fewer symbols:
```
WATCHLIST_MODE=STATIC
WATCHLIST=SPY,QQQ,AAPL,MSFT,NVDA,TSLA,AMD,META,GOOGL,AMZN
```

### Option 4: Upgrade Render
- Paid plans have no resource restrictions
- $7/month Starter plan includes 512MB RAM guaranteed
- No artificial timeouts
