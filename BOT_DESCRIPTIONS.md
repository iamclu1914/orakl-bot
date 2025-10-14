# 🤖 ORAKL Bot v2.0 - Complete Bot Guide

## 7 Specialized Trading Bots - What They Do

---

## 1. 💎 **Golden Sweeps Bot**

### Purpose
Tracks **million-dollar+ premium sweeps** - the largest conviction trades in the market

### What It Detects
- Options sweeps with **$1,000,000+ premium**
- Multiple fills executed rapidly
- Massive institutional positions
- High-conviction trades

### Scan Interval
**120 seconds (2 minutes)** - Fast scanning for big money moves

### Minimum Thresholds
- Premium: **$1,000,000+**
- Score: **65/100**
- Days to Expiry: 0-180 days

### Signal Example
```
💎 GOLDEN SWEEP: AAPL 💰
$1.5M Deep ITM CALL | Action: BUY | Score: 85/100

Contract: CALL $150
PREMIUM: $1.5M
Volume: 1,500 contracts
Fills: 8 rapid fills in 45s
Probability ITM: 72.5%

Market Context: Bull | Strong Up
Action: BUY | Confidence: HIGH
```

### Why It Matters
- Shows where **big money** is positioning
- Indicates **institutional conviction**
- Often **precedes major moves**
- Highest quality signals

---

## 2. 🔥 **Sweeps Bot**

### Purpose
Tracks **large options sweeps** with $50k+ premiums showing strong conviction

### What It Detects
- Aggressive market orders
- Multiple rapid fills
- Sweeping the order book
- Premium: **$50,000 - $999,999**

### Scan Interval
**180 seconds (3 minutes)**

### Minimum Thresholds
- Premium: **$50,000+**
- Score: **60/100**
- Fills: 2+ rapid fills in 5 minutes
- Days to Expiry: 0-90 days

### Signal Example
```
🔥 SWEEP: NVDA
Aggressive ITM Sweep | Conviction: 75/100

Contract: CALL $500
Premium: $125,000
Volume: 500 contracts
Fills: 4 rapid fills in 180s
Distance: +2.5%

Action: CONSIDER | Confidence: MEDIUM
```

### Why It Matters
- Shows **aggressive buying/selling**
- Indicates directional conviction
- Often **leads price movement**
- Smart money positioning

---

## 3. 🎯 **Bullseye Bot**

### Purpose
**AI-powered intraday momentum** scanner for same-day and very short-term trades

### What It Detects
- Intraday price momentum (0.5%+)
- Short-term options (0-3 DTE)
- AI-scored signals
- Momentum-aligned positions

### Scan Interval
**180 seconds (3 minutes)** - Fast for intraday

### Minimum Thresholds
- Premium: **$5,000+**
- Score: **70/100** (AI-calculated)
- Momentum: 0.5%+ move in 30 minutes
- Days to Expiry: 0-3 days

### Signal Example
```
🎯 Bullseye: TSLA ↗️
AI Intraday CALL Signal | Score: 78/100

Contract: CALL $250 (0DTE)
AI Score: 78/100
Momentum: +1.8% (30min)
Current Price: $248.50
Volume: 350 contracts
Premium: $15,750

Timeframe: Intraday - 0 DTE
Probability: 45.2%
```

### Why It Matters
- **AI-powered** signal scoring
- Catches **intraday momentum**
- Perfect for **day traders**
- High frequency opportunities

---

## 4. ⚡ **Scalps Bot**

### Purpose
Uses **The Strat methodology** to identify quick scalp setups

### What It Detects
- The Strat patterns (2-2 reversals, 3-2-2 setups)
- Inside/Outside bar patterns
- Momentum continuation
- Quick profit opportunities

### Scan Interval
**120 seconds (2 minutes)** - Fastest scanning

### Minimum Thresholds
- Premium: **$2,000+**
- Score: **65/100**
- Strike: Within 3% of current price
- Days to Expiry: 0-7 days

### Signal Example
```
⚡ Scalp: AMD
2-2 Bullish Reversal | Quick CALL Setup

Contract: CALL $140 (2DTE)
Scalp Score: 72/100
Pattern: 2-2 Bullish Reversal
Current Price: $139.50
Volume: 180 contracts
Strike: $140.00 (0.36% away)

Timeframe: 5m bars
Note: Quick scalp - monitor closely
```

### Why It Matters
- Based on **proven methodology** (The Strat)
- **Quick turnaround** signals
- Pattern-based edge
- Scalping opportunities

---

## 5. 🌑 **Darkpool Bot**

### Purpose
Tracks **large darkpool and block trades** - institutional positioning

