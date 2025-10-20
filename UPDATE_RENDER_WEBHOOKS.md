# How to Update Webhooks on Render

## Important: Environment Variables on Render

Your `config.env` file is **correctly** ignored by git for security. This means you need to update the webhooks directly in Render's dashboard.

## 📝 Step-by-Step Guide

### 1. Log into Render
Go to: https://dashboard.render.com

### 2. Find Your Service
Click on your ORAKL bot service

### 3. Go to Environment Variables
Click **"Environment"** tab in the left sidebar

### 4. Update These Variables

Find and update each webhook variable:

| Variable Name | New Value |
|--------------|-----------|
| **DISCORD_WEBHOOK_URL** | `https://discord.com/api/webhooks/1429868655541223525/ZiQo-1odbEhng4gIbAXpe6EyTtN0BqFLu5f4Z4KfN8NolYeoXz7pmdn3bUlU6r4R-qy5` |
| **STRAT_WEBHOOK** | `https://discord.com/api/webhooks/1429696331202428959/2NdM5OlRS3hlO0f-VeLetMEIVreaQyNPV5WJzRN7i2P6ViCxI5Us2J1fx68JR-Ih21ZW` |

### 5. Add Missing Variables (if needed)

If `STRAT_WEBHOOK` doesn't exist, click **"Add Environment Variable"** and add:
- **Key**: `STRAT_WEBHOOK`
- **Value**: `https://discord.com/api/webhooks/1429696331202428959/2NdM5OlRS3hlO0f-VeLetMEIVreaQyNPV5WJzRN7i2P6ViCxI5Us2J1fx68JR-Ih21ZW`

### 6. Save Changes
Click **"Save Changes"** at the bottom

### 7. Automatic Redeploy
Render will automatically redeploy your service with the new webhooks (takes 2-5 minutes)

## 🔍 Verify Deployment

1. Go to **"Logs"** tab
2. Look for successful initialization:
   ```
   ✓ STRAT Pattern Bot → Channel ID: 1429696331202428959
   STRAT Pattern Scanner initialized
   ```

## 📋 All Webhook Variables to Check

Make sure all these are set in Render:

```env
# Main webhook
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/1429868655541223525/ZiQo-1odbEhng4gIbAXpe6EyTtN0BqFLu5f4Z4KfN8NolYeoXz7pmdn3bUlU6r4R-qy5

# Bot-specific webhooks
ORAKL_FLOW_WEBHOOK=(your webhook URL)
BULLSEYE_WEBHOOK=(your webhook URL)
SCALPS_WEBHOOK=(your webhook URL)
SWEEPS_WEBHOOK=(your webhook URL)
GOLDEN_SWEEPS_WEBHOOK=(your webhook URL)
DARKPOOL_WEBHOOK=(your webhook URL)
BREAKOUTS_WEBHOOK=(your webhook URL)
UNUSUAL_ACTIVITY_WEBHOOK=(your webhook URL)
STRAT_WEBHOOK=https://discord.com/api/webhooks/1429696331202428959/2NdM5OlRS3hlO0f-VeLetMEIVreaQyNPV5WJzRN7i2P6ViCxI5Us2J1fx68JR-Ih21ZW
```

## 🚀 Other Important Variables

Also ensure these are set:
```env
POLYGON_API_KEY=NnbFphaif6yWkufcTV8rOEDXRi2LefZN
BOT_NAME=ORAKL
STRAT_INTERVAL=300
```

## ✅ Why This Method?

- **Security**: Webhooks stay secret, not in your repository
- **Flexibility**: Update webhooks without code changes
- **Best Practice**: Environment-specific configurations stay in environment

## 📌 Pro Tips

1. **Copy from COPY_TO_RENDER.txt**: Your file has all the webhook URLs ready to copy
2. **Test After Deploy**: Use Discord to verify webhooks are working
3. **Keep Documentation**: Save webhook URLs in a secure password manager

---

**Important**: Never commit webhook URLs to your repository. Always use environment variables on your deployment platform!

*Last Updated: October 20, 2025*
