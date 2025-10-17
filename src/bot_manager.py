"""Bot Manager - Orchestrates all auto-posting bots"""
import asyncio
import logging
from typing import List
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
    DarkpoolBot,
    BreakoutsBot,
    UnusualVolumeBot
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

        # Orakl Flow Bot (formerly Trady Flow)
        self.orakl_flow_bot = TradyFlowBot(
            Config.ORAKL_FLOW_WEBHOOK,
            self.watchlist,
            self.fetcher,
            self.analyzer
        )
        self.bots.append(self.orakl_flow_bot)
        logger.info(f"  ✓ Orakl Flow Bot → Channel ID: {Config.ORAKL_FLOW_WEBHOOK.split('/')[-2]}")

        # Bullseye Bot (AI Intraday)
        self.bullseye_bot = BullseyeBot(
            Config.BULLSEYE_WEBHOOK,
            self.watchlist,
            self.fetcher,
            self.analyzer
        )
        self.bots.append(self.bullseye_bot)
        logger.info(f"  ✓ Bullseye Bot → Channel ID: {Config.BULLSEYE_WEBHOOK.split('/')[-2]}")

        # Scalps Bot (The Strat)
        self.scalps_bot = ScalpsBot(
            Config.SCALPS_WEBHOOK,
            self.watchlist,
            self.fetcher,
            self.analyzer
        )
        self.bots.append(self.scalps_bot)
        logger.info(f"  ✓ Scalps Bot → Channel ID: {Config.SCALPS_WEBHOOK.split('/')[-2]}")

        # Sweeps Bot (Large Options Sweeps)
        self.sweeps_bot = SweepsBot(
            Config.SWEEPS_WEBHOOK,
            self.watchlist,
            self.fetcher,
            self.analyzer
        )
        self.bots.append(self.sweeps_bot)
        logger.info(f"  ✓ Sweeps Bot → Channel ID: {Config.SWEEPS_WEBHOOK.split('/')[-2]}")

        # Golden Sweeps Bot (1M+ Sweeps)
        self.golden_sweeps_bot = GoldenSweepsBot(
            Config.GOLDEN_SWEEPS_WEBHOOK,
            self.watchlist,
            self.fetcher,
            self.analyzer
        )
        self.bots.append(self.golden_sweeps_bot)
        logger.info(f"  ✓ Golden Sweeps Bot → Channel ID: {Config.GOLDEN_SWEEPS_WEBHOOK.split('/')[-2]}")

        # Darkpool Bot (Large Darkpool/Blocks)
        self.darkpool_bot = DarkpoolBot(
            Config.DARKPOOL_WEBHOOK,
            self.watchlist,
            self.fetcher,
            self.analyzer
        )
        self.bots.append(self.darkpool_bot)
        logger.info(f"  ✓ Darkpool Bot → Channel ID: {Config.DARKPOOL_WEBHOOK.split('/')[-2]}")

        # Breakouts Bot (Stock Breakouts)
        self.breakouts_bot = BreakoutsBot(
            Config.BREAKOUTS_WEBHOOK,
            self.watchlist,
            self.fetcher,
            self.analyzer
        )
        self.bots.append(self.breakouts_bot)
        logger.info(f"  ✓ Breakouts Bot → Channel ID: {Config.BREAKOUTS_WEBHOOK.split('/')[-2]}")

        # Unusual Activity Bot (Volume Surge Detection)
        self.unusual_activity_bot = UnusualVolumeBot(
            Config.UNUSUAL_ACTIVITY_WEBHOOK,
            self.watchlist,
            self.fetcher,
            self.analyzer
        )
        self.bots.append(self.unusual_activity_bot)
        logger.info(f"  ✓ Unusual Activity Bot → Channel ID: {Config.UNUSUAL_ACTIVITY_WEBHOOK.split('/')[-2]}")

        # STRAT Pattern Bot (3-2-2, 2-2, 1-3-1 Patterns)
        self.strat_bot = STRATPatternBot(self.fetcher)
        self.bots.append(self.strat_bot)
        logger.info(f"  ✓ STRAT Pattern Bot → Channel ID: {Config.STRAT_WEBHOOK.split('/')[-2]}")

        logger.info(f"Initialized {len(self.bots)} auto-posting bots with dedicated webhooks")

    async def start_all(self):
        """Start all bots with dynamic watchlist"""
        if self.running:
            logger.warning("Bot manager already running")
            return

        self.running = True
        logger.info(f"Starting {len(self.bots)} auto-posting bots...")

        # Use watchlist based on config mode
        if Config.WATCHLIST_MODE == 'FOCUSED':
            logger.info("🔄 Loading focused high-performance watchlist...")
            # Use a small focused list for reliable performance
            self.watchlist = [
                "SPY", "QQQ", "IWM", "DIA",
                "AAPL", "MSFT", "NVDA", "GOOGL", "META", "AMZN",
                "TSLA", "AMD", "NFLX", "PLTR", "SOFI", "NIO",
                "JPM", "BAC", "WFC", "C",
                "GME", "AMC", "BBBY", "BB"
            ]
            logger.info(f"✅ Watchlist loaded: {len(self.watchlist)} tickers (focused high-volume list)")
        elif Config.WATCHLIST_MODE == 'STATIC':
            logger.info("🔄 Loading static watchlist from config...")
            self.watchlist = Config.STATIC_WATCHLIST
            logger.info(f"✅ Watchlist loaded: {len(self.watchlist)} tickers (static list)")
        else:
            logger.info("🔄 Loading comprehensive sector watchlist...")
            self.watchlist = STRAT_COMPLETE_WATCHLIST
            logger.info(f"✅ Watchlist loaded: {len(self.watchlist)} tickers (all mega/large caps)")
        
        # Update all bots with the comprehensive watchlist
        self._update_bot_watchlists()

        # Start watchlist refresh task
        watchlist_refresh_task = asyncio.create_task(self._watchlist_refresh_loop())

        # Start all bots concurrently
        tasks = [watchlist_refresh_task]
        for bot in self.bots:
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
            if hasattr(bot, 'watchlist'):
                # All bots now use the same comprehensive watchlist
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