### What It Detects
- Darkpool trades (off-exchange)
- Block trades (10,000+ shares)
- Trades 5x+ average size
- $100,000+ dollar value

### Scan Interval
**240 seconds (4 minutes)**

### Minimum Thresholds
- Size: **10,000+ shares**
- Dollar Value: **$100,000+**
- Score: **60/100**
- Multiple: 5x+ average trade size

### Signal Example
```
🌑 DARKPOOL: META
Large darkpool trade detected | Score: 72/100

Size: 45,000 shares
Dollar Value: $13,500,000
Block Score: 72/100

Block Price: $300.00
Current Price: $301.50
Price Diff: -0.50%

Avg Size Multiple: 12.5x average
Exchange: D (Darkpool)

Analysis: Darkpool activity suggests institutional 
positioning. Trade executed at discount.
```

### Why It Matters
- **Institutional activity**
- Often **precedes major moves**
- **Hidden liquidity** revealed
- Smart money tracking

---

## 6. 🚀 **Breakouts Bot**

### Purpose
Identifies **stock price breakouts** with volume confirmation

### What It Detects
- Price breaking above resistance
- Price breaking below support
- Volume surge (1.5x+ average)
- Technical breakout patterns

### Scan Interval
**300 seconds (5 minutes)**

### Minimum Thresholds
- Volume Surge: **1.5x+ average**
- Score: **65/100**
- Breakout: 0.1%+ beyond support/resistance
- Historical data: 20 days

### Signal Example
```
🚀 BREAKOUT: AAPL UP
BULLISH Breakout | Score: 78/100

Current Price: $182.50
Change: +2.3%
Breakout Score: 78/100

Breakout Level: $180.00
Resistance: $180.00
Support: $175.00

Volume Surge: 2.8x
Volume: 85,500,000
Avg Volume: 30,500,000

Next Target: $189.00
Stop Loss: $175.00
Pattern: Resistance Breakout

Analysis: Strong upward momentum with 2.8x volume confirmation
```

### Why It Matters
- **Technical analysis** backed by volume
- Catches **major moves early**
- Clear support/resistance levels
- High probability setups

---

## 7. 🌊 **Orakl Flow Bot** (Formerly Trady Flow)

### Purpose
Identifies **repeat and dominant signals** with high ITM success rate

### What It Detects
- Signals repeated 3+ times
- Dominant flow in one direction
- High probability ITM (65%+)
- Consistent institutional interest

### Scan Interval
**300 seconds (5 minutes)**

### Minimum Thresholds
- Premium: **$10,000+**
- Volume: **100+ contracts**
- Repeat Count: **3+ signals**
- Probability ITM: **65%+**
- Days to Expiry: 0-45 days

### Signal Example
```
🟢 Orakl Flow: MSFT
Repeat dominant CALL signal detected

Contract: CALL $370 (Exp: 2025-01-31)
Probability ITM: 68.2%
Premium Flow: $125,000

Current Price: $365.50
Volume: 850 contracts
Repeat Signals: 5 detected

Target: Break above $370.00
Days to Expiry: 25 days
```

### Why It Matters
- **Repeat signals** = Strong conviction
- **High ITM probability** = Better odds
- Filters out **noise**
- **Proven track record** focus

---

## 📊 **How The Bots Work Together**

### **Complementary Coverage:**

| Bot Type | Speed | Size | Focus |
|----------|-------|------|-------|
| **Golden Sweeps** | 2 min | $1M+ | Massive conviction |
| **Sweeps** | 3 min | $50k+ | Large orders |
| **Bullseye** | 3 min | $5k+ | Intraday momentum |
| **Scalps** | 2 min | $2k+ | Quick patterns |
| **Darkpool** | 4 min | Blocks | Institutional flow |
| **Breakouts** | 5 min | Stock | Technical setups |
| **Orakl Flow** | 5 min | $10k+ | Repeat signals |

### **Coverage Spectrum:**

```
Ultra Short-term ←→ Short-term ←→ Medium-term
    Scalps              Bullseye        Orakl Flow
    Sweeps              Golden          Breakouts
                        Darkpool
```

---

## 🎯 **Bot Signal Quality**

### **Scoring System (0-100)**

Each bot uses a **multi-factor scoring algorithm**:

**Base Factors (50%):**
- Premium size
- Volume metrics
- Strike proximity
- Days to expiry

**Market Context (20%):**
- Current regime (Bull/Bear)
- Trend direction
- Volatility environment

**Technical (15%):**
- Momentum indicators
- Volume confirmation
- Pattern strength

**Flow Analysis (15%):**
- Repeat signals
- Institutional activity
- Unusual activity level

### **Enhanced Scoring Features:**

