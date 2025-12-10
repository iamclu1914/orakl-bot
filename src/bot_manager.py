"""Bot Manager - Orchestrates all auto-posting bots

ORAKL v2.0 Event-Driven Architecture:
- League A (flow_bots): Real-time Kafka consumers for trade events
- League B (state_bots): Scheduled REST pollers for market state

When KAFKA_ENABLED=true:
  - Flow bots receive events via process_single_event()
  - State bots run on scheduled polling intervals
  
When KAFKA_ENABLED=false (fallback):
  - All bots run on scheduled REST polling
"""
import asyncio
import logging
from typing import List, Dict, Optional, Any
from src.data_fetcher import DataFetcher
from src.options_analyzer import OptionsAnalyzer
from src.config import Config
from src.watchlist_manager import SmartWatchlistManager
from src.bots import BullseyeBot, SweepsBot, GoldenSweepsBot, SpreadBot, GammaRatioBot, RollingThunderBot, WallsBot, LottoBot

logger = logging.getLogger(__name__)


# Bot categorization for event-driven architecture
FLOW_BOT_NAMES = {
    'Sweeps Bot',
    'Golden Sweeps Bot',
    'Bullseye Bot',
    'Lotto Bot',
    'Rolling Thunder Bot',
    # Note: 99 Cent Store removed - now a stream filter (no watchlist)
}

# Stream Filter Bots: Process EVERY Kafka event (no watchlist restriction)
# These bots are called directly from main.py for every trade
STREAM_FILTER_BOTS = {
    '99 Cent Store',  # Sub-$1 swing trades on any ticker
}

STATE_BOT_NAMES = {
    'Gamma Ratio Bot',
    'Walls Bot',
}


