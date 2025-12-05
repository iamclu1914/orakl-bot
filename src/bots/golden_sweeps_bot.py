"""Golden Sweeps Bot - 1 Million+ premium sweeps

Independent scanning - each bot scans its own watchlist directly.
Uses base class batching for efficient concurrent API calls.
"""
import asyncio
import logging
from datetime import datetime
from typing import List, Dict, Any, Optional

from .sweeps_bot import SweepsBot
from src.data_fetcher import DataFetcher
from src.options_analyzer import OptionsAnalyzer
from src.config import Config
from src.utils.monitoring import timed
from src.utils.event_bus import event_bus
from src.utils.market_hours import MarketHours

logger = logging.getLogger(__name__)

class GoldenSweepsBot(SweepsBot):
    """
    Golden Sweeps Bot
    Tracks unusually large sweeps with premiums worth over 1 million dollars
    These represent massive conviction trades
    
    ORAKL v3.0: Now includes Brain validation (HedgeHunter + ContextManager)
    """

    def __init__(
        self, 
        webhook_url: str, 
        watchlist: List[str], 
        fetcher: DataFetcher, 
        analyzer: OptionsAnalyzer,
        hedge_hunter: Optional[object] = None,
        context_manager: Optional[object] = None
    ):
        super().__init__(webhook_url, watchlist, fetcher, analyzer, hedge_hunter, context_manager)
        self.name = "Golden Sweeps Bot"
        self.scan_interval = Config.GOLDEN_SWEEPS_INTERVAL
        self.MIN_SWEEP_PREMIUM = max(Config.GOLDEN_MIN_PREMIUM, 1_000_000)
        # Golden prints should alert even with moderate contract counts; ease the score gate.
        self.MIN_SCORE = min(Config.MIN_GOLDEN_SCORE, 70)
        # Golden sweeps can sit further from the money but still matter
        self.MAX_STRIKE_DISTANCE = Config.GOLDEN_MAX_STRIKE_DISTANCE  # percent
        # Full scan mode - scan ALL symbols every cycle (no batching)
        self.scan_batch_size = 0  # 0 = full scan
        self.concurrency_limit = 30  # High concurrency for speed
        logger.info(
            "Golden Sweeps max strike distance set to %.1f%% (env override ready)",
            self.MAX_STRIKE_DISTANCE,
        )
        # Disable volume ratio check for Golden Sweeps - $1M+ premium IS the conviction signal
        self.SKIP_VOLUME_RATIO_CHECK = True
        # Disable alignment check for Golden Sweeps - we want to catch moves BEFORE price confirms
        self.SKIP_ALIGNMENT_CHECK = True
        # Golden prints often carry smaller absolute contract counts; allow smaller day volume
        self.MIN_VOLUME = max(self.MIN_VOLUME // 2, 50)
        # Allow smaller contract bursts to qualify as golden sweeps
        self.MIN_VOLUME_DELTA = max(self.MIN_VOLUME_DELTA // 2, 20)

    @timed()
    async def scan_and_post(self):
        """
        Full scan - scans ALL watchlist symbols every cycle for $1M+ premium flows.
        """
        logger.info(f"{self.name} starting full scan of {len(self.watchlist)} symbols")

        # Only scan during market hours (9:30 AM - 4:00 PM EST, Monday-Friday)
        if not MarketHours.is_market_open(include_extended=False):
            logger.debug(f"{self.name} - Market closed, skipping scan")
            return
        
        # Full scan - all symbols at once with concurrency control
        all_sweeps = []
        max_alerts = 5  # Limit alerts per cycle to avoid Discord rate limits
        
        semaphore = asyncio.Semaphore(self.concurrency_limit)
        
        async def scan_symbol_with_limit(symbol: str) -> List[Dict]:
            async with semaphore:
                try:
                    sweeps = await self._scan_sweeps(symbol)
                    # Filter to golden only ($1M+)
                    return [s for s in sweeps if s.get('premium', 0) >= self.MIN_SWEEP_PREMIUM]
                except Exception as e:
                    logger.debug(f"{self.name} error scanning {symbol}: {e}")
                    return []
        
        tasks = [scan_symbol_with_limit(symbol) for symbol in self.watchlist]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for result in results:
            if isinstance(result, list):
                all_sweeps.extend(result)
        
        logger.info(f"{self.name} found {len(all_sweeps)} golden sweep candidates")
        
        # Enhance scores for golden sweeps
        for sweep in all_sweeps:
            premium = sweep.get('premium', 0)
            # Reward outsized premium
            score_boost = 5
            if premium >= 5_000_000:
                score_boost = 20
            elif premium >= 3_000_000:
                score_boost = 15
            elif premium >= 2_000_000:
                score_boost = 10
            
            current_score = sweep.get('enhanced_score', sweep.get('sweep_score', 50))
            sweep['enhanced_score'] = min(current_score + score_boost, 100)
            
            # Premium-based score floor
            if premium >= 5_000_000:
                sweep['enhanced_score'] = max(sweep['enhanced_score'], 75)
            elif premium >= 3_000_000:
                sweep['enhanced_score'] = max(sweep['enhanced_score'], 70)
            elif premium >= 1_000_000:
                sweep['enhanced_score'] = max(sweep['enhanced_score'], 65)
        
        # Sort by premium (highest first) and post
        all_sweeps.sort(key=lambda x: x['premium'], reverse=True)
        
        posted = 0
        for sweep in all_sweeps[:max_alerts]:
            try:
                success = await self._post_signal(sweep)
                if success:
                    posted += 1
                    # Add delay between posts to avoid Discord rate limits
                    if posted < max_alerts:
                        await asyncio.sleep(1.5)
            except Exception as e:
                logger.error(f"{self.name} error posting signal: {e}")
        
        logger.info(f"{self.name} scan complete - posted {posted} golden sweep alerts")

    async def _post_signal(self, sweep: Dict) -> bool:
        """Post enhanced golden sweep signal to Discord"""
        color = 0x00FF00 if sweep['type'] == 'CALL' else 0xFF0000

        # Format time
        now = datetime.now()
        time_str = now.strftime('%I:%M %p')
        date_str = now.strftime('%m/%d/%y')

        # Format expiration
        exp_str = sweep['expiration']

        # Format premium in millions
        premium_millions = sweep['premium'] / 1000000

        # Get enhanced score
        final_score = sweep.get('enhanced_score', sweep.get('final_score', sweep.get('sweep_score', 0)))

        # Build contract string even when ticker is missing
        contract_symbol = (
            sweep.get('contract')
            or sweep.get('option_symbol')
            or sweep.get('contract_symbol')
            or f"{sweep['symbol']} {sweep['strike']:.0f} {sweep['type']} {sweep['expiration']}"
        )

        sector = sweep.get('sector')

        size_display = ""
        volume_value = sweep.get('volume')
        if isinstance(volume_value, (int, float)) and volume_value > 0:
            size_display = f"{int(volume_value):,}"

        avg_price_display = ""
        avg_price = sweep.get('avg_price')
        if isinstance(avg_price, (int, float)) and avg_price > 0:
            avg_price_display = f"${avg_price:.2f}"

        details_raw = sweep.get('details')
        if (not size_display or not avg_price_display) and isinstance(details_raw, str) and '@' in details_raw:
            size_part, price_part = details_raw.split('@', 1)
            if not size_display:
                size_display = size_part.strip()
            if not avg_price_display:
                price_part = price_part.strip()
                avg_price_display = price_part if price_part else avg_price_display

        if not size_display:
            size_display = "Unavailable"
        if not avg_price_display:
            avg_price_display = "Unavailable"

        fields = [
            {"name": "Date", "value": date_str, "inline": True},
            {"name": "Time", "value": time_str, "inline": True},
            {"name": "Ticker", "value": sweep['symbol'], "inline": True},
            {"name": "Contract", "value": contract_symbol, "inline": False},
            {"name": "Premium", "value": f"${sweep['premium']:,.2f}", "inline": True},
            {"name": "Size", "value": size_display, "inline": True},
            {"name": "Avg Price", "value": avg_price_display, "inline": True},
            {"name": "Exp", "value": exp_str, "inline": True},
            {"name": "Strike", "value": f"${sweep['strike']:.2f}", "inline": True},
            {"name": "C/P", "value": sweep['type'] + "S", "inline": True},
            {"name": "Spot", "value": f"${sweep['current_price']:.2f}", "inline": True},
            {"name": "Type", "value": "SWEEP", "inline": True},
            {"name": "Prem (M)", "value": f"${premium_millions:.1f}M", "inline": True},
            {"name": "Algo Score", "value": str(int(final_score)), "inline": True}
        ]

        if sector:
            fields.append({"name": "Sector", "value": sector, "inline": True})

        if isinstance(details_raw, str) and details_raw.strip():
            fields.append({"name": "Details", "value": details_raw.strip(), "inline": True})

        embed = self.create_signal_embed_with_disclaimer(
            title=f"🏆 {sweep['ticker']} - Golden Sweep Detected",
            description="",
            color=color,
            fields=fields,
            footer="ORAKL Bot - Golden Sweeps"
        )

        # Persist final score info on sweep for downstream consumers
        sweep['final_score'] = final_score
        sweep['score_passed'] = final_score >= Config.MIN_GOLDEN_SCORE

        success = await self.post_to_discord(embed)
        if success:
            logger.info(
                "🚨 GOLDEN SWEEP: %s %s $%s Premium:$%0.1fM Score:%d",
                sweep['ticker'],
                sweep['type'],
                sweep['strike'],
                premium_millions,
                int(final_score),
            )
            await self._publish_golden_sweep_event(sweep)

        return success

    async def _publish_golden_sweep_event(self, sweep: Dict[str, Any]) -> None:
        """Publish a golden sweep event for downstream trigger bots."""
        try:
            await event_bus.publish(
                "golden_sweep_detected",
                symbol=sweep.get("symbol"),
                option_type=sweep.get("type"),
                strike=sweep.get("strike"),
                expiration=sweep.get("expiration"),
                premium=sweep.get("premium"),
                direction=sweep.get("type"),
                timestamp=datetime.utcnow().isoformat(),
                sweep=sweep,
                final_score=sweep.get("final_score"),
                score_passed=sweep.get("score_passed", True),
            )
        except Exception as exc:
            logger.exception("failed to publish golden sweep event: %s", exc)