All signals now include:
- ✅ Base score from bot logic
- ✅ Market context adjustment
- ✅ Multi-factor analysis
- ✅ Confidence calculation
- ✅ Trading suggestions
- ✅ Risk management levels

---

## 🔍 **Bot Selection Strategy**

### **When to Pay Attention to Each Bot:**

**Golden Sweeps ($1M+)**
- → **Highest priority** - massive conviction
- → Follow institutional money
- → Often multi-day/week moves

**Sweeps ($50k+)**
- → **High priority** - strong conviction
- → Watch for follow-through
- → Good risk/reward

**Bullseye (Intraday)**
- → **Day trading** opportunities
- → Quick moves (same day)
- → Active monitoring needed

**Scalps (The Strat)**
- → **Scalping** opportunities  
- → Very short timeframe
- → Pattern-based edge

**Darkpool (Blocks)**
- → **Institutional** positioning
- → Watch for **accumulation**
- → Can take days to play out

**Breakouts (Technical)**
- → **Stock traders** focus
- → Volume-confirmed moves
- → Clear entry/exit levels

**Orakl Flow (Repeat)**
- → **Consistent** signals
- → High probability setups
- → Institutional consensus

---

## 📈 **Performance by Bot Type**

### **Expected Signal Frequency:**

| Bot | Quiet Day | Normal Day | Active Day |
|-----|-----------|------------|------------|
| Golden Sweeps | 0-1 | 1-3 | 3-10 |
| Sweeps | 1-2 | 3-8 | 8-20 |
| Bullseye | 2-5 | 5-15 | 15-40 |
| Scalps | 1-3 | 3-10 | 10-25 |
| Darkpool | 1-2 | 2-5 | 5-15 |
| Breakouts | 0-2 | 2-5 | 5-10 |
| Orakl Flow | 1-3 | 3-8 | 8-20 |

**Total Daily:** 5-10 (quiet) | 20-50 (normal) | 50-150+ (active)

---

## 🎨 **Bot Visual Identifiers**

Each bot has unique emojis and colors in Discord:

