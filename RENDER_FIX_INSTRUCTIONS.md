# Render Deployment Fix Instructions

## The Issue
Your bot is running in "webhook-only mode" because no Discord bot token is configured. This is fine for your use case since you're using TradingView JSON webhooks directly.

## Fix the Crashes

### On Render Dashboard:

1. **Add this environment variable:**
   ```
   DISCORD_BOT_TOKEN=disabled
   ```
   This tells the bot to run in webhook-only mode without trying to connect to Discord.

2. **Verify these are set correctly:**
   ```
   WATCHLIST_MODE=STATIC
   WATCHLIST=SPY,QQQ,AAPL,MSFT,NVDA,TSLA,AMD,META,GOOGL,AMZN,NFLX,BAC
   ```

3. **Make sure all webhook URLs are valid** (no 404 errors)

## What This Means:

✅ Your auto-posting bots will work perfectly
✅ TradingView JSON webhooks will work
❌ Discord slash commands won't work (ok-commands)
❌ Auto-formatting won't work (but you don't need it with JSON)

## Your Current Setup Works!

Since you're using TradingView's JSON format to send pre-formatted STRAT cards, you don't need the Discord bot features. The webhook-only mode is perfect for your use case.
