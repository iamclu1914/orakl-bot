# Render SIGTERM Analysis - October 21, 2025

## Issue: Partial SIGTERM at ~1 minute

### Observed Behavior:
1. Bot starts successfully
2. After ~58 seconds: "Received signal 15, shutting down..."
3. All bot tasks stop
4. BUT: Main process and heartbeat continue running!

### Possible Causes:

#### 1. Memory Limit (Most Likely)
- Render's free tier has a 512MB memory limit
- Bot using ~186MB initially, but may spike during concurrent operations
- Render sends SIGTERM when approaching memory limit

#### 2. CPU Throttling
- Free tier has CPU limits
- Initial burst of all bots scanning might trigger throttling

#### 3. Deployment Configuration
- Render might be misinterpreting the service type
- Could be treating it as a cron job with 1-minute timeout

### Evidence:
- The heartbeat continues after SIGTERM = main process not killed
- Only bot tasks terminated = selective shutdown
- Consistent ~1 minute timing = automated trigger

### Solutions to Try:

#### 1. Reduce Initial Load
- Stagger bot startups instead of all at once
- Start with fewer bots initially

#### 2. Monitor Memory
- Add more detailed memory logging
- Check for memory spikes during startup

#### 3. Contact Render Support
- This behavior is unusual for a Background Worker
- May need clarification on service limits

#### 4. Upgrade Render Plan
- Paid plans have higher memory/CPU limits
- No artificial timeouts on paid tiers