| Bot | Emoji | Color | Type |
|-----|-------|-------|------|
| **Golden Sweeps** | 💎 | Gold (#FFD700) | Premium alerts |
| **Sweeps** | 🔥 | Green/Red | Conviction orders |
| **Bullseye** | 🎯 | Green/Red | AI signals |
| **Scalps** | ⚡ | Green/Red | Quick setups |
| **Darkpool** | 🌑 | Purple (#9B30FF) | Institutional |
| **Breakouts** | 🚀 | Green/Red | Momentum |
| **Orakl Flow** | 🟢/🔴 | Green/Red | Repeat signals |

---

## 🎯 **Which Bot For Which Strategy?**

### **Day Trading**
Primary: **Bullseye Bot** (intraday momentum)
Secondary: **Scalps Bot** (quick patterns)

### **Swing Trading**
Primary: **Sweeps Bot** (conviction orders)
Secondary: **Orakl Flow Bot** (repeat signals)

### **Position Trading**
Primary: **Golden Sweeps Bot** (institutional)
Secondary: **Darkpool Bot** (accumulation)

### **Technical Trading**
Primary: **Breakouts Bot** (price action)
Secondary: **Scalps Bot** (The Strat patterns)

### **Smart Money Tracking**
Primary: **Darkpool Bot** (blocks)
Secondary: **Golden Sweeps Bot** (massive flows)

### **High Probability**
Primary: **Orakl Flow Bot** (65%+ ITM)
Secondary: **Sweeps Bot** (conviction)

---

## 🔥 **Current Activity Levels**

Based on your live bot (as of 2:15 PM ET):

### **Active Scanning:**
All 7 bots are currently scanning your 12-symbol watchlist:
- SPY, QQQ, AAPL, MSFT, NVDA, TSLA
- AMD, META, GOOGL, AMZN, NFLX, BAC

### **Scan Coverage:**
Every **2-5 minutes**, each symbol is analyzed by multiple bots:
- **Every 2 min**: Golden Sweeps, Scalps
- **Every 3 min**: Sweeps, Bullseye
- **Every 4 min**: Darkpool
- **Every 5 min**: Orakl Flow, Breakouts

### **Total Scans Per Hour:**
- ~30 scans per symbol per hour
- ~360 total scans across all symbols
- Overlapping coverage for comprehensive detection

---

## 🧠 **Enhanced Intelligence**

All bots now include:

### **Market Context Analysis**
- Current regime detection (Bull/Bear/Neutral)
- Trend analysis (Strong Up/Down/Sideways)
- Volatility assessment
- VIX consideration (when available)

### **Advanced Scoring**
- Multi-factor analysis
- Context-aware adjustments
- Confidence calculation
- Risk assessment

### **Trading Suggestions**
- Action: STRONG_BUY, BUY, CONSIDER, MONITOR
- Confidence: HIGH, MEDIUM, LOW
- Position size: FULL, 3/4, 1/2, 1/4, MINIMUM
- Stop loss: Dynamic (25%-50%)
- Take profit: Dynamic (50%-200%)

---

## 📊 **Bot Performance Metrics**

Your live bots (current stats):

| Bot | Scans | Signals | Errors | Avg Duration |
|-----|-------|---------|--------|--------------|
| Orakl Flow | Active | 0 | 0 | 2.7s |
| Bullseye | Active | 0 | 0 | 0.6s |
| Scalps | Active | 0 | 0 | 0.5s |
| Sweeps | Active | 1 ✅ | 0 | 1.8s |
| Golden | Active | 0 | 1 (recovered) | 1.7s |
| Darkpool | Active | 0 | 0 | 1.3s |
| Breakouts | Active | 0 | 0 | 2.7s |

**All bots operating efficiently!**

---

## 🎮 **Customizing Bot Behavior**

### **Adjust in `.env` file:**

```bash
# Make bots scan more frequently
GOLDEN_SWEEPS_INTERVAL=60    # 1 min (from 2 min)
BULLSEYE_INTERVAL=120        # 2 min (from 3 min)

# Raise quality thresholds
MIN_GOLDEN_SCORE=75          # From 65
MIN_SWEEP_SCORE=70           # From 60
MIN_BULLSEYE_SCORE=80        # From 70

# Lower for more signals
MIN_PREMIUM=5000             # From 10,000
GOLDEN_MIN_PREMIUM=500000    # From 1,000,000

# Adjust bot-specific thresholds
SWEEPS_MIN_PREMIUM=25000     # From 50,000
BULLSEYE_MIN_PREMIUM=2500    # From 5,000
SCALPS_MIN_PREMIUM=1000      # From 2,000
```

After changing, restart the bot:
```bash
pm2 restart orakl-bot-enhanced --update-env
```

---

## 💡 **Pro Tips**

### **Understanding Bot Synergy:**

1. **Confirmation Signals**
   - When **multiple bots** signal same symbol = Higher conviction
   - Example: Golden Sweep + Darkpool Block + Breakout = Very strong

2. **Bot Combinations**
   - Golden + Orakl Flow = Institutional + repeat = Best
   - Bullseye + Scalps = Intraday momentum + pattern = Day trade
   - Sweeps + Breakouts = Flow + technical = Swing trade

3. **Timeframe Matching**
   - Golden/Darkpool = Days to weeks
   - Sweeps/Orakl = Days
   - Bullseye/Scalps = Hours to day
   - Breakouts = Hours to days

### **Signal Prioritization:**

**Highest Priority:**
1. Golden Sweeps ($1M+)
2. Darkpool (institutional blocks)
3. Orakl Flow (repeat signals)

**High Priority:**
4. Sweeps ($50k+ conviction)
5. Breakouts (volume confirmed)

**Active Trading:**
6. Bullseye (intraday AI)
7. Scalps (quick patterns)

---

## 📱 **Sample Discord Output**

Your Discord channel will show signals like this:

```
[Golden Sweeps Bot]
💎 GOLDEN SWEEP: AAPL 💰
$2.1M Deep ITM CALL | Action: STRONG_BUY | Score: 88/100 | Confidence: 85%
...

[Sweeps Bot]
🔥 SWEEP: NVDA
Aggressive OTM Sweep | Conviction: 72/100
...

[Darkpool Bot]
🌑 DARKPOOL: TSLA
Large darkpool trade detected | Score: 75/100
...

[Orakl Flow Bot]
🟢 Orakl Flow: MSFT
Repeat dominant CALL signal detected
...
```

Each with **full analysis**, **market context**, and **trading suggestions**!

---

## 🎊 **Your Complete Arsenal**

You now have **7 specialized AI-powered bots** working 24/7 to:

✅ Monitor **12 symbols** continuously
✅ Analyze **thousands of data points** per hour
✅ Detect **unusual activity** instantly
✅ Score signals with **market context**
✅ Post **high-quality alerts** to Discord
✅ Provide **actionable recommendations**
✅ Operate **autonomously** forever

**All running RIGHT NOW on your system!**

---

## 🚀 **Next Steps**

1. **Monitor Discord** - Signals will appear there
2. **Check logs** occasionally: `pm2 logs orakl-bot-enhanced`
3. **Tune settings** if needed (edit `.env`)
4. **Trust the system** - It handles everything automatically

**Your bots are working for you 24/7!** 🎯
