# ORAKL Options Flow Bot

An automated options flow scanner that monitors unusual options activity using Polygon.io API and sends real-time alerts to Discord.

## Features

- 🔮 **ORAKL Flow Scanner**: Detects high-probability options signals with >65% ITM probability
- 🔄 **Repeat Signal Detection**: Tracks signals that appear 3+ times within an hour
- 📊 **AI Analysis**: Sentiment scoring and directional predictions based on flow
- 🚀 **Auto-Start**: Runs automatically on system startup (Windows/Mac/Linux)
- 💬 **Discord Integration**: Rich embeds with detailed analysis and alerts
- 📈 **Real-time Monitoring**: Scans every 5 minutes during market hours
- 🎯 **Smart Filtering**: Minimum $10k premium and unusual volume detection

## Quick Start

### 1. Prerequisites

- Python 3.8 or higher
- Polygon.io API key (get from [polygon.io](https://polygon.io))
- Discord Bot Token (create at [discord.com/developers](https://discord.com/developers))
- Discord Webhook URL (from your Discord server settings)

### 2. Installation

```bash
# Clone or download the project
cd orakl-bot

# Run automatic setup
python setup.py
```

### 3. Configuration

Edit the `.env` file with your credentials:

```env
POLYGON_API_KEY=your_polygon_api_key_here
DISCORD_BOT_TOKEN=your_discord_bot_token_here
DISCORD_WEBHOOK_URL=your_discord_webhook_url_here
DISCORD_CHANNEL_ID=your_channel_id_here
```

### 4. Running the Bot

#### Option A: Auto-Start (Recommended)
The setup script configures auto-start. Just restart your computer.

#### Option B: Manual Start
```bash
# Windows
scripts\start.bat

# Mac/Linux
./scripts/start.sh

# Or directly
python main.py
```

#### Option C: PM2 (All Platforms)
```bash
npm install -g pm2
pm2 start main.py --name ORAKL
pm2 save
pm2 startup
```

## Discord Commands

All commands use the `ok-` prefix:

### Flow Analysis
- `ok-all SYMBOL` - AI predictions for stock movement
- `ok-topflow` - Most bullish and bearish stocks today
- `ok-bigflow SYMBOL` - 10 largest options trades
- `ok-flowsum SYMBOL` - Complete flow summary
- `ok-scan` - Force immediate scan

### Info
- `ok-help` - Show all commands

## Configuration Options

Edit `.env` to customize:

```env
# Scan Settings
SCAN_INTERVAL_MINUTES=5        # How often to scan
MIN_PREMIUM=10000             # Minimum trade premium
MIN_VOLUME=100                # Minimum volume
UNUSUAL_VOLUME_MULTIPLIER=3   # Volume vs average multiplier
REPEAT_SIGNAL_THRESHOLD=3     # Minimum repeat signals
SUCCESS_RATE_THRESHOLD=0.65   # Minimum probability ITM

# Watchlist
WATCHLIST=SPY,QQQ,AAPL,MSFT,NVDA,TSLA,AMD,META,GOOGL,AMZN
```

## How It Works

1. **Scanning**: Every 5 minutes, scans your watchlist for unusual options activity
2. **Analysis**: Calculates probability ITM, analyzes flow sentiment, detects repeat signals
3. **Filtering**: Only alerts on high-probability trades (>65% ITM) with significant premium
4. **Alerts**: Sends rich Discord embeds with:
   - Contract details and probability
   - Premium flow and volume metrics
   - Repeat signal count
   - Target prices and sentiment

## ORAKL Signal Criteria

A signal is triggered when ALL conditions are met:
- Premium ≥ $10,000
- Volume ≥ 100 contracts
- Probability ITM ≥ 65%
- Repeat signals ≥ 3 within 1 hour
- Days to expiry between 0-45

## Monitoring

```bash
# Check if running
ps aux | grep main.py

# View logs
tail -f logs/orakl_*.log

# PM2 monitoring (if using)
pm2 status
pm2 logs ORAKL
```

## Troubleshooting

### Bot won't start
1. Check your Python version: `python --version`
2. Verify API keys in `.env` file
3. Check logs in `logs/` directory

### No signals appearing
1. Verify market is open
2. Check your watchlist has active symbols
3. Lower `MIN_PREMIUM` or `SUCCESS_RATE_THRESHOLD` temporarily

### Discord errors
1. Verify bot token is correct
2. Ensure bot has permissions in your server
3. Check channel IDs match your server

## Project Structure

```
orakl-bot/
├── src/                      # Core bot code
│   ├── config.py            # Configuration management
│   ├── data_fetcher.py      # Polygon API integration
│   ├── options_analyzer.py  # Analysis engine
│   ├── flow_scanner.py      # ORAKL scanner
│   ├── discord_bot.py       # Discord bot
│   └── utils/               # Helper functions
├── scripts/                 # Startup scripts
├── logs/                    # Log files
├── main.py                  # Entry point
├── setup.py                 # Auto-setup script
└── .env                     # Configuration (create this)
```

## Safety & Disclaimer

- This bot is for informational purposes only
- Not financial advice
- Always do your own research
- Past performance doesn't guarantee future results
- Options trading involves significant risk

## Support

- Check logs in `logs/` directory for errors
- Ensure all API keys are valid
- Verify Python dependencies are installed
- Market must be open for signals to appear

## License

MIT License - See LICENSE file for details
