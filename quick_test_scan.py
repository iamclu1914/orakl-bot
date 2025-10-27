"""Quick test of 1-3-1 detection on specific stocks"""
import asyncio
from datetime import datetime, timedelta
import pytz
from src.data_fetcher import DataFetcher
from src.config import Config
from src.bots.strat_bot import STRATPatternBot

ET = pytz.timezone('America/New_York')

async def main():
    print("\n🎯 Quick Test: 1-3-1 Detection")
    print("="*60)
    
    fetcher = DataFetcher(Config.POLYGON_API_KEY)
    strat_bot = STRATPatternBot(data_fetcher=fetcher)
    
    # Test specific stocks from the other bot
    test_stocks = ['JPM', 'SPY', 'COST', 'AAPL', 'MSFT']
    
    now_et = datetime.now(ET)
    if now_et.hour < 8:
        target_date = (now_et - timedelta(days=1)).date()
    else:
        target_date = now_et.date()
    
    print(f"Target: {target_date} 20:00 ET\n")
    
    for symbol in test_stocks:
        print(f"{symbol:6} ", end='', flush=True)
        
        # Fetch 12h bars
        bars_12h = await strat_bot.fetch_and_compose_12h_bars(symbol, n_bars=6)
        
        if len(bars_12h) < 4:
            print("❌ Not enough bars")
            continue
        
        # Check last bar
        last_bar_time = datetime.fromtimestamp(bars_12h[-1]['t'] / 1000, tz=pytz.UTC).astimezone(ET)
        
        if last_bar_time.date() != target_date or last_bar_time.hour != 20:
            print(f"❌ Last bar: {last_bar_time.strftime('%m/%d %H:%M')}")
            continue
        
        # Type bars
        typed = strat_bot.strat_12h_detector.attach_types(bars_12h)
        
        if len(typed) >= 3:
            b1, b2, b3 = typed[-3], typed[-2], typed[-1]
            pattern = f"{b1.type}-{b2.type}-{b3.type}"
            
            if pattern == "1-3-1":
                trigger = (b3.h + b3.l) / 2
                print(f"✅ 1-3-1! Trigger: ${trigger:.2f}")
            else:
                print(f"Pattern: {pattern}")
    
    await fetcher.close()
    print("\n" + "="*60)

asyncio.run(main())

