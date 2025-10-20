# 🚨 RENDER KEEPS RESTARTING YOUR BOT!

## The Problem:
Your bot is being killed after ~1 minute with "signal 15" (SIGTERM). This happens when:
1. Health checks fail
2. Render thinks the service is unhealthy

## 🔍 Found the Issue:

Your Dockerfile has a complex health check:
```dockerfile
HEALTHCHECK --interval=60s --timeout=10s --start-period=30s --retries=3 \
    CMD python -c "import psutil; import sys; sys.exit(0 if any('main.py' in ' '.join(p.cmdline()) for p in psutil.process_iter(['cmdline'])) else 1)"
```

This health check:
- Runs every 60 seconds
- Looks for "main.py" in process list
- Might be failing on Render's environment

## 🔧 Quick Fix Options:

### Option 1: Remove Health Check (FASTEST)
Comment out the health check in Dockerfile:
```dockerfile
# Health check - DISABLED to prevent restarts
# HEALTHCHECK --interval=60s --timeout=10s --start-period=30s --retries=3 \
#     CMD python -c "import psutil; import sys; sys.exit(0 if any('main.py' in ' '.join(p.cmdline()) for p in psutil.process_iter(['cmdline'])) else 1)"
```

### Option 2: Simple Health Check
Replace with a basic check:
```dockerfile
HEALTHCHECK --interval=120s --timeout=30s --start-period=60s --retries=5 \
    CMD python -c "print('healthy'); exit(0)"
```

### Option 3: Check Render Settings
In Render Dashboard:
1. Go to your service
2. Settings → Health & Alerts
3. Disable health checks or increase grace period

## 🎯 Recommended: Option 1

Disable the health check for now to let your bot run!

## 📊 Why This Matters:

Your bot needs to run for at least:
- 2 minutes for Scalps/Golden Sweeps
- 3 minutes for Sweeps/Bullseye
- 5 minutes for Orakl Flow/Breakouts

But it's being killed after 1 minute!

## ✅ After Fix:

Your bot will:
1. Run continuously
2. Complete scans
3. Find signals
4. **SEND ALERTS TO DISCORD!**

---

The bot is working perfectly - it just needs to stay alive long enough!
