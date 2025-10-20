# Render Webhook Configuration

Add these environment variables to your Render service to route each bot to its dedicated Discord channel.

## Required Environment Variables

Copy and paste these into Render Dashboard → Your Service → Environment:

```env
# Scalps Bot - Quick STRAT signals
SCALPS_WEBHOOK=https://discord.com/api/webhooks/1427361954850144419/z2aub0kyJHLqz3LLKLOL_CHw7_PaZcJqyiPg3BYp_wW3M3uFVJI0Gx9qsC9a4R7sliH9

# Golden Sweeps Bot - $1M+ option sweeps
GOLDEN_SWEEPS_WEBHOOK=https://discord.com/api/webhooks/1427361801443741788/hXDZQd4hce8-Ph_GKKxFGTzE8EHzSZP0S-xTjxa5lXAc2LoqofGebkk924PbKKXw4FBN

# Breakouts Bot - Stock breakout patterns
BREAKOUTS_WEBHOOK=https://discord.com/api/webhooks/1427362209524355133/eQZmCzobqcMtyuXDZox3gYnSGZET9BKefWrQw64rw5Po0cCOEpjpUFCEBl1fa5VDOJ_B

# Bullseye Bot - AI intraday signals
BULLSEYE_WEBHOOK=https://discord.com/api/webhooks/1427362052753850549/NJBVniyzWQHrc_M6mZ2_19fQjNn_iVEpaMNDjhbYsGuqP6dlElDU58QH-MgfpJ7UE6ip

# Sweeps Bot - Large option sweeps ($50k+)
SWEEPS_WEBHOOK=https://discord.com/api/webhooks/1427361658761777287/vloziMHuypGrjwv8vxd72ySfzTblc9Nf1OHkkKAkUI81IqNPRym0FgjPDQGzYfwiNyC8

# Unusual Activity Bot - Volume surge detection
UNUSUAL_ACTIVITY_WEBHOOK=https://discord.com/api/webhooks/1427372929099894794/xyAqCfHmarR92mr22p6MttN-4c-kBC8rYL_MZJw61a252Z9WsHBFuSu2iQY0bKK0lls_

# STRAT Pattern Bot - 3-2-2, 2-2, 1-3-1 patterns
STRAT_WEBHOOK=https://discord.com/api/webhooks/1429696331202428959/2NdM5OlRS3hlO0f-VeLetMEIVreaQyNPV5WJzRN7i2P6ViCxI5Us2J1fx68JR-Ih21ZW

# Darkpool Bot - Large block and darkpool trades
DARKPOOL_WEBHOOK=https://discord.com/api/webhooks/1428112253697392652/C5WhN4ANtY3kbkgIweYmsZeHYFbhpGdoqQvm7_sk_00QL6zoP7qLOvmfDKyPhohHnKtp

# ORAKL Flow Bot - Repeat and dominant options signals
ORAKL_FLOW_WEBHOOK=https://discord.com/api/webhooks/1428112598917714113/DlMauOnNu4K6h66hc3_geY5mAp0bhFAm1BCEpNf7DekOMVs3kNFvJ0RQ_btaywZRW8nN
```

## Verification

After adding these to Render:

1. Render will auto-deploy with new configuration
2. Each bot will post to its dedicated channel
3. Check logs for: `✓ [Bot Name] → Channel ID: [channel_id]`

## Current Bot Mapping

| Bot | Channel | Status |
|-----|---------|--------|
| Scalps Bot | #scalps | ✅ Configured |
| Golden Sweeps Bot | #golden-sweeps | ✅ Configured |
| Breakouts Bot | #breakouts | ✅ Configured |
| Bullseye Bot | #bullseye | ✅ Configured |
| Sweeps Bot | #sweeps | ✅ Configured |
| Unusual Activity Bot | #unusual-activity | ✅ Configured |
| STRAT Pattern Bot | #strat-alerts | ✅ Configured |
| Darkpool Bot | #darkpool | ✅ Configured |
| ORAKL Flow Bot | #option-flow | ✅ Configured |

## Notes

- All webhooks default to `DISCORD_WEBHOOK_URL` if not set
- Setting individual webhooks ensures proper channel separation
- Render auto-deploys when environment variables change
- No code changes needed - configuration only
