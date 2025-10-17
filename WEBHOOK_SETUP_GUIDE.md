# Discord Webhook Setup Guide

This guide explains how to properly configure Discord webhooks for the ORAKL bot system.

## Problem Solved

The bots were not sending signals to Discord channels due to missing webhook configuration.

## Solution

### 1. Create `.env` File

Create a `.env` file in the project root with the following webhook URLs:

```bash
# Main webhook URL (fallback for all bots)
DISCORD_WEBHOOK_URL=your_main_webhook_url

# Individual Bot Webhooks (each bot posts to its own channel)
UNUSUAL_ACTIVITY_WEBHOOK=your_unusual_activity_webhook
SWEEPS_WEBHOOK=your_sweeps_webhook
BULLSEYE_WEBHOOK=your_bullseye_webhook
BREAKOUTS_WEBHOOK=your_breakouts_webhook
GOLDEN_SWEEPS_WEBHOOK=your_golden_sweeps_webhook
SCALPS_WEBHOOK=your_scalps_webhook
DARKPOOL_WEBHOOK=your_darkpool_webhook
ORAKL_FLOW_WEBHOOK=your_orakl_flow_webhook
STRAT_WEBHOOK=your_strat_webhook
```

### 2. Test Webhook Connectivity

Run the test script to verify webhooks are working:

```bash
python3 send_test_signal.py
```

You should see "Status Code: 204" and "SUCCESS" message.

### 3. Start the Bot

```bash
python3 main.py
```

Or run in background:

```bash
nohup python3 main.py > bot_output.log 2>&1 &
```

## Important Notes

- **Security**: Never commit the `.env` file to git (it's in `.gitignore`)
- **Production**: Set these environment variables in your hosting platform (Render, Railway, etc.)
- **Market Hours**: Bots only find signals during market hours (9:30 AM - 4:00 PM ET, Mon-Fri)

## Bot Intervals

- Orakl Flow Bot: 5 minutes
- Bullseye Bot: 3 minutes  
- Scalps Bot: 2 minutes
- Sweeps Bot: 3 minutes
- Golden Sweeps Bot: 2 minutes
- Darkpool Bot: 4 minutes
- Breakouts Bot: 5 minutes
- Unusual Volume Bot: 3 minutes
- STRAT Bot: 5 minutes

## Troubleshooting

If signals aren't appearing:
1. Check market is open
2. Verify webhook URLs are valid (test with `send_test_signal.py`)
3. Check bot logs: `tail -f bot_output.log`
4. Ensure thresholds aren't too high for current market activity