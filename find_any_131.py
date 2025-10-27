"""Find ANY 1-3-1 patterns in JPM data"""
import asyncio
from datetime import datetime, timedelta
import pytz
from src.data_fetcher import DataFetcher
from src.config import Config
from src.bots.strat_bot import STRATPatternBot

ET = pytz.timezone('America/New_York')

async def main():
    fetcher = DataFetcher(Config.POLYGON_API_KEY)
    strat_bot = STRATPatternBot(data_fetcher=fetcher)
    
    symbol = 'JPM'
    
    # Fetch more bars
    bars_12h = await strat_bot.fetch_and_compose_12h_bars(symbol, n_bars=10)
    
    print(f"\n{symbol} - All 12h bars:")
    print("="*80)
    for i, bar in enumerate(bars_12h, 1):
        bar_time = datetime.fromtimestamp(bar['t'] / 1000, tz=pytz.UTC).astimezone(ET)
        print(f"{i}. {bar_time.strftime('%m/%d %H:%M ET')}: H=${bar['h']:.2f}, L=${bar['l']:.2f}, C=${bar['c']:.2f}")
    
    # Type all bars
    typed = strat_bot.strat_12h_detector.attach_types(bars_12h)
    
    print(f"\nTyped bars:")
    print("="*80)
    for i, tb in enumerate(typed, 1):
        bar_time = datetime.fromtimestamp(tb.t / 1000, tz=pytz.UTC).astimezone(ET)
        print(f"{i}. {bar_time.strftime('%m/%d %H:%M ET')}: Type {tb.type}")
    
    # Find ALL 1-3-1 patterns
    print(f"\nSearching for 1-3-1 patterns:")
    print("="*80)
    
    found_any = False
    for i in range(2, len(typed)):
        b1, b2, b3 = typed[i-2], typed[i-1], typed[i]
        
        if b1.type == "1" and b2.type == "3" and b3.type == "1":
            t1 = datetime.fromtimestamp(b1.t / 1000, tz=pytz.UTC).astimezone(ET)
            t2 = datetime.fromtimestamp(b2.t / 1000, tz=pytz.UTC).astimezone(ET)
            t3 = datetime.fromtimestamp(b3.t / 1000, tz=pytz.UTC).astimezone(ET)
            
            trigger = (b3.h + b3.l) / 2
            
            print(f"\n✅ 1-3-1 FOUND:")
            print(f"   Bar 1: {t1.strftime('%m/%d %H:%M ET')} - Type 1")
            print(f"   Bar 2: {t2.strftime('%m/%d %H:%M ET')} - Type 3")
            print(f"   Bar 3: {t3.strftime('%m/%d %H:%M ET')} - Type 1")
            print(f"   Trigger: ${trigger:.2f}")
            found_any = True
    
    if not found_any:
        print("\n❌ No 1-3-1 patterns found in any position")
    
    await fetcher.close()

asyncio.run(main())

