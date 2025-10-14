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

    @timed()
    async def scan_and_post(self):
        """Scan for golden sweeps (1M+ premium) with enhanced analysis"""
        logger.info(f"{self.name} scanning for million dollar sweeps")

        is_open = await self.fetcher.is_market_open()
        if not is_open:
            logger.debug(f"{self.name} - Market closed")
            return

        signals_found = 0
        
        for symbol in self.watchlist:
            try:
                sweeps = await self._scan_golden_sweeps(symbol)
                
                # Enhance signals with market context
                enhanced_sweeps = []
                for sweep in sweeps:
                    try:
                        # Get price data for context
                        price_data = await self.fetcher.get_aggregates(
                            symbol,
                            timespan='day',
                            multiplier=1,
                            from_date=(datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
                        )
                        
                        # Enhance with advanced scoring
                        enhanced = await self.analyzer.analyze_signal_with_context(
                            sweep,
                            price_data,
                            base_score=sweep['golden_score']
                        )
                        
                        # Only include if meets enhanced criteria
                        if enhanced.get('final_score', 0) >= self.MIN_SCORE:
                            enhanced_sweeps.append(enhanced)
                    except Exception as e:
                        logger.warning(f"Error enhancing signal for {symbol}: {e}")
                        # Fall back to original signal
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

                # Golden score (conviction level)
                golden_score = self._calculate_golden_score(
                    total_premium, total_volume, abs(strike_distance), days_to_expiry
                )

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
                    'volume_ratio': total_volume / 100  # Approximate for scoring
                }

                # Check if already posted (unique per hour to avoid spam)
                signal_key = f"{symbol}_{opt_type}_{strike}_{expiration}_{datetime.now().strftime('%Y%m%d%H')}"
                if signal_key not in self.signal_history:
                    sweeps.append(sweep)
                    self.signal_history[signal_key] = datetime.now()

        except Exception as e:
            logger.error(f"Error scanning golden sweeps for {symbol}: {e}")

        return sweeps

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
        emoji = "💎" if sweep['type'] == 'CALL' else "💎"

        # Format premium in millions
        premium_millions = sweep['premium'] / 1000000

        # Sentiment
        if sweep['moneyness'] == 'ITM':
            sentiment = f"Deep ITM {sweep['type']}"
        elif sweep['moneyness'] == 'ATM':
            sentiment = f"ATM {sweep['type']}"
        else:
            sentiment = f"OTM {sweep['type']}"
        
        # Get enhanced score if available
        final_score = sweep.get('final_score', sweep['golden_score'])
        confidence = sweep.get('confidence', 'N/A')
        
        # Get market context if available
        market_context = sweep.get('market_context', {})
        regime = market_context.get('regime', 'unknown')
        trend = market_context.get('trend', 'unknown')
        
        # Get suggestions if available
        suggestions = sweep.get('suggestions', {})
        action = suggestions.get('action', 'MONITOR')
        notes = suggestions.get('notes', [])

        # Build description with enhanced info
        description_parts = [f"**${premium_millions:.2f}M {sentiment}**"]
        if action != 'MONITOR':
            description_parts.append(f"**Action: {action}**")
        description_parts.append(f"Score: {int(final_score)}/100")
        if confidence != 'N/A':
            description_parts.append(f"Confidence: {int(confidence)}%")
        
        embed = self.create_embed(
            title=f"{emoji} GOLDEN SWEEP: {sweep['ticker']} 💰",
            description=" | ".join(description_parts),
            color=color,
            fields=[
                {
                    "name": "📊 Contract",
                    "value": f"{sweep['type']} ${sweep['strike']}\nExp: {sweep['expiration']}",
                    "inline": True
                },
                {
                    "name": "💰 PREMIUM",
                    "value": f"**${premium_millions:.2f}M**",
                    "inline": True
                },
                {
                    "name": "💎 Golden Score",
                    "value": f"**{sweep['golden_score']}/100**",
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
                    "name": "⚡ Number of Fills",
                    "value": f"{sweep['num_fills']} fills",
                    "inline": True
                },
                {
                    "name": "🎯 Strike",
                    "value": f"${sweep['strike']:.2f} ({sweep['moneyness']})",
                    "inline": True
                },
                {
                    "name": "📍 Distance to Strike",
                    "value": f"{sweep['strike_distance']:+.2f}%",
                    "inline": True
                },
                {
                    "name": "⏰ Days to Expiry",
                    "value": f"{sweep['days_to_expiry']} days",
                    "inline": True
                },
                {
                    "name": "🎲 Probability ITM",
                    "value": f"{sweep['probability_itm']:.1f}%",
                    "inline": True
                },
                {
                    "name": "💵 Avg Contract Price",
                    "value": f"${sweep['avg_price']:.2f}",
                    "inline": True
                },
                {
                    "name": "⏱️ Execution Time",
                    "value": f"{int(sweep['time_span'])}s",
                    "inline": True
                },
                {
                    "name": "🚨 ALERT",
                    "value": f"**MASSIVE CONVICTION: ${premium_millions:.2f}M position opened**",
                    "inline": False
                }
            ],
            footer="Golden Sweeps Bot | Million Dollar+ Sweeps"
        )
        
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
