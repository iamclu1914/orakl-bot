# TradingView STRAT Alert JSON Formats

## Format 1: Full STRAT Pattern (1-3-1, 2-2, etc.) with Targets

**For alerts like:** `1-3-1 detected for {{ticker}}. 50% Trigger: {{plot_0}} If we open above {{plot_0}} First PT is {{low}}, If we open below {{plot_0}} First PT is {{high}}`

```json
{
  "embeds": [{
    "title": "♟️ STRAT Alert: {{ticker}}",
    "color": 16766720,
    "fields": [
      {
        "name": "📊 Pattern",
        "value": "1-3-1",
        "inline": true
      },
      {
        "name": "🎯 50% Trigger",
        "value": "${{plot_0}}",
        "inline": true
      },
      {
        "name": "⏰ Timeframe",
        "value": "12HR",
        "inline": true
      },
      {
        "name": "🟢 Bullish Scenario",
        "value": "**Open above ${{plot_0}}**\nFirst PT: **${{low}}**",
        "inline": true
      },
      {
        "name": "🔴 Bearish Scenario",
        "value": "**Open below ${{plot_0}}**\nFirst PT: **${{high}}**",
        "inline": true
      },
      {
        "name": "📈 Status",
        "value": "Alert Active",
        "inline": true
      }
    ]
  }]
}
```

## Format 2: Range Pattern with Auto 2:1 R:R Targets (RECOMMENDED)

**For alerts like:** `7HR 1-3 {{ticker}}. High: {{high}}, Low: {{low}}`

**Requires:** Pine Script to calculate targets (see STRAT_RR_SETUP_GUIDE.md)

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

**How it works:**
- Risk = High - Low
- Bullish Target = High + (2 × Risk)
- Bearish Target = Low - (2 × Risk)
- See `STRAT_RR_SETUP_GUIDE.md` for Pine Script code

## How to Use:

1. In TradingView Alert Settings:
   - **Webhook URL**: Your Discord STRAT webhook
   - **Message**: Copy the entire JSON block that matches your alert type

2. Customize as needed:
   - Change `"value": "1-3-1"` to your specific pattern
   - Change `"value": "12HR"` to your timeframe
   - Adjust colors: 16766720 (gold), 65280 (green), 16711680 (red)

3. Available TradingView Placeholders:
   - `{{ticker}}` - Stock symbol
   - `{{close}}` - Current price
   - `{{high}}` - High price
   - `{{low}}` - Low price
   - `{{plot_0}}`, `{{plot_1}}` - Custom indicator values
   - `{{timenow}}` - Current time

## Color Codes:
- Gold (STRAT): 16766720
- Green: 65280
- Red: 16711680
- Blue: 255
