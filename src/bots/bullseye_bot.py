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
        """Scan a single symbol for swing trade setups"""
        signals = []
        try:
            current_price = await self.fetcher.get_stock_price(symbol)
            if not current_price: return signals

            # 1. Focus on longer expirations (7-60 days)
            from_date = (datetime.now() + timedelta(days=7)).strftime('%Y-%m-%d')
            to_date = (datetime.now() + timedelta(days=60)).strftime('%Y-%m-%d')
            
            options_chain = await self.fetcher.get_options_chain(symbol, expiration_date_gte=from_date, expiration_date_lte=to_date)
            if options_chain.empty: return signals

            # Analyze each contract in the chain
            for _, contract in options_chain.iterrows():
                # 2. Unusual Volume & Open Interest (VOI > 3)
                volume = contract.get('day', {}).get('volume', 0)
                open_interest = contract.get('open_interest', 0)
                
                if open_interest == 0 or volume < 100: continue
                
                voi_ratio = volume / open_interest
                if voi_ratio < 3.0: continue

                # 3. Significant Smart Money (>= $25k premium)
                last_price = contract.get('day', {}).get('close', 0)
                premium = volume * last_price * 100
                if premium < 25000: continue

                # 4. Price Action Confirmation
                momentum = await self._calculate_momentum(symbol)
                opt_type = contract.get('contract_type', '').upper()
                
                if not momentum or \
                   (opt_type == 'CALL' and momentum['direction'] != 'bullish') or \
                   (opt_type == 'PUT' and momentum['direction'] != 'bearish'):
                    continue
                
                # 5. Strike Price Sanity Check (near the money)
                strike_price = contract.get('strike_price', 0)
                strike_distance = abs(strike_price - current_price) / current_price
                if strike_distance > 0.15: # Within 15% of current price
                    continue

                # If all checks pass, calculate score and create signal
                days_to_expiry = (pd.to_datetime(contract['expiration_date']) - datetime.now()).days
                
                bullseye_score = self._calculate_bullseye_score(
                    voi_ratio, premium, momentum['strength'], days_to_expiry
                )

                if bullseye_score >= 70:
                    signal = {
                        'ticker': symbol,
                        'type': opt_type,
                        'strike': strike_price,
                        'expiration': contract['expiration_date'],
                        'current_price': current_price,
                        'days_to_expiry': days_to_expiry,
                        'premium': premium,
                        'volume': volume,
                        'open_interest': open_interest,
                        'voi_ratio': voi_ratio,
                        'momentum_strength': momentum['strength'],
                        'bullseye_score': bullseye_score,
                        'market_context': market_context
                    }
                    
                    signal_key = f"{symbol}_{opt_type}_{strike_price}_{contract['expiration_date']}"
                    if signal_key not in self.signal_history or \
                       (datetime.now() - self.signal_history[signal_key]).total_seconds() > 3600 * 4: # Re-alert after 4 hours
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
