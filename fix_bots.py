#!/usr/bin/env python3
"""Fix the bot configuration to use a smaller watchlist"""
import os
import sys

# Create a focused watchlist of high-liquidity stocks
FOCUSED_WATCHLIST = [
    # Major indices
    "SPY", "QQQ", "IWM", "DIA",
    # Top tech
    "AAPL", "MSFT", "NVDA", "GOOGL", "META", "AMZN",
    # High volume stocks
    "TSLA", "AMD", "NFLX", "PLTR", "SOFI", "NIO",
    # Banks
    "JPM", "BAC", "WFC", "C",
    # Popular retail stocks
    "GME", "AMC", "BBBY", "BB"
]

print("Updating bot configuration...")

# Update the .env file to use focused watchlist
env_content = open('.env', 'r').read()

# Update watchlist mode
env_content = env_content.replace('WATCHLIST_MODE=STATIC', 'WATCHLIST_MODE=FOCUSED')

# Add focused watchlist
if 'FOCUSED_WATCHLIST=' not in env_content:
    env_content += f"\n# Focused watchlist for better performance\nFOCUSED_WATCHLIST={','.join(FOCUSED_WATCHLIST)}\n"

# Lower some thresholds for testing
env_content = env_content.replace('MIN_VOLUME_RATIO=2.0', 'MIN_VOLUME_RATIO=1.5')
env_content = env_content.replace('MIN_ABSOLUTE_VOLUME=500000', 'MIN_ABSOLUTE_VOLUME=100000')

with open('.env', 'w') as f:
    f.write(env_content)

print("✅ Updated .env file")

# Create a simple patch for bot_manager.py
patch_content = '''
# Patch to use focused watchlist
import os
FOCUSED_WATCHLIST = os.getenv('FOCUSED_WATCHLIST', '').split(',')
if FOCUSED_WATCHLIST and len(FOCUSED_WATCHLIST) > 1:
    print(f"Using focused watchlist with {len(FOCUSED_WATCHLIST)} symbols")
else:
    FOCUSED_WATCHLIST = ["SPY", "QQQ", "AAPL", "MSFT", "NVDA", "TSLA", "AMD", "META", "GOOGL", "AMZN"]
'''

print("\nTo fix the bots:")
print("1. Stop the current bot: pkill -f 'python3 main.py'")
print("2. Update the bot_manager.py to use a smaller watchlist")
print("3. Restart with: python3 main.py")
print("\nFocused watchlist has only", len(FOCUSED_WATCHLIST), "symbols for faster scanning")