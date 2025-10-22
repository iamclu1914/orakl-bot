"""
ORAKL Bot - Kafka Consumer Launcher
Consumes real-time data from your Polygon → Kafka pipeline
"""
import asyncio
import os
import logging
from dotenv import load_dotenv
from src.bots.golden_sweeps_bot_kafka import GoldenSweepsBotKafka
from src.options_analyzer import OptionsAnalyzer

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()


async def main():
    """Run all Kafka consumer bots concurrently"""
    logger.info("=" * 80)
    logger.info("🚀 ORAKL Bot - Kafka Consumer Mode Starting")
    logger.info("=" * 80)

    # Load configuration
    watchlist = os.getenv('WATCHLIST', 'SPY,QQQ').split(',')
    watchlist = [s.strip() for s in watchlist]

    logger.info(f"📊 Monitoring {len(watchlist)} symbols: {', '.join(watchlist[:10])}...")
    logger.info(f"🔌 Kafka Broker: {os.getenv('KAFKA_BOOTSTRAP_SERVERS')}")
    logger.info(f"👥 Consumer Group: {os.getenv('KAFKA_CONSUMER_GROUP')}")

    # Initialize shared analyzer
    analyzer = OptionsAnalyzer()

    # Initialize Kafka consumer bot (Golden Sweeps for now)
    golden_sweeps_bot = GoldenSweepsBotKafka(
        webhook_url=os.getenv('GOLDEN_SWEEPS_WEBHOOK'),
        watchlist=watchlist,
        analyzer=analyzer
    )

    logger.info("✅ Golden Sweeps bot initialized")
    logger.info("🔌 Connecting to Kafka topics: raw-trades")
    logger.info("⏳ Waiting for messages from Kafka stream...")
    logger.info("=" * 80)

    # Run bot
    try:
        await golden_sweeps_bot.run()
    except KeyboardInterrupt:
        logger.info("\n🛑 Shutting down Kafka consumers...")
    except Exception as e:
        logger.error(f"❌ Fatal error: {e}")
        raise


if __name__ == "__main__":
    # Run the asyncio event loop
    asyncio.run(main())
