"""Bot Manager - Orchestrates all auto-posting bots"""
import asyncio
import logging
from typing import List, Dict
from src.data_fetcher import DataFetcher
from src.options_analyzer import OptionsAnalyzer
from src.config import Config
from src.watchlist_manager import SmartWatchlistManager
from src.bots import (
    TradyFlowBot,
    BullseyeBot,
    ScalpsBot,
    SweepsBot,
    GoldenSweepsBot,
    DarkpoolBot
)
from src.bots.strat_bot import STRATPatternBot
from src.utils.sector_watchlist import STRAT_COMPLETE_WATCHLIST

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

        # Orakl Flow Bot (formerly Trady Flow)
        orakl_watchlist = list(Config.ORAKL_FLOW_WATCHLIST)
        self.orakl_flow_bot = TradyFlowBot(
            Config.ORAKL_FLOW_WEBHOOK,
            orakl_watchlist,
            self.fetcher,
            self.analyzer
        )
        self.bots.append(self.orakl_flow_bot)
        self.bot_overrides[self.orakl_flow_bot] = orakl_watchlist
        logger.info(f"  ✓ Orakl Flow Bot → Channel ID: {Config.ORAKL_FLOW_WEBHOOK.split('/')[-2]}")

        # Shared large-cap watchlist used by sweeps/golden/darkpool/bullseye/strat
        shared_large_cap_watchlist = list(Config.SWEEPS_WATCHLIST)

        # Bullseye Bot (AI Intraday)
        bullseye_watchlist = list(shared_large_cap_watchlist)
        self.bullseye_bot = BullseyeBot(
            Config.BULLSEYE_WEBHOOK,
            bullseye_watchlist,
            self.fetcher,
            self.analyzer
        )
        self.bots.append(self.bullseye_bot)
        self.bot_overrides[self.bullseye_bot] = bullseye_watchlist
        logger.info(
            f"  ✓ Bullseye Bot → Channel ID: {Config.BULLSEYE_WEBHOOK.split('/')[-2]}"
            f" | Watchlist: {len(bullseye_watchlist)} tickers"
        )

        # Scalps Bot (The Strat)
        scalps_watchlist = list(Config.SCALPS_WATCHLIST)
        self.scalps_bot = ScalpsBot(
            Config.SCALPS_WEBHOOK,
            scalps_watchlist,
            self.fetcher,
            self.analyzer
        )
        self.bots.append(self.scalps_bot)
        self.bot_overrides[self.scalps_bot] = scalps_watchlist
        logger.info(f"  ✓ Scalps Bot → Channel ID: {Config.SCALPS_WEBHOOK.split('/')[-2]}")

        # Sweeps Bot (Large Options Sweeps)
        sweeps_watchlist = list(shared_large_cap_watchlist)
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
        golden_watchlist = list(shared_large_cap_watchlist)
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
            f" | Watchlist: {len(golden_watchlist)} tickers"
        )

        # Darkpool Bot (Large Darkpool/Blocks)
        darkpool_watchlist = list(Config.DARKPOOL_WATCHLIST or shared_large_cap_watchlist)
        if not darkpool_watchlist:
            darkpool_watchlist = list(shared_large_cap_watchlist)
        self.darkpool_bot = DarkpoolBot(
            Config.DARKPOOL_WEBHOOK,
            darkpool_watchlist,
            self.fetcher,
            self.analyzer
        )
        self.bots.append(self.darkpool_bot)
        self.bot_overrides[self.darkpool_bot] = darkpool_watchlist
        logger.info(
            f"  ✓ Darkpool Bot → Channel ID: {Config.DARKPOOL_WEBHOOK.split('/')[-2]}"
            f" | Watchlist: {len(darkpool_watchlist)} tickers"
        )

        # STRAT Pattern Bot (3-2-2, 2-2, 1-3-1 Patterns)
        self.strat_bot = STRATPatternBot(self.fetcher)
        self.strat_bot.watchlist = list(shared_large_cap_watchlist)
        self.bot_overrides[self.strat_bot] = list(shared_large_cap_watchlist)
        self.bots.append(self.strat_bot)
        logger.info(
            f"  ✓ STRAT Pattern Bot → Channel ID: {Config.STRAT_WEBHOOK.split('/')[-2]}"
            f" | Watchlist: {len(shared_large_cap_watchlist)} tickers"
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
            self.watchlist = Config.STATIC_WATCHLIST
            logger.info(f"✅ Watchlist loaded: {len(self.watchlist)} tickers (static configuration)")
        else:
            logger.info("🔄 Loading ALL_MARKET watchlist (comprehensive sector list)...")
            self.watchlist = STRAT_COMPLETE_WATCHLIST
            logger.info(f"✅ Watchlist loaded: {len(self.watchlist)} tickers (all mega/large caps)")
        
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

                # No need to refresh - using static comprehensive watchlist
                logger.info("🔄 Using static comprehensive watchlist...")
                logger.info(f"✅ All bots using: {len(self.watchlist)} mega/large cap tickers")

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
