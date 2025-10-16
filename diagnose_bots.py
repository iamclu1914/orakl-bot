"""
Diagnostic script to check why bots aren't sending alerts
"""
import asyncio
from datetime import datetime
import pytz
from src.config import Config
from src.data_fetcher import DataFetcher
from src.watchlist_manager import SmartWatchlistManager

async def diagnose():
    print("=" * 60)
    print("ORAKL Bot Diagnostic Tool")
    print("=" * 60)

    # 1. Check current time
    eastern = pytz.timezone('America/New_York')
    now_et = datetime.now(eastern)
    print(f"\n1. Current Time: {now_et.strftime('%I:%M %p ET on %A, %B %d, %Y')}")
    print(f"   Weekday: {now_et.weekday()} (0=Monday, 6=Sunday)")

    # 2. Check market hours
    market_open = now_et.replace(hour=9, minute=30, second=0, microsecond=0)
    market_close = now_et.replace(hour=16, minute=0, second=0, microsecond=0)
    is_market_hours = market_open <= now_et <= market_close and now_et.weekday() < 5
    print(f"\n2. Market Hours Check:")
    print(f"   Market Open: {market_open.strftime('%I:%M %p ET')}")
    print(f"   Market Close: {market_close.strftime('%I:%M %p ET')}")
    print(f"   Should be open: {'YES' if is_market_hours else 'NO'}")

    # 3. Test Polygon API
    print(f"\n3. Testing Polygon API...")
    print(f"   API Key: {Config.POLYGON_API_KEY[:10]}...{Config.POLYGON_API_KEY[-4:]}")

    async with DataFetcher(Config.POLYGON_API_KEY) as fetcher:
        # Test market status
        try:
            is_open = await fetcher.is_market_open()
            print(f"   Market Status (API): {'OPEN' if is_open else 'CLOSED'}")
        except Exception as e:
            print(f"   Market Status Error: {e}")

        # Test stock price fetch
        try:
            price = await fetcher.get_stock_price('AAPL')
            print(f"   Test Stock Price (AAPL): ${price}")
        except Exception as e:
            print(f"   Stock Price Error: {e}")

        # Test options data
        try:
            trades = await fetcher.get_options_trades('AAPL')
            print(f"   Test Options Trades (AAPL): {len(trades)} trades found")
        except Exception as e:
            print(f"   Options Trades Error: {e}")

    # 4. Check watchlist
    print(f"\n4. Testing Watchlist...")
    print(f"   Watchlist Mode: {Config.WATCHLIST_MODE}")

    try:
        manager = SmartWatchlistManager(Config.POLYGON_API_KEY)
        watchlist = await manager.get_watchlist()
        print(f"   Watchlist Size: {len(watchlist)} tickers")
        if len(watchlist) > 0:
            print(f"   Sample Tickers: {', '.join(watchlist[:10])}")
        else:
            print(f"   WARNING: Watchlist is EMPTY!")
    except Exception as e:
        print(f"   Watchlist Error: {e}")

    # 5. Check webhook configuration
    print(f"\n5. Webhook Configuration:")
    webhooks = {
        'Golden Sweeps': Config.GOLDEN_SWEEPS_WEBHOOK,
        'Sweeps': Config.SWEEPS_WEBHOOK,
        'Bullseye': Config.BULLSEYE_WEBHOOK,
        'Scalps': Config.SCALPS_WEBHOOK,
        'Breakouts': Config.BREAKOUTS_WEBHOOK,
        'Darkpool': Config.DARKPOOL_WEBHOOK,
        'ORAKL Flow': Config.ORAKL_FLOW_WEBHOOK,
        'Unusual Activity': Config.UNUSUAL_ACTIVITY_WEBHOOK,
        'STRAT': Config.STRAT_WEBHOOK
    }

    for name, url in webhooks.items():
        status = "CONFIGURED" if url and url != Config.DISCORD_WEBHOOK_URL else "DEFAULT"
        print(f"   {name}: {status}")

    # 6. Check bot intervals
    print(f"\n6. Bot Scan Intervals:")
    print(f"   Golden Sweeps: {Config.GOLDEN_SWEEPS_INTERVAL}s")
    print(f"   Sweeps: {Config.SWEEPS_INTERVAL}s")
    print(f"   Bullseye: {Config.BULLSEYE_INTERVAL}s")
    print(f"   Scalps: {Config.SCALPS_INTERVAL}s")
    print(f"   Breakouts: {Config.BREAKOUTS_INTERVAL}s")
    print(f"   Darkpool: {Config.DARKPOOL_INTERVAL}s")
    print(f"   ORAKL Flow: {Config.TRADY_FLOW_INTERVAL}s")
    print(f"   Unusual Activity: {Config.UNUSUAL_VOLUME_INTERVAL}s")
    print(f"   STRAT: {Config.STRAT_INTERVAL}s")

    # 7. Check score thresholds
    print(f"\n7. Minimum Score Thresholds:")
    print(f"   Golden Sweeps: {Config.MIN_GOLDEN_SCORE}/100")
    print(f"   Sweeps: {Config.MIN_SWEEP_SCORE}/100")
    print(f"   Bullseye: {Config.MIN_BULLSEYE_SCORE}/100")
    print(f"   Scalps: {Config.MIN_SCALP_SCORE}/100")
    print(f"   Breakouts: {Config.MIN_BREAKOUT_SCORE}/100")
    print(f"   Darkpool: {Config.MIN_DARKPOOL_SCORE}/100")
    print(f"   Unusual Activity: {Config.MIN_UNUSUAL_VOLUME_SCORE}/100")

    print("\n" + "=" * 60)
    print("Diagnostic Complete")
    print("=" * 60)

if __name__ == "__main__":
    asyncio.run(diagnose())
