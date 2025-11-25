"""Golden Sweeps Bot - 1 Million+ premium sweeps"""
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
        # Limit per-scan workload; rotate batches each scan (defaults to 200 if unset).
        self.scan_batch_size = getattr(Config, "GOLDEN_SWEEPS_SCAN_BATCH_SIZE", getattr(Config, "SWEEPS_SCAN_BATCH_SIZE", 200))
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
        """Scan for golden sweeps (1M+ premium) with enhanced analysis"""
        logger.info(f"{self.name} scanning for million dollar sweeps")

        # Only scan during market hours (9:30 AM - 4:00 PM EST, Monday-Friday)
        if not MarketHours.is_market_open(include_extended=False):
            logger.debug(f"{self.name} - Market closed, skipping scan")
            return
        
        # Use base class concurrent implementation
        await super().scan_and_post()
    
    async def _scan_sweeps(self, symbol: str) -> List[Dict]:
        sweeps: List[Dict] = []

        try:
            current_price = await self.fetcher.get_stock_price(symbol)
            if not current_price:
                return sweeps

            flows = await self.fetcher.detect_unusual_flow(
                underlying=symbol,
                min_premium=self.MIN_SWEEP_PREMIUM,
                min_volume_delta=self.MIN_VOLUME_DELTA
            )

            for flow in flows:
                opt_type = flow['type']
                strike = flow['strike']
                expiration = flow['expiration']
                premium = flow['premium']
                total_volume = flow['total_volume']
                volume_delta = flow['volume_delta']

                # Filter by trade size (volume_delta) instead of day volume for Golden Sweeps
                # We want to catch massive single orders even if day volume is low
                if volume_delta < self.MIN_VOLUME_DELTA:
                    self._log_skip(symbol, f"golden sweep size {volume_delta} < {self.MIN_VOLUME_DELTA} contracts")
                    continue

                exp_date = datetime.strptime(expiration, '%Y-%m-%d')
                days_to_expiry = (exp_date - datetime.now()).days
                # Allow 0DTE up to 2-year LEAPS for Golden Sweeps - $1M+ on LEAPS is still conviction
                if days_to_expiry < 0 or days_to_expiry > 730:
                    continue

                prob_itm = self.analyzer.calculate_probability_itm(
                    opt_type, strike, current_price, days_to_expiry
                )

                strike_distance = ((strike - current_price) / current_price) * 100
                # No strike distance filter for Golden Sweeps - $1M+ premium IS the conviction signal

                if opt_type == 'CALL':
                    moneyness = 'ITM' if strike < current_price else 'OTM' if strike > current_price else 'ATM'
                else:
                    moneyness = 'ITM' if strike > current_price else 'OTM' if strike < current_price else 'ATM'

                num_fills = max(3, int(volume_delta / 50))
                sweep_score = self._calculate_sweep_score(
                    premium, total_volume, num_fills, abs(strike_distance)
                )
                # Reward outsized premium so $1M+ sweeps are never filtered out by score alone
                if premium >= 5_000_000:
                    sweep_score += 20
                elif premium >= 3_000_000:
                    sweep_score += 15
                elif premium >= 2_000_000:
                    sweep_score += 10
                else:
                    sweep_score += 5
                sweep_score = min(sweep_score, 100)

                sweep = {
                    'ticker': symbol,
                    'symbol': symbol,
                    'type': opt_type,
                    'strike': strike,
                    'expiration': expiration,
                    'current_price': current_price,
                    'days_to_expiry': days_to_expiry,
                    'premium': premium,
                    'volume': total_volume,
                    'num_fills': num_fills,
                    'moneyness': moneyness,
                    'strike_distance': strike_distance,
                    'probability_itm': prob_itm,
                    'sweep_score': sweep_score,
                    'time_span': 0,
                    'volume_delta': volume_delta,
                    'delta': flow.get('delta', 0),
                    'gamma': flow.get('gamma', 0),
                    'vega': flow.get('vega', 0),
                    'avg_price': premium / (max(volume_delta, 1) * 100)
                }

                signal_key = f"{symbol}_{opt_type}_{strike}_{expiration}"
                dedup_result = self.deduplicator.should_alert(signal_key, premium)

                if dedup_result['should_alert']:
                    if self._cooldown_active(signal_key):
                        self._log_skip(symbol, f'golden sweep cooldown {signal_key}')
                        continue

                    sweep['alert_type'] = dedup_result['type']
                    sweep['alert_reason'] = dedup_result['reason']
                    sweeps.append(sweep)
                    self._mark_cooldown(signal_key)

        except Exception as e:
            logger.error(f"Error scanning golden sweeps for {symbol}: {e}")

        return sweeps

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
            )
        except Exception as exc:
            logger.exception("failed to publish golden sweep event: %s", exc)
