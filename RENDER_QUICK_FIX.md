# 🚨 RENDER QUICK FIX - START GETTING ALERTS NOW

## THE PROBLEM
Your bot is scanning 403 stocks and timing out. It NEVER completes a scan, so NO alerts are sent.

## THE FIX (5 minutes)

### Step 1: Go to Render Dashboard
https://dashboard.render.com → Your Service → Environment

### Step 2: Add/Update These Variables EXACTLY

```env
# CRITICAL - Reduce from 403 to 12 stocks
WATCHLIST=SPY,QQQ,AAPL,MSFT,NVDA,TSLA,AMD,META,GOOGL,AMZN,NFLX,BAC
WATCHLIST_MODE=WATCHLIST

# Your New Webhooks
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/1429868655541223525/ZiQo-1odbEhng4gIbAXpe6EyTtN0BqFLu5f4Z4KfN8NolYeoXz7pmdn3bUlU6r4R-qy5
STRAT_WEBHOOK=https://discord.com/api/webhooks/1429696331202428959/2NdM5OlRS3hlO0f-VeLetMEIVreaQyNPV5WJzRN7i2P6ViCxI5Us2J1fx68JR-Ih21ZW

# Lower Thresholds = More Alerts (for testing)
MIN_PREMIUM=1000
GOLDEN_MIN_PREMIUM=100000
SWEEPS_MIN_PREMIUM=10000
BULLSEYE_MIN_PREMIUM=1000
SCALPS_MIN_PREMIUM=500

# Lower Scores = More Alerts (for testing)
MIN_GOLDEN_SCORE=50
MIN_SWEEP_SCORE=45
MIN_BULLSEYE_SCORE=50
MIN_SCALP_SCORE=50
MIN_BREAKOUT_SCORE=50
MIN_DARKPOOL_SCORE=50
```

### Step 3: Click "Save Changes"
Render will auto-redeploy (takes 3-5 minutes)

## 🎯 WHAT HAPPENS NEXT

### Within 10 minutes:
1. Bot redeploys with 12 stocks (not 403)
2. First scan completes in 30 seconds (not 10+ minutes)
3. Alerts start posting to Discord

### You'll See in Logs:
```
✓ Scanning 12 symbols (not 403)
✓ Scan completed successfully
✓ Found X signals matching criteria
✓ Alert sent to Discord
```

## 📊 EXPECTED ALERTS

With these TEST thresholds, expect:
- **5-20 alerts in first hour** (lower quality for testing)
- **Immediate feedback** that bot is working
- **All 9 bots posting** to their channels

## ✅ VERIFY IT'S WORKING

1. **Render Logs**: No more timeout errors
2. **Discord**: Alerts start appearing
3. **Health Checks**: All pass after first scan

## 🔧 AFTER TESTING (Optional)

Once you confirm alerts are working, you can:
1. Gradually increase thresholds for quality
2. Add more stocks to watchlist (max 50 recommended)
3. Fine-tune based on alert frequency

## 🚨 IF STILL NO ALERTS AFTER 15 MINUTES

Check Discord webhook permissions:
- Webhooks not deleted/regenerated
- Bot has permission to post
- Channels exist and are visible

---

**THIS WILL FIX YOUR BOT IN 5 MINUTES**
