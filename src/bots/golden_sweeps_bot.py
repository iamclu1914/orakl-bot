"""Golden Sweeps Bot - 1 Million+ premium sweeps"""
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

class GoldenSweepsBot(BaseAutoBot):
    """
    Golden Sweeps Bot
    Tracks unusually large sweeps with premiums worth over 1 million dollars
    These represent massive conviction trades
    """

    def __init__(self, webhook_url: str, watchlist: List[str], fetcher: DataFetcher, analyzer: OptionsAnalyzer):
        super().__init__(webhook_url, "Golden Sweeps Bot", scan_interval=Config.GOLDEN_SWEEPS_INTERVAL)
        self.watchlist = watchlist
        self.fetcher = fetcher
        self.analyzer = analyzer
        self.signal_history = {}
        self.MIN_GOLDEN_PREMIUM = Config.GOLDEN_MIN_PREMIUM
        self.MIN_SCORE = Config.MIN_GOLDEN_SCORE

        # Enhanced analysis tools
        self.enhanced_analyzer = EnhancedAnalyzer(fetcher)
        self.deduplicator = SmartDeduplicator()

    @timed()
    async def scan_and_post(self):
        """Scan for golden sweeps (1M+ premium) with enhanced analysis"""
        logger.info(f"{self.name} scanning for million dollar sweeps")

        # Only scan during market hours (9:30 AM - 4:00 PM EST, Monday-Friday)
        if not MarketHours.is_market_open():
            logger.debug(f"{self.name} - Market closed, skipping scan")
            return
        
        signals_found = 0
        
        for symbol in self.watchlist:
            try:
                sweeps = await self._scan_golden_sweeps(symbol)
                
                # Enhance signals with NEW critical features
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
                        if volume_ratio >= 5.0:  # 5x average
                            volume_boost = 25
                        elif volume_ratio >= 3.0:  # 3x average
                            volume_boost = 15
                        elif volume_ratio >= 2.0:  # 2x average
                            volume_boost = 10

                        # CRITICAL FEATURE #2: Price Action Alignment
                        alignment = await self.enhanced_analyzer.check_price_action_alignment(
                            symbol, sweep['type']
                        )

                        if alignment:
                            sweep['price_aligned'] = alignment['aligned']
                            sweep['momentum_strength'] = alignment['strength']
                            sweep['alignment_confidence'] = alignment['confidence']

                            # Boost score for alignment
                            if alignment['aligned']:
                                volume_boost += 20  # Flow matches stock movement
                                if alignment['volume_confirmed']:
                                    volume_boost += 10  # Volume confirms direction

                        # CRITICAL FEATURE #3: Implied Move Calculator
                        implied = self.enhanced_analyzer.calculate_implied_move(
                            sweep['current_price'],
                            sweep['strike'],
                            sweep['avg_price'],
                            sweep['days_to_expiry'],
                            sweep['type']
                        )
                        sweep['breakeven'] = implied['breakeven']
                        sweep['needed_move'] = implied['needed_move_pct']
                        sweep['prob_profit'] = implied['prob_profit']
                        sweep['risk_grade'] = implied['grade']

                        # Apply volume and alignment boosts
                        sweep['enhanced_score'] = sweep['golden_score'] + volume_boost

                        # Only include if meets enhanced criteria (minimum 50%)
                        if sweep['enhanced_score'] >= max(50, self.MIN_SCORE):
                            enhanced_sweeps.append(sweep)
                            logger.debug(f"Enhanced {symbol}: Score {sweep['golden_score']}→{sweep['enhanced_score']} (Vol:{volume_ratio}x, Aligned:{alignment.get('aligned') if alignment else 'N/A'})")

                    except Exception as e:
                        logger.warning(f"Error enhancing signal for {symbol}: {e}")
                        # Fall back to original signal if meets minimum (50%)
                        if sweep['golden_score'] >= max(50, self.MIN_SCORE):
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
                labels={'bot': self.name, 'signal_type': 'golden_sweep'}
            )

    async def _scan_golden_sweeps(self, symbol: str) -> List[Dict]:
        """Scan for 1M+ premium sweeps"""
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

            # Filter for massive trades (last 15 minutes)
            recent = trades[
                (trades['timestamp'] > datetime.now() - timedelta(minutes=15)) &
                (trades['premium'] >= self.MIN_GOLDEN_PREMIUM)
            ]

            if recent.empty:
                return sweeps

            # Group by contract
            for (contract, opt_type, strike, expiration), group in recent.groupby(
                ['contract', 'type', 'strike', 'expiration']
            ):
                # Sort by timestamp
                group = group.sort_values('timestamp')

                total_premium = group['premium'].sum()
                total_volume = group['volume'].sum()
                num_trades = len(group)
                avg_price = group['price'].mean()

                # Must be at least $1M
                if total_premium < self.MIN_GOLDEN_PREMIUM:
                    continue

                # PRD Enhancement #1: Multi-exchange detection (require 3+ venues)
                exchanges_hit = self.detect_multi_exchange(group)
                if exchanges_hit < 3:
                    logger.debug(f"{symbol} {opt_type} {strike}: Only {exchanges_hit} exchanges (need 3+)")
                    continue

                # PRD Enhancement #2: Urgency check (require at least MEDIUM urgency)
                urgency_data = self.calculate_urgency(group)
                if urgency_data['urgency'] == 'LOW':
                    logger.debug(f"{symbol} {opt_type} {strike}: Low urgency ({urgency_data['cps']:.1f} cps)")
                    continue

                # PRD Enhancement #3: Smart strike filtering (≤5% OTM/ITM only)
                if not self.is_smart_strike(strike, current_price, opt_type):
                    strike_distance_pct = abs((strike - current_price) / current_price) * 100
                    logger.debug(f"{symbol} {opt_type} {strike}: Lottery ticket ({strike_distance_pct:.1f}% OTM)")
                    continue

                # Calculate metrics
                exp_date = pd.to_datetime(expiration)
                days_to_expiry = (exp_date - datetime.now()).days

                if days_to_expiry < 0 or days_to_expiry > 180:  # Up to 6 months for golden
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

                # Golden score (conviction level) - boosted for passing all PRD filters
                golden_score = self._calculate_golden_score(
                    total_premium, total_volume, abs(strike_distance), days_to_expiry
                )

                # Boost score for multi-exchange and high urgency (PRD Enhancement)
                score_boost = 0
                if exchanges_hit >= 5:
                    score_boost += 10
                elif exchanges_hit >= 4:
                    score_boost += 5

                if urgency_data['urgency'] == 'VERY HIGH':
                    score_boost += 15
                elif urgency_data['urgency'] == 'HIGH':
                    score_boost += 10
                elif urgency_data['urgency'] == 'MEDIUM':
                    score_boost += 5

                golden_score += score_boost

                # Time span of fills
                time_span = (group['timestamp'].max() - group['timestamp'].min()).total_seconds()

                # Only proceed if score meets minimum threshold
                if golden_score < self.MIN_SCORE:
                    continue

                sweep = {
                    'ticker': symbol,
                    'symbol': symbol,  # Add for compatibility
                    'type': opt_type,
                    'strike': strike,
                    'expiration': expiration,
                    'current_price': current_price,
                    'days_to_expiry': days_to_expiry,
                    'premium': total_premium,
                    'volume': total_volume,
                    'num_fills': num_trades,
                    'avg_price': avg_price,
                    'moneyness': moneyness,
                    'strike_distance': strike_distance,
                    'probability_itm': prob_itm,
                    'golden_score': golden_score,
                    'time_span': time_span,
                    'volume_ratio': total_volume / 100,  # Approximate for scoring
                    # PRD Enhancement: Add new fields
                    'exchanges_hit': exchanges_hit,
                    'urgency': urgency_data['urgency'],
                    'contracts_per_second': urgency_data['cps'],
                    'urgency_score': urgency_data['score']
                }

                # CRITICAL FEATURE #4: Smart Deduplication (catches accumulation)
                signal_key = f"{symbol}_{opt_type}_{strike}_{expiration}"
                dedup_result = self.deduplicator.should_alert(signal_key, total_premium)

                if dedup_result['should_alert']:
                    sweep['alert_type'] = dedup_result['type']  # NEW, ACCUMULATION, REFRESH
                    sweep['alert_reason'] = dedup_result['reason']
                    sweeps.append(sweep)

                    logger.info(f"✅ Golden Sweep passed PRD filters: {symbol} {opt_type} ${strike} - "
                              f"Exchanges:{exchanges_hit}, Urgency:{urgency_data['urgency']}, "
                              f"Score:{golden_score}/100")

        except Exception as e:
            logger.error(f"Error scanning golden sweeps for {symbol}: {e}")

        return sweeps

    def detect_multi_exchange(self, trades_df: pd.DataFrame) -> int:
        """PRD Enhancement: Count unique exchanges hit"""
        if 'exchange' not in trades_df.columns:
            return 1
        return trades_df['exchange'].nunique()

    def calculate_urgency(self, trades_df: pd.DataFrame) -> Dict:
        """PRD Enhancement: Calculate execution urgency (contracts per second)"""
        time_span = (trades_df['timestamp'].max() - trades_df['timestamp'].min()).total_seconds()
        total_contracts = trades_df['volume'].sum()

        contracts_per_sec = total_contracts / max(time_span, 1)

        if contracts_per_sec >= 200:
            return {'urgency': 'VERY HIGH', 'score': 1.0, 'cps': contracts_per_sec}
        elif contracts_per_sec >= 100:
            return {'urgency': 'HIGH', 'score': 0.8, 'cps': contracts_per_sec}
        elif contracts_per_sec >= 50:
            return {'urgency': 'MEDIUM', 'score': 0.6, 'cps': contracts_per_sec}
        else:
            return {'urgency': 'LOW', 'score': 0.4, 'cps': contracts_per_sec}

    def is_smart_strike(self, strike: float, current_price: float, option_type: str) -> bool:
        """PRD Enhancement: Filter lottery tickets (only ≤5% OTM/ITM allowed)"""
        distance_pct = abs((strike - current_price) / current_price) * 100

        # Only allow near-money strikes (≤5%)
        if distance_pct > 5.0:
            return False
        return True

    def _calculate_golden_score(self, premium: float, volume: int,
                                strike_distance: float, dte: int) -> int:
        """Calculate golden sweep score (0-100)"""
        score = 0

        # Premium magnitude (50%)
        if premium >= 10000000:  # $10M+
            score += 50
        elif premium >= 5000000:  # $5M+
            score += 45
        elif premium >= 2500000:  # $2.5M+
            score += 40
        elif premium >= 1000000:  # $1M+
            score += 35

        # Volume (20%)
        if volume >= 2000:
            score += 20
        elif volume >= 1000:
            score += 17
        elif volume >= 500:
            score += 14
        else:
            score += 10

        # Strike proximity (15%)
        if strike_distance <= 3:
            score += 15
        elif strike_distance <= 7:
            score += 12
        elif strike_distance <= 15:
            score += 8

        # DTE factor (15%)
        if 7 <= dte <= 45:  # Sweet spot for golden sweeps
            score += 15
        elif dte <= 90:
            score += 10
        else:
            score += 5

        return score

    async def _post_signal(self, sweep: Dict) -> bool:
        """Post enhanced golden sweep signal to Discord"""
        color = 0xFFD700  # Gold color

        # Format time
        now = datetime.now()
        time_str = now.strftime('%I:%M %p')
        date_str = now.strftime('%m/%d/%y')

        # Format expiration
        exp_str = sweep['expiration']

        # Format premium in millions
        premium_millions = sweep['premium'] / 1000000

        # Get enhanced score
        final_score = sweep.get('enhanced_score', sweep.get('final_score', sweep['golden_score']))

        # Get sector (placeholder - would need to be added to sweep data)
        sector = sweep.get('sector', 'N/A')

        # Format details string (contracts @ avg_price)
        details = f"{sweep['volume']:,} @ {sweep['avg_price']:.2f}"

        embed = self.create_embed(
            title=f"🏆 {sweep['ticker']} - Golden Sweep Detected",
            description="",
            color=color,
            fields=[
                {
                    "name": "Date",
                    "value": date_str,
                    "inline": True
                },
                {
                    "name": "Time",
                    "value": time_str,
                    "inline": True
                },
                {
                    "name": "Ticker",
                    "value": sweep['ticker'],
                    "inline": True
                },
                {
                    "name": "Exp",
                    "value": exp_str,
                    "inline": True
                },
                {
                    "name": "Strike",
                    "value": f"{sweep['strike']:.0f}",
                    "inline": True
                },
                {
                    "name": "C/P",
                    "value": sweep['type'] + "S",
                    "inline": True
                },
                {
                    "name": "Spot",
                    "value": f"{sweep['current_price']:.2f}",
                    "inline": True
                },
                {
                    "name": "Details",
                    "value": details,
                    "inline": True
                },
                {
                    "name": "Type",
                    "value": "SWEEP",
                    "inline": True
                },
                {
                    "name": "Prem",
                    "value": f"${premium_millions:.1f}M",
                    "inline": True
                },
                {
                    "name": "Algo Score",
                    "value": str(int(final_score)),
                    "inline": True
                },
                {
                    "name": "Sect",
                    "value": sector,
                    "inline": True
                }
            ]
        )

        # Add disclaimer
        embed['fields'].append({
            "name": "",
            "value": "Please always do your own due diligence on top of these trade ideas.",
            "inline": False
        })

        embed['footer'] = "ORAKL Bot - Golden Sweeps"

        success = await self.post_to_discord(embed)
        if success:
            logger.info(f"🚨 GOLDEN SWEEP: {sweep['ticker']} {sweep['type']} ${sweep['strike']} Premium:${premium_millions:.1f}M Score:{int(final_score)}")

        return success

        # Removed old enhanced fields code below
        if False and volume_ratio >= 2.0:
            embed['fields'].append({
                "name": "📊 Volume Analysis",
                "value": f"**{volume_ratio:.1f}x** above 30-day average (UNUSUAL)",
                "inline": False
            })

        if False and price_aligned:
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

        # Add accumulation warning
        if alert_type == 'ACCUMULATION':
            embed['fields'].append({
                "name": "🔥 ACCUMULATION ALERT 🔥",
                "value": f"**Continued buying pressure detected!** {sweep.get('alert_reason', '')}",
                "inline": False
            })
        else:
            embed['fields'].append({
                "name": "🚨 ALERT",
                "value": f"**MASSIVE CONVICTION: ${premium_millions:.2f}M position opened**",
                "inline": False
            })

        embed['footer'] = "Golden Sweeps Bot | Enhanced with Volume & Price Analysis"
        
        # Add market context if available
        if regime != 'unknown' or trend != 'unknown':
            context_value = []
            if regime != 'unknown':
                context_value.append(f"Regime: {regime.replace('_', ' ').title()}")
            if trend != 'unknown':
                context_value.append(f"Trend: {trend.replace('_', ' ').title()}")
            
            embed['fields'].insert(-1, {
                "name": "🌐 Market Context",
                "value": " | ".join(context_value),
                "inline": False
            })
        
        # Add notes if available
        if notes:
            embed['fields'].append({
                "name": "📝 Analysis Notes",
                "value": "\n".join(f"• {note}" for note in notes[:3]),  # Limit to 3 notes
                "inline": False
            })

        success = await self.post_to_discord(embed)
        if success:
            logger.info(f"🚨 GOLDEN SWEEP: {sweep['ticker']} {sweep['type']} ${sweep['strike']} Premium:${premium_millions:.2f}M Score:{int(final_score)}")
        
        return success
