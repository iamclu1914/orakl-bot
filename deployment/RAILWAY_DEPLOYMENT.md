# 🚂 Railway.app Deployment Guide - ORAKL Bot

**Railway.app is the EASIEST and BEST solution for Discord bots.**

## Why Railway?

✅ **Dead Simple**: Connect GitHub → Deploy (2 minutes)
✅ **Automatic Restarts**: Bot crashes? Restarts instantly
✅ **Built-in Monitoring**: See logs, metrics, health
✅ **True 24/7**: Never goes offline
✅ **Cost**: ~$5/month (first $5 free credit each month)
✅ **Perfect for Discord Bots**: Purpose-built for this

---

## Step-by-Step Deployment (10 minutes)

### 1. Create Railway Account

1. Go to https://railway.app
2. Click **"Start a New Project"**
3. Sign up with **GitHub** (required)

---

### 2. Push Your Bot to GitHub (if not already)

```bash
# In your ORAKL Bot directory
git init
git add .
git commit -m "Initial commit - ORAKL Bot v2.0"

# Create repo on GitHub, then:
git remote add origin https://github.com/YOUR_USERNAME/orakl-bot.git
git branch -M main
git push -u origin main
```

**⚠️ IMPORTANT**: Never commit your `.env` file!
Create `.gitignore`:

```
.env
.env.local
*.log
logs/
__pycache__/
```

---

### 3. Deploy to Railway

1. In Railway dashboard, click **"+ New Project"**
2. Select **"Deploy from GitHub repo"**
3. Choose your **orakl-bot** repository
4. Railway auto-detects Python and Dockerfile
5. Click **"Deploy Now"**

Railway will:
- Build Docker image (3-5 minutes first time)
- Start your bot automatically
- Assign a project URL (optional)

---

### 4. Add Environment Variables

Your bot needs secrets (API keys, tokens). Railway makes this easy:

1. In Railway project, click **"Variables"** tab
2. Add these variables (from your `.env` file):

```
DISCORD_BOT_TOKEN=your_discord_bot_token_here
DISCORD_WEBHOOK_URL=your_webhook_url_here
POLYGON_API_KEY=your_polygon_api_key_here
TZ=America/New_York
PYTHONUNBUFFERED=1
```

3. Click **"Add Variable"** for each
4. Railway auto-restarts with new variables

---

### 5. Verify Deployment

**Check Logs:**
1. Click **"Deployments"** tab
2. Click latest deployment
3. View live logs
4. Look for: `"ORAKL Enhanced Bot Starting..."`
5. Look for: `"✓ Enhanced auto-posting bots started successfully"`

**Check Discord:**
1. Go to your Discord server
2. Bot should show as **ONLINE**
3. Run: `ok-help`
4. Should respond instantly

---

### 6. Configure Auto-Deploy (Optional)

Every time you push to GitHub, Railway auto-deploys:

1. Make code changes locally
2. Commit and push:
   ```bash
   git add .
   git commit -m "Update bot features"
   git push
   ```
3. Railway auto-detects and deploys (2-3 minutes)

---

## Monitoring & Maintenance

### View Logs (Real-Time)
```
Railway Dashboard → Your Project → Deployments → View Logs
```

### Check Bot Health
Railway shows:
- **Status**: Running / Crashed
- **Uptime**: Hours online
- **Restarts**: Auto-restart count
- **Memory**: RAM usage
- **CPU**: CPU usage

### Restart Manually (if needed)
```
Railway Dashboard → Your Project → Settings → Restart
```

---

## Cost Breakdown

| Resource | Usage | Cost |
|----------|-------|------|
| **Base Plan** | Included | $5/month |
| **Compute** | ~0.1 vCPU | ~$2/month |
| **Memory** | ~500MB RAM | ~$1/month |
| **Network** | Minimal | ~$0.50/month |
| **Total** | Estimated | **~$5/month** |

**First Month**: FREE ($5 credit included)

---

## Troubleshooting

### Bot Shows "Crashed"

**Check logs for errors:**
```
Railway Dashboard → Deployments → Latest → Logs
```

**Common fixes:**
1. Missing environment variables
2. Invalid API keys
3. Python dependency issues

**Quick fix:** Restart from dashboard

### Bot Not Responding in Discord

1. **Check Railway status**: Should show "Running"
2. **Check logs**: Look for "Discord: CONNECTED"
3. **Verify token**: Check `DISCORD_BOT_TOKEN` variable
4. **Check intents**: Bot needs `Message Content Intent` enabled in Discord Developer Portal

### High Memory Usage

Railway limits: 512MB by default

**Optimize memory:**
```python
# In your config, reduce cache sizes
CACHE_MAX_SIZE = 100  # Instead of 1000
```

---

## Advanced Configuration

### Set Custom Domain (Optional)

1. Railway provides a `*.railway.app` URL
2. Add custom domain in **Settings → Domains**
3. Update DNS records

### Set Up Monitoring Alerts

1. Go to **Settings → Notifications**
2. Add webhook URL for alerts
3. Get notified when bot crashes

### Enable Auto-Scaling (Pro Plan)

Upgrade to Pro ($20/mo) for:
- Auto-scaling based on load
- Higher resource limits
- Priority support

---

## Why This is the BEST Solution

✅ **No PC Required**: Runs in cloud 24/7
✅ **Survives Sleep**: Your computer can sleep/shutdown
✅ **Auto-Recovery**: Restarts on crashes automatically
✅ **Easy Updates**: Push to GitHub → auto-deploy
✅ **Professional**: Same platform used by production apps
✅ **Monitoring**: Built-in logs and metrics
✅ **Secure**: Environment variables never in code

---

## Next Steps

After deployment:

1. ✅ **Test all commands** in Discord
2. ✅ **Monitor logs** for 24 hours
3. ✅ **Set up alerts** (optional)
4. ✅ **Turn off local PC** - bot stays online!

---

## Support

- **Railway Docs**: https://docs.railway.app
- **Railway Discord**: https://discord.gg/railway
- **Issue?**: Check logs first, then Railway support

---

**Your bots will now run 24/7 without your PC!** 🚀
