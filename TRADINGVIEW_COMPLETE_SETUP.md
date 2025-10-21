# Complete TradingView Setup Guide for STRAT Alerts

## Step 1: Add the Pine Script to TradingView

1. Open TradingView
2. Click the **Pine Editor** tab at the bottom of your screen
3. Click **"Open"** → **"New blank indicator"**
4. **Delete all the default code**
5. **Copy and paste the entire code** from `TRADINGVIEW_COMPLETE_PINE_SCRIPT.txt`
6. Click **"Save"** and name it: `STRAT 7HR 1-3 Auto RR`
7. Click **"Add to Chart"**

You should now see:
- Green/Red lines for 7HR High/Low
- Yellow background when a 1-3 pattern is detected
- Target circles showing where the 2:1 targets are

---

## Step 2: Create the Alert

1. Click the **Alert** button (⏰ clock icon) in the top toolbar
2. In the alert creation window:
   - **Condition:** Select `STRAT 7HR 1-3 Auto RR` → `7HR 1-3 Detected`
   - **Options:** Set "Once Per Bar Close" (to avoid false signals)
   - **Expiration:** Set to your preference (or "Open-ended")

3. **Enable Webhook** (check the box)

4. **Webhook URL:** Paste your STRAT Discord webhook:
   ```
   https://discord.com/api/webhooks/1429696331202428959/2NdM5OlRS3hlO0f-VeLetMEIVreaQyNPV5WJzRN7i2P6ViCxI5Us2J1fx68JR-Ih21ZW
   ```

5. **Message:** Copy and paste this entire JSON:

```json
{
  "embeds": [{
    "title": "♟️ STRAT Alert: {{ticker}}",
    "color": 16766720,
    "fields": [
      {
        "name": "📊 Pattern",
        "value": "1-3",
        "inline": true
      },
      {
        "name": "⏰ Timeframe",
        "value": "7HR",
        "inline": true
      },
      {
        "name": "📊 Range",
        "value": "${{plot("7HR Low")}} - ${{plot("7HR High")}}",
        "inline": true
      },
      {
        "name": "🟢 Bullish Setup",
        "value": "**Entry:** Break above ${{plot("7HR High")}}\n**Target:** ${{plot("plot_0")}} (2:1 R:R)\n**Stop:** ${{plot("7HR Low")}}",
        "inline": true
      },
      {
        "name": "🔴 Bearish Setup",
        "value": "**Entry:** Break below ${{plot("7HR Low")}}\n**Target:** ${{plot("plot_1")}} (2:1 R:R)\n**Stop:** ${{plot("7HR High")}}",
        "inline": true
      },
      {
        "name": "💡 Risk:Reward",
        "value": "2:1 targets auto-calculated",
        "inline": false
      }
    ]
  }]
}
```

6. Click **"Create"**

---

## Step 3: Test Your Alert

To test if everything works:

1. Go to a stock chart (like SPY)
2. Switch to a timeframe where you can see 7HR bars forming
3. Wait for a 1-3 pattern to trigger
4. Check your Discord STRAT channel for the formatted card

---

## What the Code Does

### Pattern Detection:
```pine
isOneThree = (sevenHrHigh > prevHigh) and (sevenHrLow < prevLow)
```
Detects when the current 7HR bar's high is higher AND low is lower than the previous 7HR bar (expansion = 1-3 pattern)

### Target Calculation:
```pine
range = sevenHrHigh - sevenHrLow
bullishTarget = sevenHrHigh + (range * 2)
bearishTarget = sevenHrLow - (range * 2)
```
Automatically calculates perfect 2:1 R:R targets based on the bar's range

### Example:
If SPY forms a 7HR 1-3 bar with:
- High: $453.85
- Low: $451.20
- Range: $2.65

The alert will show:
- **Bullish Target:** $459.15 (entry at $453.85 + 2×$2.65)
- **Bearish Target:** $445.90 (entry at $451.20 - 2×$2.65)

---

## Troubleshooting

**Alert not triggering?**
- Make sure you're on a chart with 7HR bars visible
- Check that the indicator is added to your chart
- Verify the alert condition is set to "7HR 1-3 Detected"

**Webhook not posting to Discord?**
- Verify the webhook URL is correct
- Check that the JSON format is exact (no extra spaces or missing brackets)
- Test the webhook by clicking "Test" in TradingView

**Targets look wrong?**
- The script uses `request.security` to get 7HR data regardless of your chart timeframe
- Make sure you're looking at the correct bar's high/low values

---

## Ready to Go! 🚀

Once set up:
1. TradingView detects 1-3 patterns on 7HR timeframe
2. Calculates 2:1 R:R targets automatically
3. Sends beautiful formatted cards to your Discord STRAT channel
4. You get instant alerts with entry, target, and stop levels

No manual calculation needed!

