# Bot Stability Fixes - October 21, 2025

## Problem
Bots were permanently stopping after 10 consecutive timeout errors (600 seconds each), caused by:
1. STRAT bot scanning 403 stocks instead of configured 109
2. No auto-recovery mechanism after failures
3. Fixed timeout regardless of watchlist size

## Solutions Implemented

### 1. Fixed STRAT Bot Watchlist
- **File**: `src/bots/strat_bot.py`
- Added `self.watchlist` attribute to accept configured watchlist from BotManager
- Changed from hardcoded 403 stocks to configured watchlist (109 stocks)

### 2. Enhanced Error Tolerance
- **File**: `src/bots/base_bot.py`
- Increased max consecutive errors from 10 to 25
- Added adaptive timeout based on watchlist size (10s per stock minimum)
- Implemented auto-recovery mechanism with 3 retry attempts

### 3. Auto-Recovery System
- Bots now attempt to auto-restart after failures
- 1-minute cooldown between recovery attempts
- Maximum 3 recovery attempts before permanent stop
- Successful scan resets all error counters

## Expected Behavior
- Bots will be more resilient to temporary failures
- STRAT bot will scan 109 stocks like other bots
- Failed bots will attempt to recover automatically
- Timeouts adapt to watchlist size

## Deployment
Push to GitHub and Render will auto-deploy the fixes.
