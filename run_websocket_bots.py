"""
ORAKL Bot - WebSocket Real-Time Launcher
Runs all 6 bots simultaneously using Polygon WebSocket streaming
"""
import asyncio
import os
from dotenv import load_dotenv
from src.bots.golden_sweeps_bot_ws import GoldenSweepsBotWS
from src.bots.sweeps_bot_ws import SweepsBotWS
from src.bots.bullseye_bot_ws import BullseyeBotWS
from src.bots.scalps_bot_ws import ScalpsBotWS
from src.bots.darkpool_bot_ws import DarkpoolBotWS
from src.bots.breakouts_bot_ws import BreakoutsBotWS
from src.options_analyzer import OptionsAnalyzer
from src.utils.logger import logger

# Load environment variables
load_dotenv()


async def main():
    """Run all WebSocket bots concurrently"""
    logger.info("=" * 80)
    logger.info("🚀 ORAKL Bot - WebSocket Real-Time Mode Starting")
    logger.info("=" * 80)

    # Load configuration
    watchlist = os.getenv('WATCHLIST', 'SPY,QQQ').split(',')
    watchlist = [s.strip() for s in watchlist]

    logger.info(f"📊 Monitoring {len(watchlist)} symbols: {', '.join(watchlist)}")

    # Initialize shared analyzer
    analyzer = OptionsAnalyzer()

    # Initialize all WebSocket bots
    golden_sweeps_bot = GoldenSweepsBotWS(
        webhook_url=os.getenv('GOLDEN_SWEEPS_WEBHOOK'),
        watchlist=watchlist,
        analyzer=analyzer
    )

    sweeps_bot = SweepsBotWS(
        webhook_url=os.getenv('SWEEPS_WEBHOOK'),
        watchlist=watchlist,
        analyzer=analyzer
    )

    bullseye_bot = BullseyeBotWS(
        webhook_url=os.getenv('BULLSEYE_WEBHOOK'),
        watchlist=watchlist,
        analyzer=analyzer
    )

    scalps_bot = ScalpsBotWS(
        webhook_url=os.getenv('SCALPS_WEBHOOK'),
        watchlist=watchlist,
        analyzer=analyzer
    )

    darkpool_bot = DarkpoolBotWS(
        webhook_url=os.getenv('DARKPOOL_WEBHOOK'),
        watchlist=watchlist
    )

    breakouts_bot = BreakoutsBotWS(
        webhook_url=os.getenv('BREAKOUTS_WEBHOOK'),
        watchlist=watchlist
    )

    logger.info("✅ All 6 bots initialized successfully")
    logger.info("🔌 Connecting to Polygon WebSocket...")

    # Run all bots concurrently
    try:
        await asyncio.gather(
            golden_sweeps_bot.run(),
            sweeps_bot.run(),
            bullseye_bot.run(),
            scalps_bot.run(),
            darkpool_bot.run(),
            breakouts_bot.run(),
            return_exceptions=True
        )
    except KeyboardInterrupt:
        logger.info("\n🛑 Shutting down WebSocket bots...")
    except Exception as e:
        logger.error(f"❌ Fatal error: {e}")
        raise


if __name__ == "__main__":
    # Run the asyncio event loop
    asyncio.run(main())
