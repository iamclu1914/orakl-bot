"""
Scan all stocks for 1-3-1 Miyagi patterns and post to Discord
"""
import asyncio
import logging
from datetime import datetime, timedelta
import pytz
from src.data_fetcher import DataFetcher
from src.config import Config
from src.bots.strat_bot import STRATPatternBot
from src.utils.sector_watchlist import STRAT_COMPLETE_WATCHLIST

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

ET = pytz.timezone('America/New_York')

async def scan_all_stocks_for_131():
    """Scan all stocks for 1-3-1 Miyagi patterns"""
    
    print("\n" + "="*80)
    print("🎯 SCANNING FOR 1-3-1 MIYAGI PATTERNS FROM TODAY'S TRADING DAY")
    print("="*80)
    now_et = datetime.now(ET)
    print(f"Time: {now_et.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    
    # Calculate the most recent 20:00 ET close
    # If it's after midnight but before 8am, use yesterday's 20:00
    # If it's after 8pm but before midnight, use today's 20:00
    if now_et.hour < 8:
        # After midnight, before 8am - target yesterday's 20:00
        target_date = (now_et - timedelta(days=1)).date()
    else:
        # After 8am - target today's 20:00 (even if it hasn't closed yet)
        target_date = now_et.date()
    
    print(f"Target: Patterns closing at {target_date} 20:00 ET")
    print("="*80 + "\n")
    
    # Initialize
    fetcher = DataFetcher(Config.POLYGON_API_KEY)
    strat_bot = STRATPatternBot(data_fetcher=fetcher)
    
    # Use the complete STRAT watchlist (all mega/large caps + sector ETFs)
    all_stocks = STRAT_COMPLETE_WATCHLIST
    
    print(f"📊 Scanning {len(all_stocks)} stocks from watchlist...")
    print("This will take a few minutes...\n")
    
    patterns_found = []
    scanned = 0
    errors = 0
    posted_patterns = set()  # Track posted patterns to avoid duplicates
    
    # Scan in batches to avoid rate limits
    for i, symbol in enumerate(all_stocks, 1):
        try:
            # Scan for 1-3-1: Last 36 hours = Last 3 bars (12h each)
            # Need at least 4 bars to classify 3 bars
            bars_12h = await strat_bot.fetch_and_compose_12h_bars(symbol, n_bars=6)
            
            scanned += 1
            
            if len(bars_12h) < 4:
                continue
            
            # We want patterns from today (either 08:00 or 20:00)
            # Just ensure we have recent data
            last_bar_time = datetime.fromtimestamp(bars_12h[-1]['t'] / 1000, tz=pytz.UTC).astimezone(ET)
            if last_bar_time.date() < target_date:
                logger.debug(f"{symbol}: Data too old, last bar: {last_bar_time.strftime('%m/%d')}")
                continue
            
            # Type the bars
            typed_bars = strat_bot.strat_12h_detector.attach_types(bars_12h)
            
            # Find ANY 1-3-1 patterns in the data (not just last 3)
            miyagi_patterns = strat_bot.strat_12h_detector.detect_131_miyagi(typed_bars)
            
            for sig in miyagi_patterns:
                if sig['kind'] == '131-complete':
                    # Pattern MUST complete at 20:00 PM on target date
                    pattern_time = datetime.fromtimestamp(sig['completed_at'] / 1000, tz=pytz.UTC).astimezone(ET)
                    
                    # Strict check: must be target date AND 20:00 hour
                    if pattern_time.date() != target_date or pattern_time.hour != 20:
                        logger.debug(f"{symbol}: Pattern at {pattern_time.strftime('%m/%d %H:%M')}, not {target_date} 20:00")
                        continue  # Skip patterns not completing at 20:00
                    
                    # Pattern already has all the data we need
                    pattern = {
                        'symbol': symbol,
                        'signal': sig,
                        'bars_12h': bars_12h
                    }
                    patterns_found.append(pattern)
                    print(f"  ✅ {symbol:6} - 1-3-1 @ {pattern_time.strftime('%m/%d %H:%M ET')} (Entry: ${sig['entry']:.2f})")
            
            # Progress update every 50 stocks
            if i % 50 == 0:
                print(f"\n📈 Progress: {i}/{len(all_stocks)} stocks scanned ({patterns_found.__len__()} patterns found)\n")
            
            # Rate limiting
            await asyncio.sleep(0.2)
            
        except Exception as e:
            errors += 1
            logger.debug(f"Error scanning {symbol}: {e}")
            continue
    
    # Summary
    print("\n" + "="*80)
    print("SCAN COMPLETE")
    print("="*80)
    print(f"Scanned: {scanned} stocks")
    print(f"Errors: {errors}")
    print(f"Patterns Found: {len(patterns_found)}")
    print("="*80 + "\n")
    
    # Post to Discord
    if patterns_found:
        print(f"📤 Posting {len(patterns_found)} patterns to Discord...\n")
        
        for pattern in patterns_found:
            symbol = pattern['symbol']
            sig = pattern['signal']
            
            # Create signal in format expected by send_alert
            if sig['kind'] == '131-complete':
                discord_signal = {
                    'symbol': symbol,
                    'pattern': '1-3-1 Miyagi',
                    'completed_at': sig['completed_at'],
                    'entry': sig['entry'],
                    'type': 'Pending 4th bar',
                    'confidence_score': 0.75,
                    'timeframe': '12h',
                    'bars': '1→3→1',
                    'pattern_bars': sig.get('pattern_bars', {})  # Include bar details for trigger calc
                }
            elif sig['kind'] in ['131-4th-2U-PUTS', '131-4th-2D-CALLS']:
                discord_signal = {
                    'symbol': symbol,
                    'pattern': '1-3-1 Miyagi (Confirmed)',
                    'completed_at': sig['at'],
                    'entry': sig['entry'],
                    'type': sig.get('direction', 'N/A'),
                    'confidence_score': 0.85,
                    'timeframe': '12h',
                    'bars': '1→3→1→' + ('2U' if 'PUTS' in sig['kind'] else '2D')
                }
            else:
                continue
            
            # Check for duplicates before posting
            # Create unique signature for pattern
            timestamp_ms = discord_signal['completed_at']
            pattern_signature = f"{symbol}_{discord_signal['pattern']}_{timestamp_ms}"
            
            if pattern_signature in posted_patterns:
                print(f"  ⚠️  Skipping {symbol} - already posted")
                continue
            
            # Post to Discord
            try:
                strat_bot.send_alert(discord_signal)
                posted_patterns.add(pattern_signature)
                print(f"  ✅ Posted {symbol} to Discord")
                await asyncio.sleep(2)  # Delay between posts to avoid rate limits
            except Exception as e:
                print(f"  ❌ Failed to post {symbol}: {e}")
        
        print(f"\n✅ Posted all {len(patterns_found)} patterns to Discord!")
    else:
        print("No 1-3-1 Miyagi patterns found in current data.")
        print("\nNote: 1-3-1 is a relatively rare pattern that requires:")
        print("  - Inside bar (compression)")
        print("  - Outside bar (expansion)")
        print("  - Inside bar again (compression)")
        print("\nPatterns will be automatically detected and posted when they form.")
    
    await fetcher.close()
    
    print("\n" + "="*80)
    print("✅ SCAN AND POST COMPLETE")
    print("="*80)

if __name__ == "__main__":
    asyncio.run(scan_all_stocks_for_131())

