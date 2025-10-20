# Update STRAT Webhook on Render

## ✅ What I've Done

Updated your new STRAT webhook in all configuration files:
- ✅ `config.env` - Local configuration
- ✅ `COPY_TO_RENDER.txt` - Render deployment reference
- ✅ `RENDER_WEBHOOKS.md` - Documentation

**New STRAT Webhook:**
```
https://discord.com/api/webhooks/1429696331202428959/2NdM5OlRS3hlO0f-VeLetMEIVreaQyNPV5WJzRN7i2P6ViCxI5Us2J1fx68JR-Ih21ZW
```

**Webhook Name:** Strat Alert  
**Channel ID:** 1427143747942088784

## 🚀 Update on Render (IMPORTANT)

Since you're using Render, you need to update the environment variable there:

### Step 1: Log into Render
Go to: https://dashboard.render.com

### Step 2: Find Your Service
1. Click on your ORAKL bot service (web service or background worker)

### Step 3: Update Environment Variable
1. Click **"Environment"** tab on the left
2. Find the variable: `STRAT_WEBHOOK`
3. Click the **"Edit"** button (pencil icon)
4. Replace the old value with:
   ```
   https://discord.com/api/webhooks/1429696331202428959/2NdM5OlRS3hlO0f-VeLetMEIVreaQyNPV5WJzRN7i2P6ViCxI5Us2J1fx68JR-Ih21ZW
   ```
5. Click **"Save Changes"**

### Step 4: Redeploy (Automatic)
- Render will automatically redeploy your service after saving
- This takes 2-5 minutes
- You'll see the deployment progress in the **"Events"** tab

### Step 5: Verify Deployment
Check the logs to confirm:
1. Go to **"Logs"** tab
2. Look for:
   ```
   ✓ STRAT Pattern Bot → Channel ID: 1429696331202428959
   STRAT Pattern Scanner initialized
   STRAT Pattern Scanner started with dynamic scan intervals
   ```

## 🎯 Why This Fixes the Test Messages

Your **old webhook** was somehow sending test messages. Possible causes:
- Webhook URL was exposed/compromised
- Discord integration testing feature
- Render notification system using it

Your **new webhook** is:
- ✅ Fresh and unused
- ✅ Named "Strat Alert" specifically for STRAT patterns
- ✅ Not connected to any external test systems

Once updated on Render, only your ORAKL bot will use this webhook, and you'll only see real STRAT pattern alerts.

## 📊 What You'll See Next

After deployment, your STRAT bot will send alerts like this:

### Example: 3-2-2 Reversal
```
🎯 3-2-2 Reversal - AAPL
Bullish setup detected

📊 Timeframe: 60min
📍 Entry: $175.50
🎯 Target: $180.25
🛑 Stop: $173.25
💰 R:R: 2.00
🎲 Confidence: 75%

Please always do your own due diligence on top of these trade ideas.

STRAT Pattern Scanner • 2025-10-20 10:01:00 EST
```

### Example: 2-2 Reversal
```
🎯 2-2 Reversal - SPY
Bearish setup detected

📊 Timeframe: 4hour
📍 Entry: $450.00
🎯 Target: $445.00
🛑 Stop: $452.50
💰 R:R: 2.00
🎲 Confidence: 68%

Please always do your own due diligence on top of these trade ideas.

STRAT Pattern Scanner • 2025-10-20 08:15:00 EST
```

### Example: 1-3-1 Miyagi
```
🎯 1-3-1 Miyagi - TSLA
Bullish setup detected

📊 Timeframe: 12hour
📍 Entry: $250.00
🎯 Target: $260.00
🛑 Stop: $245.00
💰 R:R: 2.00
🎲 Confidence: 72%
⚙️ Setup: 1-3-1 2D (Fade)

Please always do your own due diligence on top of these trade ideas.

STRAT Pattern Scanner • 2025-10-20 16:01:00 EST
```

## ⏰ When STRAT Bot Sends Alerts

Your bot scans 24/7 but only alerts during these windows:

| Pattern | Alert Window | Frequency |
|---------|-------------|-----------|
| **3-2-2 Reversal** | 10:01 AM EST | Once daily (if pattern detected) |
| **2-2 Reversal** | 8:01-9:29 AM EST | When pullback confirmed |
| **1-3-1 Miyagi** | 4:01 AM or 4:01 PM EST | Twice daily (if pattern detected) |

## ✅ Quick Checklist

- [ ] Update `STRAT_WEBHOOK` on Render
- [ ] Save changes (triggers auto-redeploy)
- [ ] Wait 2-5 minutes for deployment
- [ ] Check logs for successful initialization
- [ ] Monitor Discord channel for new alerts
- [ ] Confirm no more test messages appear

## 🔒 Security Tip

**Never share your webhook URLs publicly!** They work like passwords. If you accidentally expose a webhook:
1. Delete it in Discord (Server Settings → Integrations → Webhooks)
2. Create a new webhook
3. Update the URL on Render

---

**Need Help?**

If you see any issues after updating:
1. Check Render logs for errors
2. Verify the webhook URL was copied correctly (no extra spaces)
3. Test the webhook manually using the Discord API

**Current Status:** ✅ Local config updated, ready for Render deployment

*Last Updated: October 20, 2025*

