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
        self.MIN_SWEEP_PREMIUM = Config.SWEEPS_MIN_PREMIUM
        self.MIN_SCORE = Config.MIN_SWEEP_SCORE

        # Enhanced analysis tools
        self.enhanced_analyzer = EnhancedAnalyzer(fetcher)
        self.deduplicator = SmartDeduplicator()

    @timed()
    async def scan_and_post(self):
        """Scan for large options sweeps with enhanced analysis"""
        logger.info(f"{self.name} scanning for large sweeps")

        # Only scan during market hours (9:30 AM - 4:00 PM EST, Monday-Friday)
        if not MarketHours.is_market_open():
            logger.debug(f"{self.name} - Market closed, skipping scan")
            return
        
        # Use base class concurrent implementation
        await super().scan_and_post()
    
    async def _scan_symbol(self, symbol: str) -> List[Dict]:
        """Scan a symbol for large sweeps with enhancements"""
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
                    
                    # Apply score adjustments
                    if sweep.get('sweep_score', 0) >= Config.MIN_SWEEP_SCORE:
                        enhanced_sweeps.append(sweep)
                except Exception as e:
                    logger.error(f"Error enhancing sweep: {e}")
                    if sweep.get('sweep_score', 0) >= Config.MIN_SWEEP_SCORE:
                        enhanced_sweeps.append(sweep)
            
            # Return top 3 signals per symbol
            return sorted(enhanced_sweeps, key=lambda x: x.get('sweep_score', 0), reverse=True)[:3]
        except Exception as e:
            logger.error(f"Error scanning {symbol}: {e}")
            return []
        
        # OLD SEQUENTIAL CODE - REMOVED
        signals_found = 0
        for symbol in self.watchlist:
            try:
                sweeps = await self._scan_sweeps(symbol)

                # Enhance signals with critical features
                enhanced_sweeps = []
                for sweep in sweeps:
                    try:
                        # CRITICAL FEATURE #1: Volume Ratio Analysis
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

                        # CRITICAL FEATURE #2: Price Action Alignment
                        alignment = await self.enhanced_analyzer.check_price_action_alignment(
                            symbol, sweep['type']
                        )

                        if alignment:
                            sweep['price_aligned'] = alignment['aligned']
                            sweep['momentum_strength'] = alignment['strength']
                            sweep['alignment_confidence'] = alignment['confidence']

                            if alignment['aligned']:
                                volume_boost += 20
                                if alignment['volume_confirmed']:
                                    volume_boost += 10

                        # CRITICAL FEATURE #3: Implied Move Calculator
                        avg_price = sweep['premium'] / (sweep['volume'] * 100)
                        implied = self.enhanced_analyzer.calculate_implied_move(
                            sweep['current_price'],
                            sweep['strike'],
                            avg_price,
                            sweep['days_to_expiry'],
                            sweep['type']
                        )
                        sweep['breakeven'] = implied['breakeven']
                        sweep['needed_move'] = implied['needed_move_pct']
                        sweep['prob_profit'] = implied['prob_profit']
                        sweep['risk_grade'] = implied['grade']

                        # Apply boosts
                        sweep['enhanced_score'] = sweep['sweep_score'] + volume_boost

                        # Require minimum 50% confidence
                        if sweep['enhanced_score'] >= max(50, self.MIN_SCORE):
                            enhanced_sweeps.append(sweep)

                    except Exception as e:
                        logger.warning(f"Error enhancing signal for {symbol}: {e}")
                        # Require minimum 50% confidence even for fallback
                        if sweep['sweep_score'] >= max(50, self.MIN_SCORE):
                            enhanced_sweeps.append(sweep)

                # Post enhanced signals
                for sweep in enhanced_sweeps:
                    if await self._post_signal(sweep):
                        signals_found += 1

            except Exception as e:
                error_info = handle_exception(e, logger)
                logger.error(f"{self.name} error scanning {symbol}: {error_info['message']}")

        if signals_found > 0:
            signals_generated.inc(
                value=signals_found,
                labels={'bot': self.name, 'signal_type': 'sweep'}
            )

    async def _scan_sweeps(self, symbol: str) -> List[Dict]:
        """Scan for sweep orders"""
        sweeps = []

        try:
            # Get current price
            current_price = await self.fetcher.get_stock_price(symbol)
            if not current_price:
                return sweeps

            # Get recent options trades
            trades = await self.fetcher.get_options_trades(symbol)
            if trades.empty:
                return sweeps

            # Filter recent high-value trades (last 10 minutes)
            recent = trades[
                (trades['timestamp'] > datetime.now() - timedelta(minutes=10)) &
                (trades['premium'] >= self.MIN_SWEEP_PREMIUM)
            ]

            if recent.empty:
                return sweeps

            # Identify sweeps (aggressive fills at multiple price levels)
            # Group by contract and look for rapid succession
            for (contract, opt_type, strike, expiration), group in recent.groupby(
                ['contract', 'type', 'strike', 'expiration']
            ):
                # Sort by timestamp
                group = group.sort_values('timestamp')

                # Check for sweep characteristics
                total_premium = group['premium'].sum()
                total_volume = group['volume'].sum()
                num_trades = len(group)

                # Sweep detection:
                # 1. Multiple fills in quick succession (>2 trades in <5 minutes)
                # 2. Large premium ($50k+)
                # 3. Aggressive pricing (likely market orders)

                time_span = (group['timestamp'].max() - group['timestamp'].min()).total_seconds()

                is_sweep = (
                    num_trades >= 2 and
                    time_span <= 300 and  # Within 5 minutes
                    total_premium >= self.MIN_SWEEP_PREMIUM
                )

                if not is_sweep:
                    continue

                # Calculate metrics
                exp_date = pd.to_datetime(expiration)
                days_to_expiry = (exp_date - datetime.now()).days

                if days_to_expiry < 0 or days_to_expiry > 90:
                    continue

                # Probability ITM
                prob_itm = self.analyzer.calculate_probability_itm(
                    opt_type, strike, current_price, days_to_expiry
                )

                # Strike analysis
                strike_distance = ((strike - current_price) / current_price) * 100
                if opt_type == 'CALL':
                    moneyness = 'ITM' if strike < current_price else 'OTM' if strike > current_price else 'ATM'
                else:
                    moneyness = 'ITM' if strike > current_price else 'OTM' if strike < current_price else 'ATM'

                # Calculate sweep score
                sweep_score = self._calculate_sweep_score(
                    total_premium, total_volume, num_trades, abs(strike_distance)
                )

                sweep = {
                    'ticker': symbol,
                    'symbol': symbol,
                    'type': opt_type,
                    'strike': strike,
                    'expiration': expiration,
                    'current_price': current_price,
                    'days_to_expiry': days_to_expiry,
                    'premium': total_premium,
                    'volume': total_volume,
                    'num_fills': num_trades,
                    'moneyness': moneyness,
                    'strike_distance': strike_distance,
                    'probability_itm': prob_itm,
                    'sweep_score': sweep_score,
                    'time_span': time_span
                }

                # CRITICAL FEATURE #4: Smart Deduplication
                signal_key = f"{symbol}_{opt_type}_{strike}_{expiration}"
                dedup_result = self.deduplicator.should_alert(signal_key, total_premium)

                if dedup_result['should_alert']:
                    sweep['alert_type'] = dedup_result['type']
                    sweep['alert_reason'] = dedup_result['reason']
                    sweeps.append(sweep)

        except Exception as e:
            logger.error(f"Error scanning sweeps for {symbol}: {e}")

        return sweeps

    def _calculate_sweep_score(self, premium: float, volume: int,
                               num_fills: int, strike_distance: float) -> int:
        """Calculate sweep conviction score"""
        score = 0

        # Premium size (40%)
        if premium >= 500000:
            score += 40
        elif premium >= 250000:
            score += 35
        elif premium >= 100000:
            score += 30
        elif premium >= 50000:
            score += 25

        # Volume (25%)
        if volume >= 1000:
            score += 25
        elif volume >= 500:
            score += 20
        elif volume >= 250:
            score += 15
        elif volume >= 100:
            score += 10

        # Number of fills (20%)
        if num_fills >= 5:
            score += 20
        elif num_fills >= 3:
            score += 15
        elif num_fills >= 2:
            score += 10

        # Strike proximity (15%)
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

        embed = self.create_embed(
            title=f"{emoji} SWEEP: {sweep['ticker']}",
            description=" | ".join(description_parts),
            color=color,
            fields=[
                {
                    "name": "📊 Contract",
                    "value": f"{sweep['type']} ${sweep['strike']}\nExp: {sweep['expiration']}",
                    "inline": True
                },
                {
                    "name": "💰 Premium",
                    "value": f"**${sweep['premium']:,.0f}**",
                    "inline": True
                },
                {
                    "name": "🔥 Sweep Score",
                    "value": f"**{sweep['sweep_score']}/100**",
                    "inline": True
                },
                {
                    "name": "📈 Current Price",
                    "value": f"${sweep['current_price']:.2f}",
                    "inline": True
                },
                {
                    "name": "📊 Volume",
                    "value": f"{sweep['volume']:,} contracts",
                    "inline": True
                },
                {
                    "name": "⚡ Fills",
                    "value": f"{sweep['num_fills']} rapid fills",
                    "inline": True
                },
                {
                    "name": "🎯 Strike",
                    "value": f"${sweep['strike']:.2f} ({sweep['moneyness']})",
                    "inline": True
                },
                {
                    "name": "📍 Distance",
                    "value": f"{sweep['strike_distance']:+.2f}%",
                    "inline": True
                },
                {
                    "name": "⏰ DTE",
                    "value": f"{sweep['days_to_expiry']} days",
                    "inline": True
                },
                {
                    "name": "🎲 Probability ITM",
                    "value": f"{sweep['probability_itm']:.1f}%",
                    "inline": True
                },
                {
                    "name": "⏱️ Time Span",
                    "value": f"{int(sweep['time_span'])}s sweep",
                    "inline": True
                },
            ]
        )

        # Add enhanced analysis fields
        if volume_ratio >= 2.0:
            embed['fields'].append({
                "name": "📊 Volume Analysis",
                "value": f"**{volume_ratio:.1f}x** above 30-day average (UNUSUAL)",
                "inline": False
            })

        if price_aligned:
            momentum_str = sweep.get('momentum_strength', 0)
            embed['fields'].append({
                "name": "✅ Price Action Confirmed",
                "value": f"Options flow aligned with stock movement ({momentum_str:+.2f}%)",
                "inline": False
            })

        # Add implied move analysis
        if 'needed_move' in sweep:
            embed['fields'].append({
                "name": "🎯 Break-Even Analysis",
                "value": f"Needs {sweep['needed_move']:+.1f}% move to ${sweep['breakeven']:.2f} | Risk: {sweep['risk_grade']} | Prob: {sweep['prob_profit']}%",
                "inline": False
            })

        # Add accumulation warning or insight
        if alert_type == 'ACCUMULATION':
            embed['fields'].append({
                "name": "🔥 ACCUMULATION ALERT 🔥",
                "value": f"**Continued buying pressure detected!** {sweep.get('alert_reason', '')}",
                "inline": False
            })
        else:
            embed['fields'].append({
                "name": "💡 Insight",
                "value": f"Large sweep shows conviction - {sweep['num_fills']} fills in {int(sweep['time_span'])}s",
                "inline": False
            })

        # Add disclaimer
        embed['fields'].append({
            "name": "",
            "value": "Please always do your own due diligence on top of these trade ideas.",
            "inline": False
        })

        embed['footer'] = "Sweeps Bot | Enhanced with Volume & Price Analysis"

        success = await self.post_to_discord(embed)
        if success:
            logger.info(f"🚨 SWEEP: {sweep['ticker']} {sweep['type']} ${sweep['strike']} Premium:${sweep['premium']:,.0f} Score:{int(final_score)}")

        return success