class BotManager:
    """
    Manages all auto-posting bots with hybrid Kafka/REST architecture.
    
    Bot Leagues:
    - League A (Flow Bots): React to individual trade events in real-time
      - Sweeps, Golden Sweeps, Bullseye, Lotto, Rolling Thunder, 99 Cent Store
    - League B (State Bots): Analyze aggregate market state on schedule
      - Gamma Ratio, Walls
    
    Modes:
    - Kafka Mode: Flow bots via process_single_event(), State bots scheduled
    - REST Mode: All bots on scheduled polling (fallback)
    """

    def __init__(
        self, 
        webhook_url: str, 
        fetcher: DataFetcher, 
        analyzer: OptionsAnalyzer,
        hedge_hunter: Optional[object] = None,
        context_manager: Optional[object] = None
    ):
        """
        Initialize Bot Manager

        Args:
            webhook_url: Discord webhook URL
            fetcher: Data fetcher instance
            analyzer: Options analyzer instance
            hedge_hunter: Optional HedgeHunter instance for synthetic trade detection
            context_manager: Optional ContextManager instance for GEX regime tracking
        """
        self.webhook_url = webhook_url
        self.fetcher = fetcher
        self.analyzer = analyzer
        self.hedge_hunter = hedge_hunter
        self.context_manager = context_manager
        self.bots = []
        self.running = False
        
        # Segregated bot lists for event-driven architecture
        self.flow_bots: List[Any] = []  # League A: Kafka event consumers (watchlist-based)
        self.state_bots: List[Any] = []  # League B: Scheduled pollers
        self.stream_filter_bots: List[Any] = []  # Stream filters: process ALL events
        
        # Event processing stats
        self.events_processed = 0
        self.events_dispatched = 0
        self.events_alerted = 0

        # Initialize watchlist manager
        self.watchlist_manager = SmartWatchlistManager(fetcher)
        self.watchlist = []  # Will be populated dynamically

        # Initialize all bots
        self._initialize_bots()

    def _initialize_bots(self):
        """Initialize all auto-posting bots with dedicated webhooks"""
        logger.info("Initializing auto-posting bots with dedicated channels...")
        self.bot_overrides: Dict[object, List[str]] = {}
        brain_status = "🧠" if (self.hedge_hunter or self.context_manager) else ""

        # =======================================================================
        # Bot-Specific Watchlists (Tier 1 + selective Tier 2 expansions)
        # =======================================================================

        # Bullseye Bot: Tier 1 + institutionals (23 tickers)
        bullseye_watchlist = list(Config.BULLSEYE_WATCHLIST)
        self.bullseye_bot = BullseyeBot(
            Config.BULLSEYE_WEBHOOK,
            bullseye_watchlist,
            self.fetcher,
            hedge_hunter=self.hedge_hunter,
            context_manager=self.context_manager,
        )
        self.bots.append(self.bullseye_bot)
        self.bot_overrides[self.bullseye_bot] = bullseye_watchlist
        logger.info(
            f"  ✓ Bullseye Bot (Institutional) {brain_status} | Watchlist: {len(bullseye_watchlist)} tickers"
        )

        # Sweeps Bot: Tier 1 + growth/beta (26 tickers)
        sweeps_watchlist = list(Config.SWEEPS_WATCHLIST)
        self.sweeps_bot = SweepsBot(
            Config.SWEEPS_WEBHOOK,
            sweeps_watchlist,
            self.fetcher,
            self.analyzer,
            hedge_hunter=self.hedge_hunter,
            context_manager=self.context_manager,
        )
        self.bots.append(self.sweeps_bot)
        self.bot_overrides[self.sweeps_bot] = sweeps_watchlist
        logger.info(
            f"  ✓ Sweeps Bot {brain_status} | Watchlist: {len(sweeps_watchlist)} tickers"
        )

        # Golden Sweeps Bot: Tier 1 + whale magnets (24 tickers)
        golden_watchlist = list(Config.GOLDEN_SWEEPS_WATCHLIST)
        self.golden_sweeps_bot = GoldenSweepsBot(
            Config.GOLDEN_SWEEPS_WEBHOOK,
            golden_watchlist,
            self.fetcher,
            self.analyzer,
            hedge_hunter=self.hedge_hunter,
            context_manager=self.context_manager,
        )
        self.bots.append(self.golden_sweeps_bot)
        self.bot_overrides[self.golden_sweeps_bot] = golden_watchlist
        logger.info(
            f"  ✓ Golden Sweeps Bot {brain_status} | Watchlist: {len(golden_watchlist)} tickers"
        )

        # 99 Cent Store Bot: STREAM FILTER (no watchlist restriction)
        # Processes EVERY Kafka event and applies its own filters:
        # - Price < $1.00, Premium >= $250K, DTE 5-21, Vol/OI >= 2.0
        spread_watchlist = list(Config.SPREAD_WATCHLIST)  # For REST fallback only
        self.spread_bot = SpreadBot(
            Config.SPREAD_WEBHOOK,
            spread_watchlist,
            self.fetcher,
        )
        self.bots.append(self.spread_bot)
        self.bot_overrides[self.spread_bot] = spread_watchlist
        logger.info(
            f"  ✓ 99 Cent Store Bot → STREAM FILTER (any ticker) | REST fallback: {len(spread_watchlist)} tickers"
        )

        # Gamma Ratio Bot: Focused liquid set (5 tickers)
        gamma_watchlist = list(Config.GAMMA_RATIO_WATCHLIST)
        self.gamma_ratio_bot = GammaRatioBot(
            Config.GAMMA_RATIO_WEBHOOK,
            gamma_watchlist,
            self.fetcher,
        )
        self.bots.append(self.gamma_ratio_bot)
        self.bot_overrides[self.gamma_ratio_bot] = gamma_watchlist
        logger.info(
            f"  ✓ Gamma Ratio Bot → G ratio regime tracker | Watchlist: {len(gamma_watchlist)} tickers"
        )

        # Rolling Thunder Bot: Tier 1 + roll-prone (23 tickers)
        rolling_watchlist = list(Config.ROLLING_WATCHLIST)
        self.rolling_thunder_bot = RollingThunderBot(
            Config.ROLLING_THUNDER_WEBHOOK,
            rolling_watchlist,
            self.fetcher,
            hedge_hunter=self.hedge_hunter,
            context_manager=self.context_manager,
        )
        self.bots.append(self.rolling_thunder_bot)
        self.bot_overrides[self.rolling_thunder_bot] = rolling_watchlist
        logger.info(
            f"  ✓ Rolling Thunder Bot 🔄 → Whale roll detector | Watchlist: {len(rolling_watchlist)} tickers"
        )

        # Walls Bot: GEX Universe (10 tickers)
        walls_watchlist = list(Config.GEX_UNIVERSE)
        self.walls_bot = WallsBot(
            Config.WALLS_BOT_WEBHOOK,
            walls_watchlist,
            self.fetcher,
            hedge_hunter=self.hedge_hunter,
            context_manager=self.context_manager,
        )
        self.bots.append(self.walls_bot)
        self.bot_overrides[self.walls_bot] = walls_watchlist
        logger.info(
            f"  ✓ Walls Bot 🧱 → Support/Resistance detector | Watchlist: {len(walls_watchlist)} tickers"
        )

        # Lotto Bot: Tier 1 + story/beta (25 tickers)
        lotto_watchlist = list(Config.LOTTO_WATCHLIST)
        self.lotto_bot = LottoBot(
            Config.LOTTO_BOT_WEBHOOK,
            lotto_watchlist,
            self.fetcher,
            hedge_hunter=self.hedge_hunter,
            context_manager=self.context_manager,
        )
        self.bots.append(self.lotto_bot)
        self.bot_overrides[self.lotto_bot] = lotto_watchlist
        logger.info(
            f"  ✓ Lotto Bot 🎰 → Unusual OTM flow hunter | Watchlist: {len(lotto_watchlist)} tickers"
        )

        logger.info(f"Initialized {len(self.bots)} auto-posting bots with dedicated webhooks")
        
        # Categorize bots into Flow (League A) and State (League B)
        self._categorize_bots()

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
            'flow_bots': len(self.flow_bots),
            'stream_filter_bots': len(self.stream_filter_bots),
            'state_bots': len(self.state_bots),
            'events_processed': self.events_processed,
            'events_alerted': self.events_alerted,
            'bots': []
        }

        for bot in self.bots:
            if bot in self.stream_filter_bots:
                league = 'Stream Filter'
            elif bot in self.flow_bots:
                league = 'A (Flow)'
            else:
                league = 'B (State)'
            status['bots'].append({
                'name': bot.name,
                'running': bot.running,
                'scan_interval': bot.scan_interval,
                'league': league
            })

        return status

    # =========================================================================
    # Bot Categorization for Event-Driven Architecture
    # =========================================================================
    
    def _categorize_bots(self):
        """
        Categorize bots into League A (Flow) and League B (State).
        
        League A (Flow Bots): Process individual trade events from Kafka
        - Need to react to specific trade characteristics
        - Have process_event() method
        
        League B (State Bots): Analyze aggregate market state
        - Calculate metrics across many contracts/strikes
        - Run on scheduled intervals regardless of mode
        """
        self.flow_bots = []
        self.state_bots = []
        self.stream_filter_bots = []
        
        for bot in self.bots:
            if bot.name in STREAM_FILTER_BOTS:
                self.stream_filter_bots.append(bot)
            elif bot.name in FLOW_BOT_NAMES:
                self.flow_bots.append(bot)
            elif bot.name in STATE_BOT_NAMES:
                self.state_bots.append(bot)
            else:
                # Default to flow bot if not explicitly categorized
                logger.warning(f"Bot '{bot.name}' not categorized, defaulting to Flow")
                self.flow_bots.append(bot)
        
        logger.info(f"Bot categorization complete:")
        logger.info(f"  League A (Flow): {len(self.flow_bots)} bots - {[b.name for b in self.flow_bots]}")
        logger.info(f"  Stream Filters: {len(self.stream_filter_bots)} bots - {[b.name for b in self.stream_filter_bots]}")
        logger.info(f"  League B (State): {len(self.state_bots)} bots - {[b.name for b in self.state_bots]}")

    # =========================================================================
    # Kafka Mode: Event-Driven Methods
    # =========================================================================
    
    async def process_single_event(self, enriched_trade: Dict) -> List[Dict]:
        """
        Process a single enriched trade event from Kafka.
        
        Dispatches the event to all League A (Flow) bots that have a
        process_event() method. Each bot applies its own filters and
        may or may not generate an alert.
        
        Args:
            enriched_trade: Trade data enriched with Greeks, OI, etc.
            
        Returns:
            List of alert payloads generated by bots
        """
        self.events_processed += 1
        alerts = []
        
        symbol = enriched_trade.get('symbol', 'UNKNOWN')
        premium = enriched_trade.get('premium', 0)
        
        logger.debug(
            f"Processing event: {symbol} premium=${premium:,.0f} "
            f"dispatching to {len(self.flow_bots)} flow bots"
        )
        
        # TEMPORARY: Info log to confirm dispatch is working
        # This will show up in your logs even if no alert is generated
        # if premium > 50000:
        #     logger.info(f"🔎 Dispatching {symbol} trade (${premium:,.0f}) to {len(self.flow_bots)} bots...")
        
        # Dispatch to all flow bots
        for bot in self.flow_bots:
            if not bot.running:
                continue
            
            # Check if bot has process_event method
            if not hasattr(bot, 'process_event'):
                logger.debug(f"{bot.name} has no process_event method, skipping")
                continue
            
            try:
                self.events_dispatched += 1
                result = await bot.process_event(enriched_trade)
                
                if result:
                    alerts.append(result)
                    self.events_alerted += 1
                    logger.info(f"Alert generated by {bot.name} for {symbol}")
                    
            except Exception as e:
                logger.error(f"Error dispatching to {bot.name}: {e}")
        
        return alerts
    
    async def start_state_bots(self):
        """
        Start only League B (State) bots on scheduled polling.
        
        Used in Kafka mode where Flow bots receive events directly
        but State bots still need scheduled updates.
        """
        if not self.state_bots:
            logger.warning("No state bots to start")
            return
        
        logger.info(f"Starting {len(self.state_bots)} state bots (League B)...")
        
        # Load watchlist for state bots
        if Config.WATCHLIST_MODE == 'STATIC':
            self.watchlist = list(Config.STATIC_WATCHLIST)
        else:
            self.watchlist = await self.watchlist_manager.get_watchlist()
        
        self._update_bot_watchlists()
        
        # Start state bots with staggered timing
        tasks = []
        for i, bot in enumerate(self.state_bots):
            if i > 0:
                await asyncio.sleep(3)
            logger.info(f"Starting state bot: {bot.name}")
            task = asyncio.create_task(bot.start())
            tasks.append(task)
        
        # Also start watchlist refresh for state bots
        tasks.append(asyncio.create_task(self._watchlist_refresh_loop()))
        
        logger.info(f"All {len(self.state_bots)} state bots started")
        
        # Wait for tasks
        try:
            await asyncio.gather(*tasks)
        except Exception as e:
            logger.error(f"State bot error: {e}")
    
    async def start_flow_bots_polling(self):
        """
        Start League A (Flow) bots on scheduled REST polling.
        
        Used as fallback when Kafka is unavailable or during REST mode.
        """
        if not self.flow_bots:
            logger.warning("No flow bots to start")
            return
        
        logger.info(f"Starting {len(self.flow_bots)} flow bots in REST polling mode...")
        
        # Load watchlist
        if Config.WATCHLIST_MODE == 'STATIC':
            self.watchlist = list(Config.STATIC_WATCHLIST)
        else:
            self.watchlist = await self.watchlist_manager.get_watchlist()
        
        self._update_bot_watchlists()
        
        # Start flow bots with staggered timing
        tasks = []
        for i, bot in enumerate(self.flow_bots):
            if i > 0:
                await asyncio.sleep(5)
            logger.info(f"Starting flow bot (REST mode): {bot.name}")
            task = asyncio.create_task(bot.start())
            tasks.append(task)
        
        logger.info(f"All {len(self.flow_bots)} flow bots started in REST mode")
        
        # Wait for tasks
        try:
            await asyncio.gather(*tasks)
        except Exception as e:
            logger.error(f"Flow bot (REST) error: {e}")
    
    async def trigger_gamma_update(self, symbol: str):
        """
        Trigger an out-of-cycle Gamma Bot update for a specific symbol.
        
        Called by Flow bots when they detect massive flow that warrants
        an immediate GEX recalculation (the "Bridge" pattern).
        
        Args:
            symbol: Ticker to update (e.g., "NVDA")
        """
        if not self.gamma_ratio_bot:
            return
        
        if not hasattr(self.gamma_ratio_bot, '_scan_symbol'):
            return
        
        try:
            logger.info(f"Triggering out-of-cycle Gamma update for {symbol}")
            await self.gamma_ratio_bot._scan_symbol(symbol)
        except Exception as e:
            logger.error(f"Error in triggered Gamma update for {symbol}: {e}")
    
    def get_flow_bot_names(self) -> List[str]:
        """Get names of all flow bots"""
        return [bot.name for bot in self.flow_bots]
    
    def get_state_bot_names(self) -> List[str]:
        """Get names of all state bots"""
        return [bot.name for bot in self.state_bots]
    
    def get_stream_filter_bots(self) -> List:
        """Get stream filter bots for direct event dispatch (no watchlist)"""
        return self.stream_filter_bots
    
    def get_stream_filter_bot_names(self) -> List[str]:
        """Get names of all stream filter bots"""
        return [bot.name for bot in self.stream_filter_bots]
    
    def get_event_stats(self) -> Dict:
        """Get event processing statistics"""
        return {
            'events_processed': self.events_processed,
            'events_dispatched': self.events_dispatched,
            'events_alerted': self.events_alerted,
            'alert_rate': self.events_alerted / max(1, self.events_processed)
        }
