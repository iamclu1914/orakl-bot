"""Golden Sweeps Bot - 1 Million+ premium sweeps

Optimized for efficiency using shared FlowCache:
- ONE prefetch per cycle for all symbols (shared with other bots)
- Local filtering on cached data (no per-symbol API calls)
- All 400+ symbols scanned every 5 minutes
"""
import logging
from datetime import datetime
from typing import List, Dict, Any

from .sweeps_bot import SweepsBot
from src.data_fetcher import DataFetcher
from src.options_analyzer import OptionsAnalyzer
from src.config import Config
from src.utils.monitoring import timed
from src.utils.event_bus import event_bus
from src.utils.market_hours import MarketHours
from src.utils.flow_cache import get_flow_cache

logger = logging.getLogger(__name__)

class GoldenSweepsBot(SweepsBot):
    """
    Golden Sweeps Bot
    Tracks unusually large sweeps with premiums worth over 1 million dollars
    These represent massive conviction trades
    """

    def __init__(self, webhook_url: str, watchlist: List[str], fetcher: DataFetcher, analyzer: OptionsAnalyzer):
        super().__init__(webhook_url, watchlist, fetcher, analyzer)
        self.name = "Golden Sweeps Bot"
        self.scan_interval = Config.GOLDEN_SWEEPS_INTERVAL
        self.MIN_SWEEP_PREMIUM = max(Config.GOLDEN_MIN_PREMIUM, 1_000_000)
        # Golden prints should alert even with moderate contract counts; ease the score gate.
        self.MIN_SCORE = min(Config.MIN_GOLDEN_SCORE, 70)
        # Golden sweeps can sit further from the money but still matter
        self.MAX_STRIKE_DISTANCE = Config.GOLDEN_MAX_STRIKE_DISTANCE  # percent
        # NO BATCHING - scan ALL tickers every cycle using shared FlowCache
        self.scan_batch_size = 0
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
        Optimized scanning using shared FlowCache:
        - ONE prefetch for all symbols (shared with other bots)
        - Local filtering for $1M+ premium flows
        - All 400+ symbols processed every 5 minutes
        """
        logger.info(f"{self.name} scanning for million dollar sweeps")

        # Only scan during market hours (9:30 AM - 4:00 PM EST, Monday-Friday)
        if not MarketHours.is_market_open(include_extended=False):
            logger.debug(f"{self.name} - Market closed, skipping scan")
            return
        
        # Get shared flow cache
        cache = get_flow_cache()
        
        # Refresh cache if needed (this is the ONLY API call for all bots)
        await cache.refresh_if_needed(self.fetcher, self.watchlist)
        
        # Filter cached flows for GOLDEN ($1M+) premium (NO API calls!)
        candidates = cache.filter_flows(
            min_premium=self.MIN_SWEEP_PREMIUM,  # $1M+
            min_volume=self.MIN_VOLUME_DELTA,
        )
        
        logger.info(
            "%s found %d golden candidates from cache (%.1fs old)",
            self.name, len(candidates), cache.age_seconds
        )
        
        # Process candidates locally
        sweeps = []
        now = datetime.now()
        
        for flow in candidates:
            try:
                flow_dict = cache.flow_to_dict(flow)
                
                # DTE calculation
                days_to_expiry = 0
                if flow.expiration:
                    try:
                        exp_date = datetime.strptime(flow.expiration, '%Y-%m-%d')
                        days_to_expiry = (exp_date - now).days
                    except ValueError:
                        continue
                
                # Allow 0DTE up to 2-year LEAPS for Golden Sweeps
                if days_to_expiry < 0 or days_to_expiry > 730:
                    continue
                
                # Calculate strike distance (no filter for Golden - premium IS the signal)
                strike_distance = 0
                if flow.underlying_price and flow.underlying_price > 0:
                    strike_distance = ((flow.strike - flow.underlying_price) / flow.underlying_price) * 100
                
                # Calculate moneyness
                if flow.option_type == 'CALL':
                    moneyness = 'ITM' if flow.strike < flow.underlying_price else 'OTM' if flow.strike > flow.underlying_price else 'ATM'
                else:
                    moneyness = 'ITM' if flow.strike > flow.underlying_price else 'OTM' if flow.strike < flow.underlying_price else 'ATM'
                
                # Calculate base sweep score
                num_fills = max(3, int(flow.volume_delta / 50))
                sweep_score = self._calculate_sweep_score(
                    flow.premium, flow.total_volume, num_fills, abs(strike_distance)
                )
                
                # Reward outsized premium
                if flow.premium >= 5_000_000:
                    sweep_score += 20
                elif flow.premium >= 3_000_000:
                    sweep_score += 15
                elif flow.premium >= 2_000_000:
                    sweep_score += 10
                else:
                    sweep_score += 5
                sweep_score = min(sweep_score, 100)
                
                # Premium-based score floor
                premium_score_floor = 0
                if flow.premium >= 5_000_000:
                    premium_score_floor = 75
                elif flow.premium >= 3_000_000:
                    premium_score_floor = 70
                elif flow.premium >= 1_000_000:
                    premium_score_floor = 65
                sweep_score = max(sweep_score, premium_score_floor)
                
                # Deduplication
                signal_key = f"{flow.underlying}_{flow.option_type}_{flow.strike}_{flow.expiration}"
                dedup_result = self.deduplicator.should_alert(signal_key, flow.premium)
                
                if not dedup_result['should_alert']:
                    continue
                
                if self._cooldown_active(signal_key):
                    continue
                
                # Calculate probability ITM
                prob_itm = self.analyzer.calculate_probability_itm(
                    flow.option_type, flow.strike, flow.underlying_price, days_to_expiry
                ) if flow.underlying_price else 0
                
                # Build sweep signal
                sweep = {
                    'ticker': flow.underlying,
                    'symbol': flow.underlying,
                    'type': flow.option_type,
                    'strike': flow.strike,
                    'expiration': flow.expiration,
                    'current_price': flow.underlying_price,
                    'days_to_expiry': days_to_expiry,
                    'premium': flow.premium,
                    'volume': flow.total_volume,
                    'num_fills': num_fills,
                    'moneyness': moneyness,
                    'strike_distance': strike_distance,
                    'probability_itm': prob_itm,
                    'sweep_score': sweep_score,
                    'enhanced_score': sweep_score,
                    'volume_delta': flow.volume_delta,
                    'delta': flow.delta,
                    'gamma': flow.gamma,
                    'vega': flow.vega,
                    'avg_price': flow.premium / (max(flow.volume_delta, 1) * 100),
                    'alert_type': dedup_result['type'],
                    'alert_reason': dedup_result['reason'],
                }
                
                sweeps.append(sweep)
                self._mark_cooldown(signal_key)
                
            except Exception as e:
                logger.debug(f"{self.name} error processing flow: {e}")
                continue
        
        # Sort by premium (highest first) and post
        sweeps.sort(key=lambda x: x['premium'], reverse=True)
        
        posted = 0
        for sweep in sweeps:
            try:
                success = await self._post_signal(sweep)
                if success:
                    posted += 1
            except Exception as e:
                logger.error(f"{self.name} error posting signal: {e}")
        
        logger.info(f"{self.name} posted {posted} golden sweep alerts")

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
