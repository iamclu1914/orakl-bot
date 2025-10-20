# How to Get Discord Webhook URLs

## 📍 Where to Create Webhooks in Discord

### Step 1: Open Discord Server Settings
1. Open Discord (desktop app or web)
2. Go to your server
3. Right-click on the server name (or click the dropdown arrow)
4. Click **"Server Settings"**

### Step 2: Navigate to Integrations
1. In the left sidebar, click **"Integrations"**
2. Click **"Webhooks"** or **"View Webhooks"**

### Step 3: Create a New Webhook
1. Click **"New Webhook"** button
2. Configure your webhook:
   - **Name**: Give it a descriptive name (e.g., "ORAKL Sweeps Bot")
   - **Channel**: Select which channel it should post to
   - **Avatar**: (Optional) Upload a custom avatar
3. Click **"Copy Webhook URL"** button
4. Click **"Save"** to save changes

## 🔗 Example Webhook URL Format
```
https://discord.com/api/webhooks/1429696331202428959/2NdM5OlRS3hlO0f-VeLetMEIVreaQyNPV5WJzRN7i2P6ViCxI5Us2J1fx68JR-Ih21ZW
```

## 📋 Creating Webhooks for Each Bot

You need separate webhooks for each bot. Here's a checklist:

### 1. Create These Channels First (if not already created)
- 📊 **#orakl-flow** - For repeat option signals
- 🎯 **#bullseye-alerts** - For AI intraday signals  
- ⚡ **#scalps** - For quick scalp setups
- 💰 **#sweeps** - For large option sweeps ($50K+)
- 👑 **#golden-sweeps** - For million dollar sweeps
- 🌊 **#darkpool** - For darkpool/block trades
- 📈 **#breakouts** - For stock breakouts
- 🔥 **#unusual-activity** - For volume surges
- 🎯 **#strat-alerts** - For STRAT patterns

### 2. Create a Webhook for Each Channel

For each channel:
1. Right-click the channel → **"Edit Channel"**
2. Go to **"Integrations"** → **"Webhooks"**
3. Click **"Create Webhook"**
4. Name it appropriately (e.g., "Sweeps Bot", "Golden Sweeps Bot")
5. Copy the webhook URL

### 3. Update Your Config File

Once you have all webhooks, update your `.env` file:

```env
# Main webhook (can be same as one of the others)
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/YOUR_WEBHOOK_HERE

# Individual Bot Webhooks
ORAKL_FLOW_WEBHOOK=https://discord.com/api/webhooks/YOUR_WEBHOOK_HERE
BULLSEYE_WEBHOOK=https://discord.com/api/webhooks/YOUR_WEBHOOK_HERE
SCALPS_WEBHOOK=https://discord.com/api/webhooks/YOUR_WEBHOOK_HERE
SWEEPS_WEBHOOK=https://discord.com/api/webhooks/YOUR_WEBHOOK_HERE
GOLDEN_SWEEPS_WEBHOOK=https://discord.com/api/webhooks/YOUR_WEBHOOK_HERE
DARKPOOL_WEBHOOK=https://discord.com/api/webhooks/YOUR_WEBHOOK_HERE
BREAKOUTS_WEBHOOK=https://discord.com/api/webhooks/YOUR_WEBHOOK_HERE
UNUSUAL_ACTIVITY_WEBHOOK=https://discord.com/api/webhooks/YOUR_WEBHOOK_HERE
STRAT_WEBHOOK=https://discord.com/api/webhooks/YOUR_WEBHOOK_HERE
```

## 🛡️ Security Best Practices

### DO:
- ✅ Keep webhook URLs private (treat like passwords)
- ✅ Use different webhooks for different bots
- ✅ Regenerate if you suspect compromise
- ✅ Delete unused webhooks

### DON'T:
- ❌ Share webhook URLs publicly
- ❌ Post them in public repos
- ❌ Use the same webhook for everything

## 🔄 Regenerating a Webhook

If a webhook is compromised or sending unwanted messages:
1. Go to Server Settings → Integrations → Webhooks
2. Find the webhook
3. Click **"Delete Webhook"**
4. Create a new one
5. Update your bot configuration

## 🧪 Testing Your Webhook

After creating, test it works:

```bash
# Windows PowerShell
$webhook = "YOUR_WEBHOOK_URL_HERE"
$payload = @{
    content = "Test message from ORAKL Bot setup!"
} | ConvertTo-Json

Invoke-RestMethod -Uri $webhook -Method Post -Body $payload -ContentType "application/json"
```

Or use the bot's test script:
```bash
cd "C:\ORAKL Bot"
python send_test_signal.py
```

## 📱 Mobile Discord App

You can also create webhooks on mobile:
1. Long press on the channel
2. Tap "Edit Channel"
3. Scroll to "Integrations"
4. Tap "Webhooks"
5. Create and copy URL

## 🎨 Pro Tips

1. **Use Clear Names**: Name webhooks after their bot (e.g., "ORAKL Sweeps Bot")
2. **Organize Channels**: Group trading channels in a category
3. **Set Permissions**: Limit who can view trading channels
4. **Use Icons**: Give each webhook a unique avatar for easy identification

## ❓ Troubleshooting

### "Unknown Webhook" Error
- Webhook was deleted
- URL is incorrect
- Missing part of the URL

### "Invalid Webhook Token"
- URL is incomplete
- Extra characters added
- Webhook was regenerated

### No Messages Appearing
- Check channel permissions
- Verify webhook is for correct channel
- Test with simple message first

---

**Need a test server?** Create a private Discord server just for testing your bots before going live!

*Last Updated: October 20, 2025*
