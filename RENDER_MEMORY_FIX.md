# Render Background Worker Shutdown Fix

## Problem
Your Background Worker is being killed by Render after ~1 minute with SIGTERM (signal 15).

## Root Cause
Most likely hitting the **512MB memory limit** on Render's Starter plan when scanning 109 stocks concurrently.

## Solutions

### 1. Immediate Fix - Reduce Memory Usage
We've already:
- Reduced concurrent chunk size from 20 to 10
- Added memory monitoring

### 2. Update Environment Variable
You still have "SQ" in your watchlist which should be "BLOCK":
1. Go to https://dashboard.render.com
2. Click your orakl-bot service
3. Go to Environment tab
4. Find WATCHLIST variable
5. Change "SQ" to "BLOCK"
6. Save and **Manually Deploy**

### 3. Monitor Memory Usage
After deployment, check logs for:
- "Memory usage before bot start: XXX.XMB"
- "Memory usage after bot start: XXX.XMB"

If it's approaching 512MB, that's the issue.

### 4. If Memory is the Issue
Options:
- Reduce watchlist size (from 109 to ~50-75 stocks)
- Upgrade to Render Starter Plus (2GB memory)
- Further reduce concurrent chunk size to 5

### 5. Check Render Dashboard
Look for any error messages or warnings about:
- Memory limit exceeded
- CPU limit exceeded
- Other resource constraints
