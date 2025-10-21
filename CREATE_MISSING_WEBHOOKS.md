# 🔧 CREATE MISSING DISCORD WEBHOOKS

## ❌ WEBHOOKS THAT NEED TO BE CREATED:

### 1. Darkpool Bot
- **Channel**: darkpool channel (ID: 1428112253697392652)
- **Current webhook**: INVALID/DELETED

### 2. Orakl Flow Bot  
- **Channel**: orakl-flow channel (ID: 1428112598917714113)
- **Current webhook**: INVALID/DELETED

## 📝 HOW TO CREATE NEW WEBHOOKS:

1. **Go to your Discord server**

2. **Find the channel** (darkpool or orakl-flow)

3. **Right-click the channel** → **Edit Channel**

4. **Go to Integrations** → **Webhooks**

5. **Click "New Webhook"**

6. **Name it** (e.g., "ORAKL Darkpool Bot" or "ORAKL Flow Bot")

7. **Copy the webhook URL**

8. **Update in Render**:
   - For Darkpool: `DARKPOOL_WEBHOOK=<new webhook url>`
   - For Orakl Flow: `ORAKL_FLOW_WEBHOOK=<new webhook url>`

## 🚨 CRITICAL: ALSO CHANGE SERVICE TYPE!

Your bot is STILL restarting every 60 seconds because it's running as a **Web Service**.

### IN RENDER DASHBOARD:
1. Go to your service settings
2. Change from **Web Service** to **Background Worker**
3. This will stop the constant restarts!

## 📊 CURRENT STATUS:
- ✅ 7/9 bots have working webhooks
- ❌ 2/9 need new webhooks (Darkpool, Orakl Flow)
- 🚨 Bot restarts every 60 seconds (needs service type change)

Once you:
1. Create the 2 missing webhooks
2. Change to Background Worker

Your bot will be 100% operational! 🚀
