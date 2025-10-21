# Render 1-Minute Shutdown Fix

## Problem
Background Worker is being killed by Render with SIGTERM after ~1 minute, despite being configured correctly.

## Changes Made

### 1. Fixed BLOCK Ticker Issue
- Changed BLOCK back to SQ (Polygon still uses SQ for Block/Square)
- Update your Render environment WATCHLIST to use SQ not BLOCK

### 2. Added Heartbeat Mechanism
- Aggressive heartbeat every 10 seconds for first 2 minutes
- Prevents Render from thinking service is inactive
- Shows memory usage and uptime

### 3. Check Render Settings
Please check these on your Render dashboard:

1. **Service Settings**:
   - Confirm it shows "Background Worker" not "Web Service"
   - Check for any "Start Command Timeout" setting
   - Look for any "Health Check" settings that shouldn't be there

2. **Logs Tab**:
   - Look for any Render-specific error messages
   - Check if there's a message like "No output detected" before shutdown

3. **Metrics Tab**:
   - Confirm memory is under limit
   - Check CPU usage

## Expected Behavior After Deploy

You should see:
```
💓 Bot heartbeat #1 - Service is active and monitoring 8 bots
💓 Bot heartbeat #2 - Service is active and monitoring 8 bots
Memory: XXX.XMB | Status: Operational | Uptime: 20s
...continuing every 10 seconds for 2 minutes, then every 30 seconds
```

## If Still Shutting Down

1. **Check Render Service Type Again**:
   - Some users accidentally have TWO services (one Web, one Worker)
   - Make sure you're looking at the right one

2. **Try Creating Fresh Background Worker**:
   - Delete current service
   - Create new one explicitly as "Background Worker"
   - Copy all environment variables

3. **Contact Render Support**:
   - Show them the 1-minute SIGTERM issue
   - Ask if there's a hidden timeout for Background Workers
