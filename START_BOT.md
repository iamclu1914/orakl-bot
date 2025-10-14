# ORAKL Bot v2.0 Enhanced - Quick Start Guide

## 🚀 Starting Your Enhanced ORAKL Bot

### Prerequisites Check

1. **Python 3.8+** installed
2. **Configuration file** ready (`.env` or `config.env`)
3. **API Keys** configured:
   - ✅ Polygon API Key (Already configured)
   - ✅ Discord Webhook URL (Already configured)
   - ⚠️  Discord Bot Token (Optional - for commands)

### Method 1: Direct Python Launch (Recommended)

```bash
# Install/update dependencies
pip install -r requirements.txt

# Start the bot
python main.py
```

### Method 2: Using Start Scripts

**Windows:**
```bash
start_bot.bat
```

**Linux/Mac:**
```bash
chmod +x scripts/start.sh
./scripts/start.sh
```

### Method 3: Hidden Background Mode (Windows)

```bash
# Runs bot in background without console window
run_hidden.vbs
```

## 📊 What Happens When You Start

The enhanced bot will:

1. **Validate Configuration** - Checks all settings
2. **Initialize Cache Manager** - Starts caching system
3. **Create Connection Pool** - Optimizes API connections
4. **Start All Bots** - Launches 7 specialized bots:
   - 🌊 Orakl Flow Bot (5 min intervals)
   - 🎯 Bullseye Bot (3 min intervals)
   - ⚡ Scalps Bot (2 min intervals)
   - 🔥 Sweeps Bot (3 min intervals)
   - 💎 Golden Sweeps Bot (2 min intervals)
   - 🌑 Darkpool Bot (4 min intervals)
   - 🚀 Breakouts Bot (5 min intervals)
5. **Begin Monitoring** - Health checks every minute

## ✅ Verifying Bot is Running

You should see:

```
╔════════════════════════════════════════════════════╗
║     ORAKL OPTIONS FLOW BOT v2.0 ENHANCED 🚀       ║
║     Polygon API + Discord + Advanced Analytics     ║
║     Production-Ready with Auto-Recovery            ║
╚════════════════════════════════════════════════════╝

============================================================
ORAKL Enhanced Bot Starting...
============================================================
Configuration validated successfully
✓ Enhanced auto-posting bots started successfully
Active bots: 7
  - Orakl Flow Bot: True (Interval: 300s)
  - Bullseye Bot: True (Interval: 180s)
  - Scalps Bot: True (Interval: 120s)
  - Sweeps Bot: True (Interval: 180s)
  - Golden Sweeps Bot: True (Interval: 120s)
  - Darkpool Bot: True (Interval: 240s)
  - Breakouts Bot: True (Interval: 300s)
```

## 📈 Real-Time Monitoring

### Health Status Indicators
- 🟢 **Running** - Bot operating normally
- 🟡 **Warning** - Minor errors, still functional
- 🔴 **Error** - Multiple errors, needs attention
- ⚫ **Stopped** - Bot not running

### Log Files
- Location: `logs/orakl_YYYYMMDD.log`
- Contains: All bot activity, signals, errors
- Auto-rotates: Daily

### Discord Signals
Signals will appear in your configured webhook channel with:
- Enhanced scoring (base + market context)
- Market regime information
- Trading suggestions
- Risk management recommendations

## 🛠️ Configuration Tuning

### For More Aggressive Scanning
Edit `.env`:
```bash
# Scan more frequently
BULLSEYE_INTERVAL=60        # 1 minute (from 3 min)
GOLDEN_SWEEPS_INTERVAL=60   # 1 minute (from 2 min)

# Lower thresholds
MIN_GOLDEN_SCORE=60         # From 65
MIN_SWEEP_SCORE=55          # From 60
```

### For Conservative Mode
```bash
# Scan less frequently
TRADY_FLOW_INTERVAL=600     # 10 minutes (from 5 min)

# Higher quality thresholds
MIN_GOLDEN_SCORE=75         # From 65
MIN_BULLSEYE_SCORE=80       # From 70
```

### For More Symbols
```bash
WATCHLIST=SPY,QQQ,AAPL,MSFT,NVDA,TSLA,AMD,META,GOOGL,AMZN,NFLX,BAC,DIS,GOOG,FB,COIN,PLTR,DKNG,HOOD,RIOT,MARA,GME,AMC
```

## 🔧 Troubleshooting

### "Configuration errors: POLYGON_API_KEY is not set"
**Solution:** Ensure `config.env` is renamed to `.env`
```bash
cp config.env .env
```

### Bot keeps restarting
**Check:** 
1. API key validity: Test at https://polygon.io
2. Rate limits: Free tier has 5 calls/min
3. Network connection

### No signals appearing
**Normal!** Signals only appear when:
- Market is open (9:30 AM - 4:00 PM ET)
- Unusual activity detected
- Minimum thresholds met

**To test:** Lower thresholds temporarily in `.env`

### High memory usage
**Expected:** Caching system uses memory for performance
**Monitor:** Should stabilize around 200-500MB
**If growing:** Check logs for errors, restart bot

## 🎯 Expected Signal Rate

### During Market Hours
- **Quiet Day**: 5-10 signals
- **Normal Day**: 10-30 signals
- **Active Day**: 30-100+ signals

### After Hours
- Minimal activity
- Primarily darkpool reports
- Bots continue monitoring

## 🔐 Security Notes

1. **API Keys** - Keep private, never commit to Git
2. **Webhook URL** - Protects your Discord channel
3. **Log Files** - May contain sensitive data
4. **Process ID** - Only one instance should run

## 📞 Support & Monitoring

### Check Bot Health
```python
# Run in Python console while bot is running
import asyncio
from src.bot_manager import BotManager

async def check_health():
    # Your bot manager instance
    status = bot_manager.get_bot_status()
    print(status)

asyncio.run(check_health())
```

### View Cache Statistics
Check logs for:
```
Final cache statistics:
  api: X hits, Y misses, Z% hit rate
  market: X hits, Y misses, Z% hit rate
```

### Monitor Performance
- API calls: Tracked in logs
- Signal quality: Compare with market movements
- Error rate: Should be <1%

## 🚦 Stopping the Bot

### Graceful Shutdown
- Press `Ctrl+C` in console
- Bot will:
  1. Stop all scanning
  2. Close API connections
  3. Save cache statistics
  4. Clean up resources

### Force Stop (Emergency)
**Windows:** Task Manager > End Process
**Linux/Mac:** `kill -9 <PID>`

## 🎉 Success Indicators

Your bot is working correctly if you see:
- ✓ Configuration validated
- ✓ All 7 bots showing as "True"
- ✓ Health checks showing 🟢 status
- ✓ Periodic log entries (every scan interval)
- ✓ Discord signals appearing during market hours
- ✓ Cache hit rates >20%

## 📚 Additional Resources

- **Full Documentation**: `ENHANCEMENTS_SUMMARY.md`
- **Configuration Reference**: `src/config.py`
- **Test Suite**: `tests/` directory
- **Logs**: `logs/` directory

---

**Need Help?** Check the logs first - they contain detailed information about any issues.

**Market Not Open?** Bot will keep running and start scanning automatically when market opens.
