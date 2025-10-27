"""Verify COST classification to match TradingView"""
import asyncio
from datetime import datetime, timedelta
import pytz
from src.data_fetcher import DataFetcher
from src.config import Config
from src.utils.strat_12h_composer import STRAT12HourComposer
from src.utils.strat_12h import STRAT12HourDetector

ET = pytz.timezone('America/New_York')

async def main():
    fetcher = DataFetcher(Config.POLYGON_API_KEY)
    composer = STRAT12HourComposer()
    detector = STRAT12HourDetector()
    
    # Fetch data
    end_date = datetime.now()
    start_date = end_date - timedelta(days=3)
    
    bars_60m = await fetcher.get_aggregates(
        'COST',
        timespan='minute',
        multiplier=60,
        from_date=start_date.strftime('%Y-%m-%d'),
        to_date=end_date.strftime('%Y-%m-%d')
    )
    
    if hasattr(bars_60m, 'to_dict'):
        bars_list = bars_60m.to_dict('records')
    else:
        bars_list = bars_60m
    
    normalized = []
    for bar in bars_list:
        timestamp = bar.get('t', bar.get('timestamp', 0))
        if hasattr(timestamp, 'timestamp'):
            timestamp_ms = int(timestamp.timestamp() * 1000)
        else:
            timestamp_ms = int(timestamp) if timestamp else 0
        
        normalized.append({
            'o': bar.get('o', bar.get('open', 0)),
            'h': bar.get('h', bar.get('high', 0)),
            'l': bar.get('l', bar.get('low', 0)),
            'c': bar.get('c', bar.get('close', 0)),
            'v': bar.get('v', bar.get('volume', 0)),
            't': timestamp_ms
        })
    
    bars_12h = composer.compose_12h_bars(normalized)
    
    print("COST 12-Hour Bars (Last 5):")
    print("="*80)
    for bar in bars_12h[-5:]:
        bar_time = datetime.fromtimestamp(bar['t'] / 1000, tz=pytz.UTC).astimezone(ET)
        print(f"{bar_time.strftime('%m/%d %H:%M ET')}: O=${bar['o']:.2f} H=${bar['h']:.2f} L=${bar['l']:.2f} C=${bar['c']:.2f}")
    
    # Type them
    typed = detector.attach_types(bars_12h)
    
    print("\nCOST Typed Bars (Last 4):")
    print("="*80)
    for i, tb in enumerate(typed[-4:], 1):
        bar_time = datetime.fromtimestamp(tb.t / 1000, tz=pytz.UTC).astimezone(ET)
        print(f"{i}. {bar_time.strftime('%m/%d %H:%M ET')}: Type {tb.type:3} - H=${tb.h:.2f}, L=${tb.l:.2f}, C=${tb.c:.2f}")
    
    # Manual classification of last 3
    print("\nManual Classification Check (Last 3 bars):")
    print("="*80)
    
    if len(bars_12h) >= 4:
        # Bar 1 = bars_12h[-4] (to compare with)
        # Bar 2 = bars_12h[-3] (10/21 20:00)
        # Bar 3 = bars_12h[-2] (10/22 20:00)  
        # Bar 4 = bars_12h[-1] (10/23 20:00)
        
        bar0 = bars_12h[-4]
        bar1 = bars_12h[-3]
        bar2 = bars_12h[-2]
        bar3 = bars_12h[-1]
        
        # Classify bar1 vs bar0
        print(f"\nBar 1 (10/21 20:00) vs Bar 0:")
        print(f"  Bar 0: H=${bar0['h']:.2f}, L=${bar0['l']:.2f}, C=${bar0['c']:.2f}")
        print(f"  Bar 1: H=${bar1['h']:.2f}, L=${bar1['l']:.2f}, C=${bar1['c']:.2f}")
        print(f"  High > prevHigh: {bar1['h'] > bar0['h']}")
        print(f"  Low < prevLow: {bar1['l'] < bar0['l']}")
        print(f"  High <= prevHigh: {bar1['h'] <= bar0['h']}")
        print(f"  Low >= prevLow: {bar1['l'] >= bar0['l']}")
        print(f"  Close > prevClose: {bar1['c'] > bar0['c']}")
        print(f"  Close < prevClose: {bar1['c'] < bar0['c']}")
        
        # Determine type
        if bar1['h'] > bar0['h'] and bar1['l'] < bar0['l']:
            type1 = "3"
        elif bar1['h'] <= bar0['h'] and bar1['l'] >= bar0['l']:
            type1 = "1"
        elif bar1['c'] > bar0['c']:
            type1 = "2U"
        elif bar1['c'] < bar0['c']:
            type1 = "2D"
        else:
            type1 = "1"
        
        print(f"  Classification: {type1}")
        
        # Bar 2 vs Bar 1
        print(f"\nBar 2 (10/22 20:00) vs Bar 1:")
        print(f"  Bar 2: H=${bar2['h']:.2f}, L=${bar2['l']:.2f}, C=${bar2['c']:.2f}")
        if bar2['h'] > bar1['h'] and bar2['l'] < bar1['l']:
            type2 = "3"
        elif bar2['h'] <= bar1['h'] and bar2['l'] >= bar1['l']:
            type2 = "1"
        elif bar2['c'] > bar1['c']:
            type2 = "2U"
        else:
            type2 = "2D"
        print(f"  Classification: {type2}")
        
        # Bar 3 vs Bar 2
        print(f"\nBar 3 (10/23 20:00) vs Bar 2:")
        print(f"  Bar 3: H=${bar3['h']:.2f}, L=${bar3['l']:.2f}, C=${bar3['c']:.2f}")
        if bar3['h'] > bar2['h'] and bar3['l'] < bar2['l']:
            type3 = "3"
        elif bar3['h'] <= bar2['h'] and bar3['l'] >= bar2['l']:
            type3 = "1"
        elif bar3['c'] > bar2['c']:
            type3 = "2U"
        else:
            type3 = "2D"
        print(f"  Classification: {type3}")
        
        print(f"\nFinal Pattern: {type1}-{type2}-{type3}")
        print(f"TradingView says: 1-3-1")
        print(f"My classification: {type1}-{type2}-{type3}")
        
        if f"{type1}-{type2}-{type3}" == "1-3-1":
            trigger = (bar3['h'] + bar3['l']) / 2
            print(f"\n✅ MATCHES! Trigger: ${trigger:.2f}")
        else:
            print(f"\n❌ MISMATCH - Need to investigate classification rules")
    
    await fetcher.close()

asyncio.run(main())

