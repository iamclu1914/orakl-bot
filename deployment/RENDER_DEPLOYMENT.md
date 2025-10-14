# 🎨 Render.com Deployment Guide - ORAKL Bot

**Complete guide for deploying your Discord bot to Render for 24/7 operation.**

---

## ⚠️ IMPORTANT: Plan Selection

**Render has TWO plans for background workers:**

| Plan | Cost | Behavior | Suitable for 24/7? |
|------|------|----------|-------------------|
| **Free** | $0/mo | Spins down after 15 min inactivity | ❌ **NO** - Not suitable! |
| **Starter** | $7/mo | Always running, never sleeps | ✅ **YES** - Perfect! |

**For 24/7 options scanning, you MUST use the Starter plan ($7/mo).**

Free tier spins down = your bots go offline = missed opportunities.

---

## Step-by-Step Deployment (15 minutes)

### Prerequisites

✅ Render account (you already have this)
✅ GitHub account
✅ Your bot code in a Git repository

---

## Part 1: Prepare Your Repository

### 1.1 Push Code to GitHub (if not already)

```bash
# In your ORAKL Bot directory
cd "C:\ORAKL Bot"

# Initialize git (if not already)
git init

# Create .gitignore (IMPORTANT - never commit secrets!)
echo ".env
.env.local
*.log
logs/
__pycache__/
.vscode/
*.pyc
node_modules/
ecosystem.config.js
deployment/prevent_sleep.ps1
deployment/restore_sleep.ps1
deployment/wake_recovery.ps1
deployment/setup_task_scheduler.ps1
BOT_FIXED_STABLE.txt" > .gitignore

# Add files
git add .

# Commit
git commit -m "Deploy ORAKL Bot to Render"

# Create repo on GitHub, then push
git remote add origin https://github.com/YOUR_USERNAME/orakl-bot.git
git branch -M main
git push -u origin main
```

### 1.2 Verify Required Files

Make sure these files exist in your repository:

✅ `main.py` (entry point)
✅ `requirements.txt` (dependencies)
✅ `render.yaml` (already created - Render config)
✅ `.gitignore` (prevents committing secrets)

---

## Part 2: Deploy to Render

### 2.1 Create New Web Service

1. **Log into Render**: https://dashboard.render.com
2. Click **"New +"** → Select **"Background Worker"**
   - ⚠️ **NOT "Web Service"** - Discord bots are background workers!
3. Click **"Build and deploy from a Git repository"**
4. Click **"Connect GitHub"** (if not already connected)
5. Find and select your **orakl-bot** repository
6. Click **"Connect"**

### 2.2 Configure Service

**On the configuration page, fill in:**

| Field | Value |
|-------|-------|
| **Name** | `orakl-bot` (or any name you prefer) |
| **Region** | Choose closest to you (US/EU) |
| **Branch** | `main` |
| **Runtime** | **Python 3** (auto-detected) |
| **Build Command** | `pip install -r requirements.txt` |
| **Start Command** | `python -u main.py` |

**⚠️ CRITICAL: Plan Selection**

Scroll down to **"Plan"**:
- **DO NOT** select "Free" (your bot will sleep!)
- **SELECT**: **"Starter" ($7/month)** ✅

### 2.3 Add Environment Variables

**Before clicking "Create", scroll down to "Environment Variables":**

Click **"Add Environment Variable"** and add each of these:

| Key | Value | Where to Get |
|-----|-------|--------------|
| `DISCORD_BOT_TOKEN` | `your_token_here` | Copy from your local `.env` file |
| `DISCORD_WEBHOOK_URL` | `your_webhook_here` | Copy from your local `.env` file |
| `POLYGON_API_KEY` | `your_api_key_here` | Copy from your local `.env` file |
| `TZ` | `America/New_York` | Timezone (adjust if needed) |
| `PYTHONUNBUFFERED` | `1` | Ensures logs appear in real-time |

**How to copy from your local .env:**

```bash
# Open your local .env file
notepad "C:\ORAKL Bot\.env"

# Copy each value to Render dashboard
```

### 2.4 Deploy

1. **Double-check**:
   - ✅ Plan: **Starter** ($7/month)
   - ✅ All environment variables added
   - ✅ Start command: `python -u main.py`

2. Click **"Create Background Worker"**

3. **Render will now**:
   - Clone your GitHub repository
   - Install Python dependencies (~2-3 minutes)
   - Start your bot
   - Keep it running 24/7

---

## Part 3: Verify Deployment

### 3.1 Check Build Logs

1. In Render dashboard, click your service (`orakl-bot`)
2. Click **"Logs"** tab
3. Watch build process:

