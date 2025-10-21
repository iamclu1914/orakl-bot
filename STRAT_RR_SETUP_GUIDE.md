# STRAT 7HR 1-3 with Automatic 2:1 R:R Targets

## How It Works

For a 1-3 pattern, the **range** is the risk. For a 2:1 reward-to-risk ratio:

### Bullish Trade:
- **Entry:** Break above High
- **Stop Loss:** Low  
- **Risk:** High - Low
- **Target:** High + (2 × Risk) = High + (2 × (High - Low))

### Bearish Trade:
- **Entry:** Break below Low
- **Stop Loss:** High
- **Risk:** High - Low  
- **Target:** Low - (2 × Risk) = Low - (2 × (High - Low))

## TradingView Setup

### Step 1: Add This to Your Pine Script Indicator

```pine
//@version=5
indicator("STRAT 1-3 with Auto R:R", overlay=true)

// Your existing STRAT 1-3 detection logic...
// Get the 7HR bar high and low
barHigh = high[0]  // Current bar high
barLow = low[0]    // Current bar low

// Calculate range (risk)
risk = barHigh - barLow

// Calculate 2:1 R:R targets
bullishTarget = barHigh + (risk * 2)
bearishTarget = barLow - (risk * 2)

// Plot the targets (they'll appear on your chart)
plot(bullishTarget, "Bull Target", color=color.green, linewidth=2)
plot(bearishTarget, "Bear Target", color=color.red, linewidth=2)

// Your alert condition
alertcondition(your_1_3_condition, "7HR 1-3", "7HR 1-3 {{ticker}}. High: {{high}}, Low: {{low}}")
```

### Step 2: Create Alert with This JSON

In TradingView Alert Settings → Message field:

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
        "value": "${{low}} - ${{high}}",
        "inline": true
      },
      {
        "name": "🟢 Bullish Setup",
        "value": "**Entry:** Break above ${{high}}\n**Target:** ${{plot_0}} (2:1 R:R)\n**Stop:** ${{low}}",
        "inline": true
      },
      {
        "name": "🔴 Bearish Setup",
        "value": "**Entry:** Break below ${{low}}\n**Target:** ${{plot_1}} (2:1 R:R)\n**Stop:** ${{high}}",
        "inline": true
      },
      {
        "name": "💡 Risk:Reward",
        "value": "2:1 targets calculated from range",
        "inline": false
      }
    ]
  }]
}
```

### Step 3: Set Webhook URL

Use your STRAT Discord webhook:
```
https://discord.com/api/webhooks/1429696331202428959/2NdM5OlRS3hlO0f-VeLetMEIVreaQyNPV5WJzRN7i2P6ViCxI5Us2J1fx68JR-Ih21ZW
```

## What Gets Sent to Discord

When the alert triggers, Discord will show:

```
♟️ STRAT Alert: SPY

📊 Pattern: 1-3
⏰ Timeframe: 7HR  
📊 Range: $451.20 - $453.85

🟢 Bullish Setup              🔴 Bearish Setup
Entry: Break above $453.85    Entry: Break below $451.20
Target: $456.50 (2:1 R:R)     Target: $448.55 (2:1 R:R)
Stop: $451.20                 Stop: $453.85

💡 Risk:Reward
2:1 targets calculated from range
```

## The Math Example

If SPY has:
- High: $453.85
- Low: $451.20
- Range (Risk): $453.85 - $451.20 = $2.65

Then:
- **Bullish Target:** $453.85 + (2 × $2.65) = $453.85 + $5.30 = **$459.15**
- **Bearish Target:** $451.20 - (2 × $2.65) = $451.20 - $5.30 = **$445.90**

This gives you a perfect 2:1 reward-to-risk ratio on both sides!
