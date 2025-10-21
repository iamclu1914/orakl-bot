# How to Send TradingView Alerts to Your Discord Channel

This guide explains how to connect TradingView alerts to a specific Discord channel using webhooks.

### Step 1: Get Your Discord Channel's Webhook URL

Every channel in Discord can have a unique webhook URL. This URL is a special link that allows external services like TradingView to send messages to that channel.

1.  **Find the Webhook**: For your STRAT channel, you can find the URL in your `config.env` file under `STRAT_WEBHOOK`.
2.  **To create a new one**:
    *   Right-click on the desired channel in Discord.
    *   Select **"Edit Channel"** -> **"Integrations"**.
    *   Click **"Webhooks"** -> **"New Webhook"**.
    *   Name it (e.g., "TradingView Alerts") and click **"Copy Webhook URL"**.

### Step 2: Create an Alert in TradingView

1.  Open the chart and indicator you want to create an alert for.
2.  Click the **"Alert"** button in the top toolbar (it looks like an alarm clock).
3.  Set up your alert **Condition** (e.g., "Price Crossing Moving Average").
4.  Go to the **"Notifications"** tab.
5.  Check the box for **"Webhook URL"**.
6.  Paste your Discord webhook URL into the text box.

### Step 3: Format the Message for Discord

TradingView needs to send a message in a format that Discord's API can understand (JSON). Copy one of the templates below and paste it into the **"Message"** box in your TradingView alert settings.

---

#### Option 1: Simple Text Alert (Easy)

This will post a plain text message. It's the quickest way to get started.

```json
{
  "content": "📈 **TradingView Alert** 📈\n\n**Ticker**: {{ticker}}\n**Price**: {{close}}\n**Alert**: {{alert_name}}\n\n[Open Chart](https://www.tradingview.com/chart/?symbol={{ticker}})"
}
```

---

#### Option 2: Professional Embedded Alert (Recommended)

This will post a clean, professional-looking embedded message, similar to your bot's alerts.

```json
{
  "embeds": [{
    "title": "📈 TradingView Alert: {{ticker}}",
    "description": "**{{alert_name}}** triggered at **{{timenow}}**.",
    "color": 5814783,
    "fields": [
      {
        "name": "Ticker",
        "value": "{{ticker}}",
        "inline": true
      },
      {
        "name": "Price",
        "value": "${{close}}",
        "inline": true
      },
      {
        "name": "Interval",
        "value": "{{interval}}",
        "inline": true
      }
    ],
    "footer": {
      "text": "Alert triggered from TradingView"
    }
  }]
}
```

*Note: TradingView uses placeholders like `{{ticker}}` and `{{close}}` to automatically insert the correct data into your alert when it's sent.*

### Final Step: Create the Alert

Once you have the webhook URL and the message format in place, just click **"Create"** in TradingView. Your alerts will now be instantly posted to your chosen Discord channel.
