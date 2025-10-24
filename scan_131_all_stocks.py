"""
Scan all stocks for 1-3-1 Miyagi patterns and post to Discord
"""
import asyncio
import logging
from datetime import datetime
import pytz
from src.data_fetcher import DataFetcher
from src.config import Config
from src.bots.strat_bot import STRATPatternBot

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

ET = pytz.timezone('America/New_York')

async def scan_all_stocks_for_131():
    """Scan all stocks for 1-3-1 Miyagi patterns"""
    
    print("\n" + "="*80)
    print("🎯 SCANNING ALL STOCKS FOR 1-3-1 MIYAGI PATTERNS")
    print("="*80)
    now_et = datetime.now(ET)
    print(f"Time: {now_et.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    print(f"Current Hour: {now_et.hour}")
    print("="*80)
    print("\n⚠️  NOTE: 1-3-1 patterns are scanned after 20:00 ET (8pm)")
    print("    This ensures 36 hours of data (3 bars × 12 hours)")
    print("    Patterns found now will be posted to Discord.\n")
    print("="*80 + "\n")
    
    # Initialize
    fetcher = DataFetcher(Config.POLYGON_API_KEY)
    strat_bot = STRATPatternBot(data_fetcher=fetcher)
    
    # Use a comprehensive list of liquid stocks
    # Top stocks across all sectors (same as bot uses)
    all_stocks = [
        # Tech/Communications
        'AAPL', 'MSFT', 'GOOGL', 'AMZN', 'META', 'NVDA', 'TSLA', 'AMD', 'INTC', 'NFLX',
        'ADBE', 'CRM', 'ORCL', 'CSCO', 'AVGO', 'QCOM', 'TXN', 'ASML', 'NOW',
        # Finance
        'JPM', 'BAC', 'WFC', 'GS', 'MS', 'C', 'BLK', 'SCHW', 'AXP', 'USB', 'PNC',
        # Healthcare
        'UNH', 'JNJ', 'LLY', 'ABBV', 'MRK', 'PFE', 'TMO', 'ABT', 'DHR', 'AMGN', 'CVS',
        # Consumer
        'WMT', 'HD', 'MCD', 'NKE', 'SBUX', 'LOW', 'TGT', 'COST', 'DIS', 'CMCSA',
        # Industrials
        'CAT', 'BA', 'HON', 'UPS', 'RTX', 'LMT', 'GE', 'MMM', 'DE', 'UNP',
        # Energy
        'XOM', 'CVX', 'COP', 'SLB', 'EOG', 'PXD', 'MPC', 'PSX', 'VLO',
        # ETFs
        'SPY', 'QQQ', 'IWM', 'DIA', 'VXX', 'GLD', 'SLV', 'USO', 'TLT', 'HYG'
    ]
    
    print(f"📊 Scanning {len(all_stocks)} stocks from watchlist...")
    print("This will take a few minutes...\n")
    
    patterns_found = []
    scanned = 0
    errors = 0
    posted_patterns = set()  # Track posted patterns to avoid duplicates
    
    # Scan in batches to avoid rate limits
    for i, symbol in enumerate(all_stocks, 1):
        try:
            # Scan specifically for 1-3-1 patterns
            bars_12h = await strat_bot.fetch_and_compose_12h_bars(symbol, n_bars=10)
            
            if len(bars_12h) < 4:
                continue
            
            typed_bars = strat_bot.strat_12h_detector.attach_types(bars_12h)
            miyagi = strat_bot.strat_12h_detector.detect_131_miyagi(typed_bars)
            
            if miyagi:
                for sig in miyagi:
                    pattern = {
                        'symbol': symbol,
                        'signal': sig,
                        'bars_12h': bars_12h
                    }
                    patterns_found.append(pattern)
                    
                    # Show immediate feedback
                    if sig['kind'] == '131-complete':
                        timestamp_ms = sig['completed_at']
                        time_obj = datetime.fromtimestamp(timestamp_ms / 1000, tz=pytz.UTC).astimezone(ET)
                        print(f"  ✅ {symbol:6} - 1-3-1 Miyagi @ {time_obj.strftime('%m/%d %H:%M ET')} (Entry: ${sig['entry']:.2f})")
                    elif sig['kind'] in ['131-4th-2U-PUTS', '131-4th-2D-CALLS']:
                        direction = sig.get('direction', 'N/A')
                        print(f"  🔔 {symbol:6} - 1-3-1 4th Bar: {direction} bias")
            
            scanned += 1
            
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

