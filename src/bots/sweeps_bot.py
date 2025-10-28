"""Sweeps Bot - Large options sweeps tracker"""
import logging
from datetime import datetime, timedelta
from typing import List, Dict
import pandas as pd
from .base_bot import BaseAutoBot
from src.data_fetcher import DataFetcher
from src.options_analyzer import OptionsAnalyzer
from src.config import Config
from src.utils.monitoring import signals_generated, timed
from src.utils.exceptions import DataException, handle_exception
from src.utils.enhanced_analysis import EnhancedAnalyzer, SmartDeduplicator
from src.utils.market_hours import MarketHours

logger = logging.getLogger(__name__)

class SweepsBot(BaseAutoBot):
    """
    Sweeps Bot
    High premium large options sweeps showing conviction buyers
    Tracks aggressive market orders that sweep the order book
    """

    def __init__(self, webhook_url: str, watchlist: List[str], fetcher: DataFetcher, analyzer: OptionsAnalyzer):
        super().__init__(webhook_url, "Sweeps Bot", scan_interval=Config.SWEEPS_INTERVAL)
        self.watchlist = watchlist
        self.fetcher = fetcher
        self.analyzer = analyzer
        self.signal_history = {}
        self.MIN_SWEEP_PREMIUM = max(Config.SWEEPS_MIN_PREMIUM, 150000)
        self.MIN_VOLUME = 100
        self.MIN_VOLUME_DELTA = 50
        self.MAX_STRIKE_DISTANCE = 10  # percent
        self.MIN_SCORE = Config.MIN_SWEEP_SCORE

        # Enhanced analysis tools
        self.enhanced_analyzer = EnhancedAnalyzer(fetcher)
        self.deduplicator = SmartDeduplicator()

    @timed()
    async def scan_and_post(self):
        """Scan for large options sweeps with enhanced analysis"""
        logger.info(f"{self.name} scanning for large sweeps")

        # Only scan during market hours (9:30 AM - 4:00 PM EST, Monday-Friday)
        if not MarketHours.is_market_open(include_extended=False):
            logger.debug(f"{self.name} - Market closed, skipping scan")
            return
        
        # Use base class concurrent implementation
        await super().scan_and_post()
    
    async def _scan_symbol(self, symbol: str) -> List[Dict]:
        """
        Scan a symbol for large sweeps using efficient REST flow detection.

        NEW APPROACH (REST):
        - Uses detect_unusual_flow() with $50K premium threshold
        - Volume delta analysis for sweep detection
        - Enhanced with volume ratio and score boosting
        """
        try:
            sweeps = await self._scan_sweeps(symbol)

            # Enhance and filter signals
            enhanced_sweeps = []
            for sweep in sweeps:
                try:
                    # Volume Ratio Analysis
                    volume_ratio = await self.enhanced_analyzer.calculate_volume_ratio(
                        symbol, sweep['volume']
                    )
                    sweep['volume_ratio'] = volume_ratio

                    # Boost score for unusual volume
                    volume_boost = 0
                    if volume_ratio >= 5.0:
                        volume_boost = 25
                    elif volume_ratio >= 3.0:
                        volume_boost = 15
                    elif volume_ratio >= 2.0:
                        volume_boost = 10

                    # Apply boost to base score
                    sweep['sweep_score'] = min(
                        sweep.get('sweep_score', 50) + volume_boost,
                        100
                    )

                    # Filter by minimum score
                    if sweep['sweep_score'] >= Config.MIN_SWEEP_SCORE:
                        enhanced_sweeps.append(sweep)

                except Exception as e:
                    logger.debug(f"Error enhancing sweep: {e}")
                    # Include unenhanced sweep if it meets threshold
                    if sweep.get('sweep_score', 0) >= Config.MIN_SWEEP_SCORE:
                        enhanced_sweeps.append(sweep)

            # Return top 3 signals per symbol sorted by score
            return sorted(enhanced_sweeps, key=lambda x: x.get('sweep_score', 0), reverse=True)[:3]

        except Exception as e:
            logger.error(f"Error scanning {symbol} for sweeps: {e}")
            return []

    async def _scan_sweeps(self, symbol: str) -> List[Dict]:
        """
        Scan for sweep orders using efficient flow detection.

        NEW APPROACH (REST):
        - Single API call via detect_unusual_flow()
        - $50K+ premium threshold
        - Volume delta indicates aggressive buying/selling
        """
        sweeps = []

        try:
            # Get current price for context
            current_price = await self.fetcher.get_stock_price(symbol)
            if not current_price:
                return sweeps

            # NEW: Use efficient flow detection (single API call)
            flows = await self.fetcher.detect_unusual_flow(
                underlying=symbol,
                min_premium=self.MIN_SWEEP_PREMIUM,
                min_volume_delta=self.MIN_VOLUME_DELTA
            )

            # Process each flow signal
            for flow in flows:
                # Extract flow data
                opt_type = flow['type']
                strike = flow['strike']
                expiration = flow['expiration']
                premium = flow['premium']
                total_volume = flow['total_volume']
                volume_delta = flow['volume_delta']

                # Filter: Minimum volume threshold
                if total_volume < self.MIN_VOLUME or volume_delta < self.MIN_VOLUME_DELTA:
                    self._log_skip(symbol, f"sweep volume too small ({total_volume} total / {volume_delta} delta)")
                    continue

                # Calculate DTE
                exp_date = datetime.strptime(expiration, '%Y-%m-%d')
                days_to_expiry = (exp_date - datetime.now()).days

                # Filter: Valid DTE range (1-90 days)
                if days_to_expiry <= 0 or days_to_expiry > 90:
                    continue

                # Calculate probability ITM
                prob_itm = self.analyzer.calculate_probability_itm(
                    opt_type, strike, current_price, days_to_expiry
                )

                # Strike analysis
                strike_distance = ((strike - current_price) / current_price) * 100
                if abs(strike_distance) > self.MAX_STRIKE_DISTANCE:
                    self._log_skip(symbol, f'sweep strike distance {strike_distance:.1f}% exceeds {self.MAX_STRIKE_DISTANCE}%')
                    continue
                if opt_type == 'CALL':
                    moneyness = 'ITM' if strike < current_price else 'OTM' if strike > current_price else 'ATM'
                else:
                    moneyness = 'ITM' if strike > current_price else 'OTM' if strike < current_price else 'ATM'

                # Calculate sweep score (estimate 3+ fills based on volume delta)
                num_fills = max(3, int(volume_delta / 50))  # Estimate fills from volume
                sweep_score = self._calculate_sweep_score(
                    premium, total_volume, num_fills, abs(strike_distance)
                )

                # Create sweep signal
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
                    'time_span': 0,  # Not available in REST (was time between trades)
                    'volume_delta': volume_delta,
                    'delta': flow.get('delta', 0),
                    'gamma': flow.get('gamma', 0),
                    'vega': flow.get('vega', 0)
                }

                # CRITICAL FEATURE #4: Smart Deduplication
                signal_key = f"{symbol}_{opt_type}_{strike}_{expiration}"
                dedup_result = self.deduplicator.should_alert(signal_key, premium)

                if dedup_result['should_alert']:
                    if self._cooldown_active(signal_key):
                        self._log_skip(symbol, f'sweep cooldown {signal_key}')
                        continue
                    sweep['alert_type'] = dedup_result['type']
                    sweep['alert_reason'] = dedup_result['reason']
                    sweeps.append(sweep)
                    self._mark_cooldown(signal_key)

        except Exception as e:
            logger.error(f"Error scanning sweeps for {symbol}: {e}")

        return sweeps

    def _calculate_sweep_score(self, premium: float, volume: int,
                               num_fills: int, strike_distance: float) -> int:
        """Calculate sweep conviction score using generic scoring system"""
        score = self.calculate_score({
            'premium': (premium, [
                (500000, 40),  # $500k+ → 40 points (40%)
                (250000, 35),  # $250k+ → 35 points
                (100000, 30),  # $100k+ → 30 points
                (50000, 25)    # $50k+ → 25 points
            ]),
            'volume': (volume, [
                (1000, 25),  # 1000+ → 25 points (25%)
                (500, 20),   # 500+ → 20 points
                (250, 15),   # 250+ → 15 points
                (100, 10)    # 100+ → 10 points
            ]),
            'fills': (num_fills, [
                (5, 20),  # 5+ fills → 20 points (20%)
                (3, 15),  # 3+ fills → 15 points
                (2, 10)   # 2+ fills → 10 points
            ])
        })

        # Strike proximity (15%) - lower distance = higher score
        if strike_distance <= 2:
            score += 15
        elif strike_distance <= 5:
            score += 10
        elif strike_distance <= 10:
            score += 5

        return score

    async def _post_signal(self, sweep: Dict):
        """Post enhanced sweep signal to Discord"""
        color = 0x00FF00 if sweep['type'] == 'CALL' else 0xFF0000
        emoji = "🔥" if sweep['type'] == 'CALL' else "🔥"

        # Check if accumulation alert
        if sweep.get('alert_type') == 'ACCUMULATION':
            emoji = "🔥⚡🔥"
            color = 0xFF4500  # Orange-red

        # Determine sentiment
        if sweep['moneyness'] == 'ITM':
            sentiment = "Aggressive ITM Sweep"
        elif sweep['moneyness'] == 'ATM':
            sentiment = "ATM Sweep"
        else:
            sentiment = "Bullish OTM Sweep" if sweep['type'] == 'CALL' else "Bearish OTM Sweep"

        final_score = sweep.get('enhanced_score', sweep['sweep_score'])

        # Build confidence string
        volume_ratio = sweep.get('volume_ratio', 0)
        price_aligned = sweep.get('price_aligned', False)
        confidence_parts = []
        if volume_ratio >= 3.0:
            confidence_parts.append(f"{volume_ratio:.1f}x Vol")
        if price_aligned:
            confidence_parts.append("Price Aligned")
        confidence = " | ".join(confidence_parts) if confidence_parts else "N/A"

        alert_type = sweep.get('alert_type', 'NEW')
        description_parts = [f"**{sentiment}**"]
        if alert_type == 'ACCUMULATION':
            description_parts.append("🔥 **ACCUMULATION** 🔥")
        description_parts.append(f"Score: {int(final_score)}/100")
        if confidence != 'N/A':
            description_parts.append(confidence)

        # Build base fields
        fields = [
            {"name": "📊 Contract", "value": f"{sweep['type']} ${sweep['strike']}\nExp: {sweep['expiration']}", "inline": True},
            {"name": "💰 Premium", "value": f"**${sweep['premium']:,.0f}**", "inline": True},
            {"name": "🔥 Sweep Score", "value": f"**{sweep['sweep_score']}/100**", "inline": True},
            {"name": "📈 Current Price", "value": f"${sweep['current_price']:.2f}", "inline": True},
            {"name": "📊 Volume", "value": f"{sweep['volume']:,} contracts", "inline": True},
            {"name": "⚡ Fills", "value": f"{sweep['num_fills']} rapid fills", "inline": True},
            {"name": "🎯 Strike", "value": f"${sweep['strike']:.2f} ({sweep['moneyness']})", "inline": True},
            {"name": "📍 Distance", "value": f"{sweep['strike_distance']:+.2f}%", "inline": True},
            {"name": "⏰ DTE", "value": f"{sweep['days_to_expiry']} days", "inline": True}
        ]

        # Add enhanced analysis fields
        if volume_ratio >= 2.0:
            fields.append({"name": "📊 Volume Analysis", "value": f"**{volume_ratio:.1f}x** above 30-day average (UNUSUAL)", "inline": False})

        if price_aligned:
            momentum_str = sweep.get('momentum_strength', 0)
            fields.append({"name": "✅ Price Action Confirmed", "value": f"Options flow aligned with stock movement ({momentum_str:+.2f}%)", "inline": False})

        # Add implied move analysis
        if 'needed_move' in sweep:
            fields.append({"name": "🎯 Break-Even Analysis", "value": f"Needs {sweep['needed_move']:+.1f}% move to ${sweep['breakeven']:.2f} | Risk: {sweep['risk_grade']} | Prob: {sweep['prob_profit']}%", "inline": False})

        # Add accumulation warning
        if alert_type == 'ACCUMULATION':
            fields.append({"name": "🔥 ACCUMULATION ALERT 🔥", "value": f"**Continued buying pressure detected!** {sweep.get('alert_reason', '')}", "inline": False})

        # Create embed with auto-disclaimer
        embed = self.create_signal_embed_with_disclaimer(
            title=f"{emoji} SWEEP: {sweep['ticker']}",
            description=" | ".join(description_parts),
            color=color,
            fields=fields,
            footer="Sweeps Bot | Enhanced with Volume & Price Analysis"
        )

        success = await self.post_to_discord(embed)
        if success:
            logger.info(f"🚨 SWEEP: {sweep['ticker']} {sweep['type']} ${sweep['strike']} Premium:${sweep['premium']:,.0f} Score:{int(final_score)}")

        return success