**Expected output:**
```
Building...
Installing dependencies from requirements.txt
✓ Successfully installed discord.py, pandas, matplotlib...
Starting service...
ORAKL Enhanced Bot Starting...
✓ Discord bot connected as ORAKL AI#3274
✓ Enhanced auto-posting bots started successfully
Active bots: 8
```

**Build time**: 2-5 minutes (first time)

### 3.2 Verify Bot Online

1. **Go to Discord**
2. Check bot status → Should show **ONLINE** 🟢
3. Run command: `ok-help`
4. Should respond instantly

**If bot is NOT online:**
- Check Render logs for errors
- Verify environment variables are correct
- Ensure `DISCORD_BOT_TOKEN` is valid

### 3.3 Test Commands

```
ok-help          → Shows all commands
ok-topflow       → Real-time flow data
ok-srlevels SPY  → Chart generation test
```

All commands should work immediately.

---

## Part 4: Monitoring & Maintenance

### 4.1 View Live Logs

**Render Dashboard → Your Service → Logs**

Real-time logs show:
- Bot startup messages
- Discord connection status
- Auto-posting bot activity
- Command executions
- Any errors or warnings

**Filter logs:**
- Search box at top-right
- Search for "ERROR", "WARNING", specific commands, etc.

### 4.2 Check Service Health

**Render Dashboard → Your Service → Overview**

Shows:
- **Status**: Running / Deploying / Failed
- **Uptime**: Hours since last restart
- **Memory Usage**: RAM consumption
- **CPU Usage**: Processing load
- **Last Deploy**: When last updated

### 4.3 Restart Service (If Needed)

**Manual restart:**
1. Click **"Manual Deploy"** → **"Clear build cache & deploy"**
2. Or, in top-right: **Settings** → **"Restart Service"**

**Automatic restarts:**
Render automatically restarts if your bot crashes.

---

## Part 5: Automatic Deployments

### 5.1 Setup Auto-Deploy from GitHub

**Every time you push to GitHub, Render auto-deploys:**

1. Make code changes locally:
   ```bash
   cd "C:\ORAKL Bot"
   # Edit your files...
   ```

2. Commit and push:
   ```bash
   git add .
   git commit -m "Update bot features"
   git push
   ```

3. **Render automatically:**
   - Detects the push
   - Rebuilds your bot
   - Deploys new version
   - Zero downtime (using your old bot until new one is ready)

**Time**: ~2-3 minutes from push to live

### 5.2 Disable Auto-Deploy (Optional)

If you want manual control:

1. **Settings** → **"Build & Deploy"**
2. Toggle **"Auto-Deploy"** → OFF
3. Click **"Manual Deploy"** when ready

---

## Part 6: Cost Management

### 6.1 Current Costs

**Starter Plan**: $7/month

Includes:
- 512 MB RAM
- 0.5 CPU
- Unlimited builds
- Always-on (24/7)
- Automatic restarts
- Build cache

**Billing**: Monthly, billed on anniversary date

### 6.2 Monitor Usage

**Render Dashboard → Your Service → Metrics**

Check:
- **Memory**: Should stay <400MB (you have 512MB)
- **CPU**: Typically <20% average
- **Bandwidth**: Minimal for Discord bots

**If memory exceeds 512MB:**
- Optimize cache sizes in config
- Or upgrade to next plan ($20/mo for 2GB)

### 6.3 Optimize Costs

**Tips to keep costs at $7/mo:**

1. **One service only**: Run all bots in one process (you already do this)
2. **Efficient caching**: Use TTL caching (you already do this)
3. **Monitor logs**: Catch memory leaks early
4. **Clean deployments**: Remove unused dependencies

---

## Part 7: Troubleshooting

### Bot Shows "Deploy Failed"

**Check build logs:**
- **Logs** tab → Find error message
- Common issues:
  - Missing dependencies in `requirements.txt`
  - Python syntax errors
  - Invalid `main.py` path

**Fix:**
1. Fix error locally
2. Test: `python main.py`
3. Commit and push: `git add . && git commit -m "Fix" && git push`
4. Render auto-deploys fixed version

### Bot Shows "Running" but Offline in Discord

**Check:**

1. **Environment variables**:
   - Go to **Settings** → **"Environment"**
   - Verify `DISCORD_BOT_TOKEN` is correct
   - No extra spaces or quotes

2. **Logs for errors**:
   ```
   Look for:
   "discord.errors.LoginFailure"
   "Improper token has been passed"
   ```

3. **Discord Developer Portal**:
   - Verify bot token is valid
   - Check "Message Content Intent" is enabled

**Fix:**
- Update environment variable in Render
- Render auto-restarts with new config

### High Memory Usage / Service Restarting

