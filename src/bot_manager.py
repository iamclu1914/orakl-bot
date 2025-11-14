"""Bot Manager - Orchestrates all auto-posting bots"""
import asyncio
import logging
from typing import List, Dict
from src.data_fetcher import DataFetcher
from src.options_analyzer import OptionsAnalyzer
from src.config import Config
from src.watchlist_manager import SmartWatchlistManager
from src.bots import BullseyeBot, SweepsBot, GoldenSweepsBot, IndexWhaleBot, SpreadBot

logger = logging.getLogger(__name__)

class BotManager:
    """Manages all auto-posting bots with dynamic watchlist"""

    def __init__(self, webhook_url: str, fetcher: DataFetcher, analyzer: OptionsAnalyzer):
        """
        Initialize Bot Manager

        Args:
            webhook_url: Discord webhook URL
            fetcher: Data fetcher instance
            analyzer: Options analyzer instance
        """
        self.webhook_url = webhook_url
        self.fetcher = fetcher
        self.analyzer = analyzer
        self.bots = []
        self.running = False

        # Initialize watchlist manager
        self.watchlist_manager = SmartWatchlistManager(fetcher)
        self.watchlist = []  # Will be populated dynamically

        # Initialize all bots
        self._initialize_bots()

    def _initialize_bots(self):
        """Initialize all auto-posting bots with dedicated webhooks"""
        logger.info("Initializing auto-posting bots with dedicated channels...")
        self.bot_overrides: Dict[object, List[str]] = {}

        # UNIFIED WATCHLIST - All bots now use the same comprehensive watchlist
        # Includes mega-caps + small account friendly tickers (under $75)
        unified_watchlist = list(Config.SWEEPS_WATCHLIST)

        # Bullseye Bot (Institutional Swing Scanner)
        bullseye_watchlist = list(unified_watchlist)
        self.bullseye_bot = BullseyeBot(
            Config.BULLSEYE_WEBHOOK,
            bullseye_watchlist,
            self.fetcher,
        )
        self.bots.append(self.bullseye_bot)
        self.bot_overrides[self.bullseye_bot] = bullseye_watchlist
        logger.info(
            f"  ✓ Bullseye Bot (Institutional) → Channel ID: {Config.BULLSEYE_WEBHOOK.split('/')[-2]}"
            f" | Watchlist: {len(bullseye_watchlist)} tickers"
        )

        # Sweeps Bot (Large Options Sweeps)
        sweeps_watchlist = list(unified_watchlist)
        self.sweeps_bot = SweepsBot(
            Config.SWEEPS_WEBHOOK,
            sweeps_watchlist,
            self.fetcher,
            self.analyzer
        )
        self.bots.append(self.sweeps_bot)
        self.bot_overrides[self.sweeps_bot] = sweeps_watchlist
        logger.info(
            f"  ✓ Sweeps Bot → Channel ID: {Config.SWEEPS_WEBHOOK.split('/')[-2]}"
            f" | Watchlist: {len(sweeps_watchlist)} tickers"
        )

        # Golden Sweeps Bot (1M+ Sweeps)
        golden_watchlist = list(unified_watchlist)
        self.golden_sweeps_bot = GoldenSweepsBot(
            Config.GOLDEN_SWEEPS_WEBHOOK,
            golden_watchlist,
            self.fetcher,
            self.analyzer
        )
        self.bots.append(self.golden_sweeps_bot)
        self.bot_overrides[self.golden_sweeps_bot] = golden_watchlist
        logger.info(
            f"  ✓ Golden Sweeps Bot → Channel ID: {Config.GOLDEN_SWEEPS_WEBHOOK.split('/')[-2]}"
            f" | Watchlist: {len(golden_watchlist)} tickers (same as all bots)"
        )

        # Index Whale Bot (REST polling)
        self.index_whale_bot = IndexWhaleBot(
            Config.INDEX_WHALE_WEBHOOK,
            self.fetcher,
            Config.INDEX_WHALE_WATCHLIST,
        )
        self.bots.append(self.index_whale_bot)
        self.bot_overrides[self.index_whale_bot] = list(Config.INDEX_WHALE_WATCHLIST)
        logger.info(
            "  ✓ Index Whale Bot → REST polling | Symbols: %s",
            ", ".join(Config.INDEX_WHALE_WATCHLIST),
        )

        # 99 Cent Store Bot (Spread scanner)
        spread_watchlist = list(
            dict.fromkeys(
                Config.SWEEPS_WATCHLIST
                + Config.SPREAD_WATCHLIST
                + Config.SPREAD_EXTRA_TICKERS
            )
        )
        self.spread_bot = SpreadBot(
            Config.SPREAD_WEBHOOK,
            spread_watchlist,
            self.fetcher,
        )
        self.bots.append(self.spread_bot)
        self.bot_overrides[self.spread_bot] = spread_watchlist
        logger.info(
            "  ✓ 99 Cent Store Bot → Narrow spread scanner | Watchlist: %d tickers",
            len(spread_watchlist),
        )

        logger.info(f"Initialized {len(self.bots)} auto-posting bots with dedicated webhooks")

    async def start_all(self):
        """Start all bots with dynamic watchlist"""
        if self.running:
            logger.warning("Bot manager already running")
            return

        self.running = True
        logger.info(f"Starting {len(self.bots)} auto-posting bots...")

        # Load watchlist based on WATCHLIST_MODE setting
        if Config.WATCHLIST_MODE == 'STATIC':
            logger.info("🔄 Loading STATIC watchlist from configuration...")
            self.watchlist = list(Config.STATIC_WATCHLIST)
            logger.info(f"✅ Watchlist loaded: {len(self.watchlist)} tickers (static configuration)")
        else:
            logger.info("🔄 Loading dynamic watchlist from Polygon...")
            self.watchlist = await self.watchlist_manager.get_watchlist()
            logger.info(f"✅ Watchlist loaded: {len(self.watchlist)} tickers (dynamic market universe)")
        
        # Update all bots with the comprehensive watchlist
        self._update_bot_watchlists()

        # Start watchlist refresh task
        watchlist_refresh_task = asyncio.create_task(self._watchlist_refresh_loop())

        # Start all bots with staggered timing to reduce resource spike
        tasks = [watchlist_refresh_task]
        
        # Start bots with 5-second delays to prevent resource overload
        for i, bot in enumerate(self.bots):
            # Add delay between bot starts (except for first bot)
            if i > 0:
                await asyncio.sleep(5)
                logger.info(f"Starting {bot.name} (bot {i+1}/{len(self.bots)})...")
            
            task = asyncio.create_task(bot.start())
            tasks.append(task)

        logger.info("All bots started successfully")

        # Wait for all bots (they run indefinitely)
        try:
            await asyncio.gather(*tasks)
        except Exception as e:
            logger.error(f"Bot manager error: {e}")
            await self.stop_all()

    async def _watchlist_refresh_loop(self):
        """Background task to refresh watchlist periodically"""
        while self.running:
            try:
                # Wait for refresh interval
                await asyncio.sleep(Config.WATCHLIST_REFRESH_INTERVAL)

                if Config.WATCHLIST_MODE == 'STATIC':
                    logger.info("🔄 Using static watchlist configuration (no refresh needed)...")
                    logger.info(f"✅ All bots using: {len(self.watchlist)} configured tickers")
                    continue

                await self.watchlist_manager.refresh_watchlist()
                self.watchlist = await self.watchlist_manager.get_watchlist()
                logger.info(f"✅ Dynamic watchlist refreshed: {len(self.watchlist)} tickers")
                self._update_bot_watchlists()

            except Exception as e:
                logger.error(f"Error in watchlist refresh loop: {e}")
                await asyncio.sleep(60)  # Wait 1 minute before retry

    def _update_bot_watchlists(self):
        """Update watchlist for all bots with comprehensive sector list"""
        for bot in self.bots:
            if not hasattr(bot, 'watchlist'):
                continue

            override = None
            if hasattr(self, 'bot_overrides'):
                override = self.bot_overrides.get(bot)

            if override is not None:
                bot.watchlist = list(override)
                logger.info(f"  {bot.name}: {len(bot.watchlist)} tickers (custom watchlist)")
            else:
                bot.watchlist = self.watchlist
                logger.info(f"  {bot.name}: {len(self.watchlist)} tickers (full mega/large cap list)")

    async def stop_all(self):
        """Stop all bots"""
        if not self.running:
            return

        logger.info("Stopping all bots...")
        self.running = False

        # Stop all bots
        for bot in self.bots:
            await bot.stop()

        logger.info("All bots stopped")

    def get_bot_status(self) -> dict:
        """Get status of all bots"""
        status = {
            'running': self.running,
            'total_bots': len(self.bots),
            'bots': []
        }

        for bot in self.bots:
            status['bots'].append({
                'name': bot.name,
                'running': bot.running,
                'scan_interval': bot.scan_interval
            })

        return status
