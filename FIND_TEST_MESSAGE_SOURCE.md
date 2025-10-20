# How to Find & Stop Test Messages in Discord

## The Problem
You're seeing test messages like:
```
🎯 System Alert
TEST - ⚪ Started
⏰ Timeframe: N/A
💰 Entry: $0.00
🎯 Target: $0.00
```

These are **NOT** from your ORAKL bot code.

## Find the Source

### Method 1: Check Discord Webhooks
1. Open Discord → Go to your server
2. Click **Server Settings** (⚙️ icon)
3. Go to **Integrations** → **Webhooks**
4. Look for all webhooks listed
5. Find any webhook you don't recognize or that says "TEST"
6. **Delete** or **Regenerate** it

### Method 2: Check Discord Bots
1. Open Discord → Go to your server
2. Click **Server Settings** → **Integrations** → **Bots and Apps**
3. Look for any bots you didn't add
4. Remove unauthorized bots

### Method 3: Check Webhook History
To see which webhook is sending the test messages:

1. In Discord, go to the channel receiving test messages
2. Right-click on a test message
3. Click **Copy Message Link**
4. Note the timestamp

Then check your Render logs at that exact time to see if your bot was running.

### Method 4: Disable Webhook Temporarily
To confirm which webhook is the culprit:

1. Go to Discord → Server Settings → Integrations → Webhooks
2. Click on your STRAT webhook
3. Click **Delete Webhook** (you can recreate it later)
4. Wait to see if test messages stop
5. If they stop, that webhook was compromised
6. Create a new webhook with a fresh URL

## Your Render Configuration

Since you're using Render, check these locations:

### 1. Render Environment Variables
```bash
# Go to: https://dashboard.render.com
# Select your service
# Click "Environment" tab
# Look for: STRAT_WEBHOOK

Current value should be:
STRAT_WEBHOOK=https://discord.com/api/webhooks/1427143775926353952/SGludMyVWxVwug_tdCiGNXeyjWqY1TlyGlIL24FBxfUn_xGn3lpeAPQMYjqW2_xJxAfW
```

### 2. Render Webhooks Section
```bash
# Go to: https://dashboard.render.com
# Select your service
# Click "Settings" tab
# Scroll to "Webhooks" section
# Check if there are any outgoing webhooks configured
```

### 3. Render Notification Settings
```bash
# Go to: https://dashboard.render.com
# Select your service
# Click "Settings" → "Notifications"
# Disable any Discord webhook notifications if present
```

## Update Your Webhook on Render

If you need to update the STRAT webhook:

1. **In Discord:**
   - Server Settings → Integrations → Webhooks
   - Delete the old webhook
   - Create a new webhook for your STRAT channel
   - Copy the new webhook URL

2. **In Render:**
   - Dashboard → Your Service → Environment
   - Find `STRAT_WEBHOOK`
   - Update with the new URL
   - Click **Save Changes**
   - Service will auto-redeploy

## Test After Changes

After making changes, monitor your Discord channel for 10-15 minutes to confirm test messages have stopped.

### What You SHOULD See (Real STRAT Signals)
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
```

### What You Should NOT See (Test Messages)
```
TEST - ⚪ Started
⏰ Timeframe: N/A
💰 Entry: $0.00
```

## Still Seeing Test Messages?

If you still see test messages after checking all the above:

### Nuclear Option: Regenerate All Webhooks
1. Create completely new webhooks for ALL bots
2. Update all webhook URLs in Render environment variables
3. The old compromised webhooks will be abandoned

### Contact Discord Support
If nothing works, the webhook might be compromised. Contact Discord support to report webhook abuse.

## Prevention

To prevent this in the future:

1. **Never share webhook URLs publicly** - They're like passwords
2. **Regenerate webhooks periodically** - Every 3-6 months
3. **Use different webhooks for each bot** - Isolates issues
4. **Monitor your Discord integrations** - Check monthly for unauthorized bots

---
*Updated: October 20, 2025*