**Symptoms:**
- Service randomly restarts
- Logs show "Out of memory"

**Optimize:**

1. **Reduce cache sizes** in `src/config.py`:
   ```python
   CACHE_MAX_SIZE = 50  # Instead of 100+
   ```

2. **Disable unused features**:
   - Comment out unused bots in main.py

3. **Upgrade plan** (if needed):
   - **Next tier**: $20/mo for 2GB RAM

### Slow Response Times

**If commands take >5 seconds:**

1. **Check Polygon API**:
   - Verify API key is valid
   - Check rate limits

2. **Check Render region**:
   - Use region closest to you/users
   - Change in **Settings** → **"Region"**

3. **Optimize queries**:
   - Enable caching (already implemented)
   - Reduce API calls per command

---

## Part 8: Advanced Configuration

### 8.1 Custom Domain (Optional)

If you want a web dashboard:

1. Upgrade to **Web Service** (instead of Background Worker)
2. Add health check endpoint in Python
3. Configure custom domain in Render

**Not required for Discord bots.**

### 8.2 Database Integration (If Needed)

**If you want to store data:**

1. **Render Dashboard** → **"New +"** → **"PostgreSQL"**
2. Create free PostgreSQL database
3. Copy connection string
4. Add to environment variables:
   ```
   DATABASE_URL=postgresql://...
   ```

### 8.3 Multiple Environments

**Run separate dev/prod bots:**

1. Create two services:
   - `orakl-bot-dev` (branch: `dev`)
   - `orakl-bot-prod` (branch: `main`)

2. Use different Discord tokens for each

---

## Part 9: Comparison with Other Platforms

| Feature | Render | Railway | DigitalOcean VPS |
|---------|--------|---------|-----------------|
| **Cost** | $7/mo | $5/mo | $6/mo |
| **Setup Time** | 15 min | 10 min | 60 min |
| **Difficulty** | ⭐ Easy | ⭐ Easy | ⭐⭐ Medium |
| **Auto-Deploy** | ✅ Yes | ✅ Yes | ❌ Manual |
| **Logs** | ✅ Built-in | ✅ Built-in | ⚠️ Manual |
| **Restart** | ✅ Auto | ✅ Auto | ⚠️ Manual |
| **Free Tier** | ⚠️ Sleeps | ✅ $5 credit/mo | ❌ None |

**Render Advantages:**
- ✅ Simple deployment
- ✅ Excellent documentation
- ✅ Great for Discord bots
- ✅ Automatic SSL (if using web service)

**Render Disadvantages:**
- ❌ Slightly more expensive than Railway
- ❌ Free tier not suitable for 24/7

---

## Quick Reference Commands

### Update Bot Code

```bash
# On your local PC
cd "C:\ORAKL Bot"
# Make changes...
git add .
git commit -m "Update features"
git push

# Render auto-deploys in 2-3 minutes
```

### View Logs

```
Render Dashboard → Your Service → Logs
```

### Restart Service

```
Render Dashboard → Your Service → Manual Deploy → Clear build cache & deploy
```

### Check Status

```
Render Dashboard → Your Service → Overview
```

---

## Deployment Checklist

Before going live, verify:

- [ ] ✅ Plan: **Starter** ($7/month) selected
- [ ] ✅ All environment variables added correctly
- [ ] ✅ Start command: `python -u main.py`
- [ ] ✅ Build successful (check logs)
- [ ] ✅ Bot online in Discord
- [ ] ✅ All commands working (`ok-help`, `ok-topflow`)
- [ ] ✅ Auto-posting bots scanning (check webhook)
- [ ] ✅ No errors in logs
- [ ] ✅ Memory usage <80% (check metrics)

---

## Support Resources

- **Render Docs**: https://render.com/docs
- **Render Community**: https://community.render.com
- **Discord.py Docs**: https://discordpy.readthedocs.io
- **Render Status**: https://status.render.com

---

## Next Steps

After successful deployment:

1. ✅ **Turn off local PC** - bot stays online!
2. ✅ **Monitor logs** for first 24 hours
3. ✅ **Test all commands** in Discord
4. ✅ **Check webhook** for auto-posting
5. ✅ **Set up alerts** (optional - see Render notifications)

---

## Cost Breakdown (Annual)

| Item | Cost |
|------|------|
| **Render Starter Plan** | $7/month × 12 = **$84/year** |
| **vs. Running PC 24/7** | ~$15/month × 12 = **$180/year** |
| **Annual Savings** | **$96/year** + peace of mind |

---

**Your bots will now run 24/7 on Render!** 🚀

**No more sleep issues. No more downtime. True 24/7 scanning.** ✅
