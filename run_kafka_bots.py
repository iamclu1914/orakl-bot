"""
ORAKL Bot - Kafka Consumer Launcher
Consumes real-time data from your Polygon → Kafka pipeline
"""
import asyncio
import os
import logging
from dotenv import load_dotenv
from src.bots.golden_sweeps_bot_kafka import GoldenSweepsBotKafka
from src.bots.sweeps_bot_kafka import SweepsBotKafka
from src.bots.bullseye_bot_kafka import BullseyeBotKafka
from src.bots.scalps_bot_kafka import ScalpsBotKafka
from src.bots.orakl_flow_bot_kafka import OraklFlowBotKafka
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

    # Initialize all options bots (all consume from processed-flows)
    golden_sweeps_bot = GoldenSweepsBotKafka(
        webhook_url=os.getenv('GOLDEN_SWEEPS_WEBHOOK'),
        watchlist=watchlist,
        analyzer=analyzer
    )

    sweeps_bot = SweepsBotKafka(
        webhook_url=os.getenv('SWEEPS_WEBHOOK'),
        watchlist=watchlist,
        analyzer=analyzer
    )

    bullseye_bot = BullseyeBotKafka(
        webhook_url=os.getenv('BULLSEYE_WEBHOOK'),
        watchlist=watchlist,
        analyzer=analyzer
    )

    scalps_bot = ScalpsBotKafka(
        webhook_url=os.getenv('SCALPS_WEBHOOK'),
        watchlist=watchlist,
        analyzer=analyzer
    )

    orakl_flow_bot = OraklFlowBotKafka(
        webhook_url=os.getenv('ORAKL_FLOW_WEBHOOK'),
        watchlist=watchlist,
        analyzer=analyzer
    )

    logger.info("✅ All 5 options bots initialized")
    logger.info("   - Golden Sweeps ($1M+)")
    logger.info("   - Sweeps ($50K+)")
    logger.info("   - Bullseye (ATM)")
    logger.info("   - Scalps (0-7 DTE)")
    logger.info("   - ORAKL Flow (General)")
    logger.info("🔌 Connecting to Kafka topic: processed-flows")
    logger.info("⏳ Waiting for pre-aggregated flow messages...")
    logger.info("=" * 80)

    # Run all bots concurrently
    try:
        await asyncio.gather(
            golden_sweeps_bot.run(),
            sweeps_bot.run(),
            bullseye_bot.run(),
            scalps_bot.run(),
            orakl_flow_bot.run()
        )
    except KeyboardInterrupt:
        logger.info("\n🛑 Shutting down Kafka consumers...")
    except Exception as e:
        logger.error(f"❌ Fatal error: {e}")
        raise


if __name__ == "__main__":
    # Run the asyncio event loop
    asyncio.run(main())
