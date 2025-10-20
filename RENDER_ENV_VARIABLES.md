# Render Environment Variables - Complete List

## ✅ Local Bot: STOPPED
## 📍 Only Render Should Run

Update these environment variables in your Render dashboard to match your local configuration:

## 🔗 Webhook URLs

```env
# Main webhook (Spidey Bot)
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/1429868655541223525/ZiQo-1odbEhng4gIbAXpe6EyTtN0BqFLu5f4Z4KfN8NolYeoXz7pmdn3bUlU6r4R-qy5

# Individual Bot Webhooks
SWEEPS_WEBHOOK=https://discord.com/api/webhooks/1427361658761777287/vloziMHuypGrjwv8vxd72ySfzTblc9Nf1OHkkKAkUI81IqNPRym0FgjPDQGzYfwiNyC8
GOLDEN_SWEEPS_WEBHOOK=https://discord.com/api/webhooks/1427361801443741788/hXDZQd4hce8-Ph_GKKxFGTzE8EHzSZP0S-xTjxa5lXAc2LoqofGebkk924PbKKXw4FBN
SCALPS_WEBHOOK=https://discord.com/api/webhooks/1427361954850144419/z2aub0kyJHLqz3LLKLOL_CHw7_PaZcJqyiPg3BYp_wW3M3uFVJI0Gx9qsC9a4R7sliH9
BULLSEYE_WEBHOOK=https://discord.com/api/webhooks/1427362052753850549/NJBVniyzWQHrc_M6mZ2_19fQjNn_iVEpaMNDjhbYsGuqP6dlElDU58QH-MgfpJ7UE6ip
BREAKOUTS_WEBHOOK=https://discord.com/api/webhooks/1427362209524355133/eQZmCzobqcMtyuXDZox3gYnSGZET9BKefWrQw64rw5Po0cCOEpjpUFCEBl1fa5VDOJ_B
DARKPOOL_WEBHOOK=https://discord.com/api/webhooks/1427156966979010663/LQ-OzXtrj3WifaYADAWnVb9IzHbFhCcUxUmPTdylqWFSGJIz7Rwjwbl-o-B-n-7-VfkF
ORAKL_FLOW_WEBHOOK=https://discord.com/api/webhooks/1427156966979010663/LQ-OzXtrj3WifaYADAWnVb9IzHbFhCcUxUmPTdylqWFSGJIz7Rwjwbl-o-B-n-7-VfkF
UNUSUAL_ACTIVITY_WEBHOOK=https://discord.com/api/webhooks/1427372929099894794/xyAqCfHmarR92mr22p6MttN-4c-kBC8rYL_MZJw61a252Z9WsHBFuSu2iQY0bKK0lls_
STRAT_WEBHOOK=https://discord.com/api/webhooks/1429696331202428959/2NdM5OlRS3hlO0f-VeLetMEIVreaQyNPV5WJzRN7i2P6ViCxI5Us2J1fx68JR-Ih21ZW
```

## 💰 Premium Thresholds (HIGH QUALITY)

```env
# Base thresholds
MIN_PREMIUM=10000

# Bot-specific premiums
GOLDEN_MIN_PREMIUM=1000000
SWEEPS_MIN_PREMIUM=50000
BULLSEYE_MIN_PREMIUM=5000
SCALPS_MIN_PREMIUM=2000
DARKPOOL_MIN_BLOCK_SIZE=10000
```

## 📊 Score Thresholds (HIGH QUALITY)

```env
MIN_GOLDEN_SCORE=65
MIN_SWEEP_SCORE=60
MIN_DARKPOOL_SCORE=60
MIN_BULLSEYE_SCORE=70
MIN_SCALP_SCORE=65
MIN_BREAKOUT_SCORE=65
MIN_UNUSUAL_VOLUME_SCORE=65
```

## ⏱️ Scan Intervals

```env
GOLDEN_SWEEPS_INTERVAL=60
SWEEPS_INTERVAL=60
SCALPS_INTERVAL=60
BULLSEYE_INTERVAL=60
UNUSUAL_VOLUME_INTERVAL=60
DARKPOOL_INTERVAL=90
BREAKOUTS_INTERVAL=120
TRADY_FLOW_INTERVAL=120
STRAT_INTERVAL=300
```

## 🔍 Other Important Settings

```env
# Volume settings
MIN_VOLUME=100
MIN_VOLUME_RATIO=3.0
MIN_ABSOLUTE_VOLUME=1000000
BREAKOUT_MIN_VOLUME_SURGE=1.5

# Success and repeat thresholds
SUCCESS_RATE_THRESHOLD=0.65
REPEAT_SIGNAL_THRESHOLD=3
UNUSUAL_VOLUME_MULTIPLIER=3

# Watchlist
WATCHLIST=SPY,QQQ,AAPL,MSFT,NVDA,TSLA,AMD,META,GOOGL,AMZN,NFLX,BAC
```

## 📋 How to Update on Render

1. **Go to**: https://dashboard.render.com
2. **Click**: Your ORAKL service
3. **Navigate to**: Environment tab
4. **For each variable above**:
   - Find the variable (or click "Add Environment Variable")
   - Update the value
   - Click save icon
5. **Click**: "Save Changes" at the bottom
6. **Result**: Render will auto-redeploy with new settings

## 🎯 Expected Results After Update

With these HIGH QUALITY thresholds:
- **Fewer alerts** (only the best signals)
- **Higher win rate potential**
- **Less noise to filter**
- **Institutional-grade signals only**

### Daily Alert Expectations:
- Golden Sweeps: 0-2 per day
- Regular Sweeps: 2-5 per day
- Darkpool: 2-5 per day
- Bullseye: 2-6 per day
- Scalps: 5-15 per day
- STRAT: 0-3 per day
- **Total: 15-40 quality signals/day**

## ✅ Verification

After updating and redeployment:
1. Check logs for: "Configuration validated successfully"
2. Verify thresholds show correctly:
   ```
   Min Premium: $10,000
   Golden Sweeps: $1,000,000 (Score: 65)
   Sweeps: $50,000 (Score: 60)
   ```

## 🚫 Local Bot Status

- **Local bot**: ✅ STOPPED (no longer running)
- **Render bot**: 🟢 RUNNING (only instance)

This prevents:
- Duplicate alerts
- Conflicting signals
- Wasted API calls
- Confusion about which bot sent what

---

**Important**: Update ALL variables listed above to ensure Render matches your local high-quality configuration!

*Last Updated: October 20, 2025*
