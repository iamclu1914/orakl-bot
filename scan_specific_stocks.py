"""Scan specific stocks mentioned by other bot to understand the pattern"""
import asyncio
from datetime import datetime, timedelta
import pytz
from src.data_fetcher import DataFetcher
from src.config import Config
from src.utils.strat_12h_composer import STRAT12HourComposer
from src.utils.strat_12h import STRAT12HourDetector

ET = pytz.timezone('America/New_York')

async def analyze_stock(symbol, expected_trigger):
    """Analyze a stock to understand its 1-3-1 pattern"""
    fetcher = DataFetcher(Config.POLYGON_API_KEY)
    composer = STRAT12HourComposer()
    detector = STRAT12HourDetector()
    
    # Fetch data
    end_date = datetime.now()
    start_date = end_date - timedelta(days=3)
    
    bars_60m = await fetcher.get_aggregates(
        symbol,
        timespan='minute',
        multiplier=60,
        from_date=start_date.strftime('%Y-%m-%d'),
        to_date=end_date.strftime('%Y-%m-%d')
    )
    
    if bars_60m is None or len(bars_60m) == 0:
        return None
    
    # Normalize
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
    
    # Compose 12h bars
    bars_12h = composer.compose_12h_bars(normalized)
    
    # Type them
    typed = detector.attach_types(bars_12h)
    
    # Check last 3 bars
    if len(typed) >= 3:
        last_3 = typed[-3:]
        pattern = f"{last_3[0].type}-{last_3[1].type}-{last_3[2].type}"
        
        # Get timestamps
        time1 = datetime.fromtimestamp(last_3[0].t / 1000, tz=pytz.UTC).astimezone(ET)
        time2 = datetime.fromtimestamp(last_3[1].t / 1000, tz=pytz.UTC).astimezone(ET)
        time3 = datetime.fromtimestamp(last_3[2].t / 1000, tz=pytz.UTC).astimezone(ET)
        
        # Calculate trigger
        trigger = (last_3[2].h + last_3[2].l) / 2.0
        
        result = {
            'symbol': symbol,
            'pattern': pattern,
            'bar1_time': time1.strftime('%m/%d %H:%M ET'),
            'bar2_time': time2.strftime('%m/%d %H:%M ET'),
            'bar3_time': time3.strftime('%m/%d %H:%M ET'),
            'bar1_type': last_3[0].type,
            'bar2_type': last_3[1].type,
            'bar3_type': last_3[2].type,
            'trigger': trigger,
            'expected': expected_trigger,
            'bar3_h': last_3[2].h,
            'bar3_l': last_3[2].l,
            'bar3_c': last_3[2].c
        }
        
        await fetcher.close()
        return result
    
    await fetcher.close()
    return None

async def main():
    # Stocks from other bot
    stocks = {
        'JPM': 294.5,
        'SPY': 671.59,
        'ASTS': 72.26,
        'DIA': 467.03,
        'COST': 941.45,
        'PLTR': 180.56,
        'SOFI': 28.12,
        'MU': 207.33,
        'RIVN': 13.1,
        'AAPL': 259.61,
        'WMT': 106.53,
        'MSFT': 520.79,
        'NVDA': 182.31
    }
    
    print("\n" + "="*80)
    print("🔍 ANALYZING STOCKS FROM OTHER BOT")
    print("="*80)
    print(f"Checking last 3 bars to find commonality...\n")
    
    results = []
    
    for symbol, expected in list(stocks.items())[:5]:  # Check first 5
        print(f"Analyzing {symbol}...")
        result = await analyze_stock(symbol, expected)
        if result:
            results.append(result)
        await asyncio.sleep(0.3)
    
    # Display results
    print("\n" + "="*80)
    print("PATTERN ANALYSIS")
    print("="*80)
    
    for r in results:
        print(f"\n{r['symbol']}:")
        print(f"  Last 3 bars: {r['pattern']}")
        print(f"    Bar 1: {r['bar1_time']} - Type {r['bar1_type']}")
        print(f"    Bar 2: {r['bar2_time']} - Type {r['bar2_type']}")
        print(f"    Bar 3: {r['bar3_time']} - Type {r['bar3_type']}")
        print(f"  Bar 3 details: H=${r['bar3_h']:.2f}, L=${r['bar3_l']:.2f}, C=${r['bar3_c']:.2f}")
        print(f"  My trigger: ${r['trigger']:.2f}")
        print(f"  Their trigger: ${r['expected']}")
        print(f"  Match: {'✅' if abs(r['trigger'] - r['expected']) < 1 else '❌'}")
    
    # Find commonality
    print("\n" + "="*80)
    print("COMMONALITY:")
    print("="*80)
    
    patterns = [r['pattern'] for r in results]
    bar1_times = [r['bar1_time'] for r in results]
    bar3_times = [r['bar3_time'] for r in results]
    
    print(f"Patterns: {set(patterns)}")
    print(f"Bar 1 times: {set(bar1_times)}")
    print(f"Bar 3 times: {set(bar3_times)}")

if __name__ == "__main__":
    asyncio.run(main())

