"""Bullseye Bot - AI signal tool for intraday movements"""
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import pandas as pd
import asyncio
import numpy as np
from .base_bot import BaseAutoBot
from src.data_fetcher import DataFetcher
from src.options_analyzer import OptionsAnalyzer
from src.config import Config
from src.utils.market_hours import MarketHours
from src.utils.market_context import MarketContext
from src.utils.exit_strategies import ExitStrategies

logger = logging.getLogger(__name__)

class BullseyeBot(BaseAutoBot):
    """
    Bullseye Bot - Swing Trading Signal Bot
    Identifies high-conviction swing trades that can pan out over a few days to a few weeks.
    Focuses on unusual volume, smart money, and price action confirmation.
    """

    def __init__(self, webhook_url: str, watchlist: List[str], fetcher: DataFetcher, analyzer: OptionsAnalyzer):
        super().__init__(webhook_url, "Bullseye Bot", scan_interval=300)  # Scan every 5 minutes
        self.watchlist = watchlist
        self.fetcher = fetcher
        self.analyzer = analyzer
        self.signal_history = {}

    async def scan_and_post(self):
        """Scan for high-conviction swing trades"""
        logger.info(f"{self.name} scanning for swing trade opportunities")

        if not MarketHours.is_market_open():
            logger.debug(f"{self.name} - Market closed, skipping scan")
            return
        
        market_context = await MarketContext.get_market_context(self.fetcher)
        
        tasks = [self._scan_for_swing_trade(symbol, market_context) for symbol in self.watchlist]
        all_signals = await asyncio.gather(*tasks, return_exceptions=True)
        
        flat_signals = [signal for sublist in all_signals if isinstance(sublist, list) for signal in sublist]
        
        # Rank and post top signals
        top_signals = sorted(flat_signals, key=lambda x: x['bullseye_score'], reverse=True)[:5] # Post top 5
        
        for signal in top_signals:
            await self._post_signal(signal)

    async def _scan_for_swing_trade(self, symbol: str, market_context: Dict) -> List[Dict]:
        """
        Scan a single symbol for swing trade setups using efficient REST flow detection.

        NEW APPROACH (REST):
        - Uses detect_unusual_flow() with $5K premium threshold
        - ATM filtering (delta 0.4-0.6 range)
        - 7-60 day DTE range for swing trades
        """
        signals = []
        try:
            current_price = await self.fetcher.get_stock_price(symbol)
            if not current_price:
                return signals

            # NEW: Use efficient flow detection (single API call)
            flows = await self.fetcher.detect_unusual_flow(
                underlying=symbol,
                min_premium=Config.BULLSEYE_MIN_PREMIUM,  # $5K minimum
                min_volume_delta=10  # At least 10 contracts of volume change
            )

            # Price Action Confirmation
            momentum = await self._calculate_momentum(symbol)
            if not momentum:
                return signals

            # Process each flow signal
            for flow in flows:
                # Extract flow data
                opt_type = flow['type']
                strike = flow['strike']
                expiration = flow['expiration']
                premium = flow['premium']
                total_volume = flow['total_volume']
                volume_delta = flow['volume_delta']
                open_interest = flow.get('open_interest', 0)
                delta = flow.get('delta', 0)

                # Calculate DTE
                exp_date = datetime.strptime(expiration, '%Y-%m-%d')
                days_to_expiry = (exp_date - datetime.now()).days

                # Filter 1: DTE range (7-60 days for swing trades)
                if days_to_expiry < 7 or days_to_expiry > 60:
                    continue

                # Filter 2: VOI ratio (volume/OI > 3.0)
                if open_interest == 0 or total_volume < 100:
                    continue

                voi_ratio = total_volume / open_interest
                if voi_ratio < 3.0:
                    continue

                # Filter 3: ATM options only (delta 0.4-0.6 range)
                if abs(delta) < 0.4 or abs(delta) > 0.6:
                    continue

                # Filter 4: Strike distance (within 15% of current price)
                strike_distance = abs(strike - current_price) / current_price
                if strike_distance > 0.15:
                    continue

                # Filter 5: Price action confirmation
                if (opt_type == 'CALL' and momentum['direction'] != 'bullish') or \
                   (opt_type == 'PUT' and momentum['direction'] != 'bearish'):
                    continue

                # Calculate Bullseye score
                bullseye_score = self._calculate_bullseye_score(
                    voi_ratio, premium, momentum['strength'], days_to_expiry
                )

                if bullseye_score >= Config.MIN_BULLSEYE_SCORE:
                    signal = {
                        'ticker': symbol,
                        'type': opt_type,
                        'strike': strike,
                        'expiration': expiration,
                        'current_price': current_price,
                        'days_to_expiry': days_to_expiry,
                        'premium': premium,
                        'volume': total_volume,
                        'open_interest': open_interest,
                        'voi_ratio': voi_ratio,
                        'momentum_strength': momentum['strength'],
                        'momentum_direction': momentum['direction'],
                        'bullseye_score': bullseye_score,
                        'market_context': market_context,
                        'volume_delta': volume_delta,
                        'delta': delta,
                        'gamma': flow.get('gamma', 0),
                        'vega': flow.get('vega', 0)
                    }

                    signal_key = f"{symbol}_{opt_type}_{strike}_{expiration}"
                    if signal_key not in self.signal_history or \
                       (datetime.now() - self.signal_history[signal_key]).total_seconds() > 3600 * 4:
                        signals.append(signal)
                        self.signal_history[signal_key] = datetime.now()

        except Exception as e:
            logger.error(f"Error scanning for swing trades on {symbol}: {e}")

        return signals

    def _calculate_bullseye_score(self, voi_ratio: float, premium: float, momentum_strength: float, dte: int) -> int:
        """Calculate the Bullseye Score for a swing trade using generic scoring"""
        score = self.calculate_score({
            'voi_ratio': (voi_ratio, [
                (10, 35),  # 10x+ → 35 points (35%)
                (5, 30),   # 5x+ → 30 points
                (3, 25)    # 3x+ → 25 points
            ]),
            'premium': (premium, [
                (250000, 30),  # $250k+ → 30 points (30%)
                (100000, 25),  # $100k+ → 25 points
                (50000, 20),   # $50k+ → 20 points
                (25000, 15)    # $25k+ → 15 points
            ]),
            'momentum': (momentum_strength, [
                (0.7, 20),  # 70%+ → 20 points (20%)
                (0.5, 15),  # 50%+ → 15 points
                (0.3, 10)   # 30%+ → 10 points
            ])
        })

        # DTE sweet spot (15%)
        if 21 <= dte <= 45:
            score += 15
        elif 7 <= dte <= 60:
            score += 10

        return min(score, 100)

    async def _calculate_momentum(self, symbol: str) -> Optional[Dict]:
        """Calculate daily/4-hour momentum for swing trades"""
        try:
            # Use daily bars for longer-term trend
            to_date = datetime.now().strftime('%Y-%m-%d')
            from_date = (datetime.now() - timedelta(days=90)).strftime('%Y-%m-%d')
            
            daily_bars = await self.fetcher.get_aggregates(
                symbol, 'day', 1, from_date, to_date
            )
            
            if daily_bars.empty or len(daily_bars) < 20: return None
            
            # Simple Moving Averages
            sma_20 = daily_bars['close'].rolling(window=20).mean().iloc[-1]
            sma_50 = daily_bars['close'].rolling(window=50).mean().iloc[-1]
            
            direction = 'neutral'
            strength = 0.5
            
            if sma_20 > sma_50 and daily_bars['close'].iloc[-1] > sma_20:
                direction = 'bullish'
                strength = 0.7 + (daily_bars['close'].iloc[-1] / sma_20 - 1) * 10
            elif sma_20 < sma_50 and daily_bars['close'].iloc[-1] < sma_20:
                direction = 'bearish'
                strength = 0.7 + (sma_20 / daily_bars['close'].iloc[-1] - 1) * 10
                
            return {
                'direction': direction,
                'strength': min(max(strength, 0), 1)
            }
        except Exception as e:
            logger.error(f"Error calculating momentum for {symbol}: {e}")
            return None

    async def _post_signal(self, signal: Dict):
        """Post the new Bullseye swing trade signal"""
        color = 0x007bff  # Professional Blue

        title = f"🎯 Bullseye Swing Idea: {signal['ticker']} {signal['type']}"
        description = f"**Bullseye Score: {signal['bullseye_score']}/100**"

        # Build fields
        fields = [
            {"name": "Contract", "value": f"${signal['strike']} {signal['type']} expiring {signal['expiration']}", "inline": False},
            {"name": "Thesis", "value": f"Detected **${signal['premium']:,.0f}** in premium on this contract, which is **{signal['voi_ratio']:.1f}x** its open interest. This unusual activity, combined with a **{signal['market_context']['regime']} market** and **{signal['momentum_strength']:.2f} {('bullish' if signal['type'] == 'CALL' else 'bearish')} momentum**, suggests a potential multi-day move.", "inline": False},
            {"name": "Current Stock Price", "value": f"${signal['current_price']:.2f}", "inline": True},
            {"name": "Days to Expiration", "value": f"{signal['days_to_expiry']} days", "inline": True},
            {"name": "Management", "value": "This is a swing trade idea. Consider a timeframe of several days to weeks. Always use your own risk management.", "inline": False}
        ]

        # Create embed with auto-disclaimer
        embed = self.create_signal_embed_with_disclaimer(
            title=title,
            description=description,
            color=color,
            fields=fields,
            footer="Bullseye Bot - High-Conviction Swing Trades"
        )

        await self.post_to_discord(embed)
        logger.info(f"Posted Bullseye SWING signal: {signal['ticker']} {signal['type']} ${signal['strike']} Score:{signal['bullseye_score']}")
