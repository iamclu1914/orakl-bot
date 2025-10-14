"""Bullseye Bot - AI signal tool for intraday movements"""
import logging
from datetime import datetime, timedelta
from typing import List, Dict
import pandas as pd
from .base_bot import BaseAutoBot
from src.data_fetcher import DataFetcher
from src.options_analyzer import OptionsAnalyzer
from src.config import Config

logger = logging.getLogger(__name__)

class BullseyeBot(BaseAutoBot):
    """
    Bullseye Bot
    AI signal tool that anticipates intraday movements in options contracts
    Focuses on same-day or very short-term expiries with momentum
    """

    def __init__(self, webhook_url: str, watchlist: List[str], fetcher: DataFetcher, analyzer: OptionsAnalyzer):
        super().__init__(webhook_url, "Bullseye Bot", scan_interval=180)  # 3 minutes for intraday
        self.watchlist = watchlist
        self.fetcher = fetcher
        self.analyzer = analyzer
        self.signal_history = {}
        self.price_history = {}  # Track price momentum

    async def scan_and_post(self):
        """Scan for intraday momentum signals"""
        logger.info(f"{self.name} scanning for intraday movements")

        # Only run during market hours
        is_open = await self.fetcher.is_market_open()
        if not is_open:
            logger.debug(f"{self.name} - Market closed")
            return

        for symbol in self.watchlist:
            try:
                signals = await self._scan_intraday_momentum(symbol)
                for signal in signals:
                    await self._post_signal(signal)
            except Exception as e:
                logger.error(f"{self.name} error scanning {symbol}: {e}")

    async def _scan_intraday_momentum(self, symbol: str) -> List[Dict]:
        """Scan for intraday momentum plays"""
        signals = []

        try:
            # Get current price
            current_price = await self.fetcher.get_stock_price(symbol)
            if not current_price:
                return signals

            # Track price momentum
            self._update_price_history(symbol, current_price)
            momentum = self._calculate_momentum(symbol)

            if momentum is None or abs(momentum) < 0.5:  # Minimum 0.5% move
                return signals

            # Get options trades (recent only)
            trades = await self.fetcher.get_options_trades(symbol)
            if trades.empty:
                return signals

            # Filter for high activity and near-term expiry
            today = datetime.now()
            max_exp = today + timedelta(days=3)  # 0-3 DTE for intraday

            recent_trades = trades[
                (trades['timestamp'] > datetime.now() - timedelta(minutes=30)) &
                (trades['premium'] >= 5000) &  # Lower minimum for intraday
                (trades['volume'] >= 50)
            ]

            if recent_trades.empty:
                return signals

            # Group by contract
            for (contract, opt_type, strike, expiration), group in recent_trades.groupby(
                ['contract', 'type', 'strike', 'expiration']
            ):
                exp_date = pd.to_datetime(expiration)

                # Only 0-3 DTE
                days_to_expiry = (exp_date - today).days
                if days_to_expiry < 0 or days_to_expiry > 3:
                    continue

                total_premium = group['premium'].sum()
                total_volume = group['volume'].sum()
                avg_price = group['price'].mean()

                # Check momentum alignment
                momentum_aligned = (
                    (momentum > 0 and opt_type == 'CALL') or
                    (momentum < 0 and opt_type == 'PUT')
                )

                if not momentum_aligned:
                    continue

                # Calculate strike distance
                strike_distance = abs(strike - current_price) / current_price * 100

                # Prefer ATM or slightly OTM (within 3%)
                if strike_distance > 5:
                    continue

                # Calculate probability with high volatility assumption
                prob_itm = self.analyzer.calculate_probability_itm(
                    opt_type, strike, current_price, days_to_expiry,
                    implied_volatility=0.5  # Higher IV for intraday
                )

                # AI scoring for intraday movement
                ai_score = self._calculate_ai_score(
                    momentum, total_volume, total_premium, strike_distance, days_to_expiry
                )

                if ai_score >= 70:  # High confidence threshold
                    signal = {
                        'ticker': symbol,
                        'type': opt_type,
                        'strike': strike,
                        'expiration': expiration,
                        'current_price': current_price,
                        'days_to_expiry': days_to_expiry,
                        'premium': total_premium,
                        'volume': total_volume,
                        'avg_price': avg_price,
                        'momentum': momentum,
                        'strike_distance': strike_distance,
                        'probability_itm': prob_itm,
                        'ai_score': ai_score
                    }

                    # Check if already posted
                    signal_key = f"{symbol}_{opt_type}_{strike}_{expiration}"
                    if signal_key not in self.signal_history:
                        signals.append(signal)
                        self.signal_history[signal_key] = datetime.now()

        except Exception as e:
            logger.error(f"Error scanning intraday momentum for {symbol}: {e}")

        return signals

    def _update_price_history(self, symbol: str, price: float):
        """Track recent price history for momentum"""
        if symbol not in self.price_history:
            self.price_history[symbol] = []

        self.price_history[symbol].append({
            'price': price,
            'timestamp': datetime.now()
        })

        # Keep only last 30 minutes
        cutoff = datetime.now() - timedelta(minutes=30)
        self.price_history[symbol] = [
            p for p in self.price_history[symbol] if p['timestamp'] > cutoff
        ]

    def _calculate_momentum(self, symbol: str) -> float:
        """Calculate price momentum percentage"""
        if symbol not in self.price_history or len(self.price_history[symbol]) < 2:
            return None

        history = self.price_history[symbol]
        old_price = history[0]['price']
        new_price = history[-1]['price']

        momentum = ((new_price - old_price) / old_price) * 100
        return momentum

    def _calculate_ai_score(self, momentum: float, volume: int, premium: float,
                           strike_distance: float, dte: int) -> int:
        """AI scoring algorithm for intraday signals"""
        score = 0

        # Momentum strength (40%)
        if abs(momentum) >= 2.0:
            score += 40
        elif abs(momentum) >= 1.0:
            score += 30
        elif abs(momentum) >= 0.5:
            score += 20

        # Volume intensity (25%)
        if volume >= 500:
            score += 25
        elif volume >= 200:
            score += 20
        elif volume >= 100:
            score += 15

        # Premium flow (20%)
        if premium >= 50000:
            score += 20
        elif premium >= 20000:
            score += 15
        elif premium >= 10000:
            score += 10

        # Strike proximity (10%)
        if strike_distance <= 1:
            score += 10
        elif strike_distance <= 3:
            score += 7

        # DTE factor (5%)
        if dte == 0:
            score += 5
        elif dte <= 1:
            score += 4

        return score

    async def _post_signal(self, signal: Dict):
        """Post Bullseye signal to Discord"""
        color = 0x00FF00 if signal['type'] == 'CALL' else 0xFF0000
        emoji = "🎯" if signal['type'] == 'CALL' else "🎯"
        direction = "↗️" if signal['momentum'] > 0 else "↘️"

        embed = self.create_embed(
            title=f"{emoji} Bullseye: {signal['ticker']} {direction}",
            description=f"AI Intraday {signal['type']} Signal | Score: {signal['ai_score']}/100",
            color=color,
            fields=[
                {
                    "name": "📊 Contract",
                    "value": f"{signal['type']} ${signal['strike']}\n{signal['days_to_expiry']}DTE",
                    "inline": True
                },
                {
                    "name": "🤖 AI Score",
                    "value": f"**{signal['ai_score']}/100**",
                    "inline": True
                },
                {
                    "name": "📈 Momentum",
                    "value": f"{signal['momentum']:+.2f}%",
                    "inline": True
                },
                {
                    "name": "💵 Current Price",
                    "value": f"${signal['current_price']:.2f}",
                    "inline": True
                },
                {
                    "name": "📊 Volume",
                    "value": f"{signal['volume']:,}",
                    "inline": True
                },
                {
                    "name": "💰 Premium",
                    "value": f"${signal['premium']:,.0f}",
                    "inline": True
                },
                {
                    "name": "🎯 Target",
                    "value": f"${signal['strike']:.2f} ({signal['strike_distance']:.1f}% {'away' if signal['strike_distance'] > 0 else 'ITM'})",
                    "inline": False
                },
                {
                    "name": "⏰ Timeframe",
                    "value": f"Intraday - {signal['days_to_expiry']} DTE",
                    "inline": True
                },
                {
                    "name": "🎲 Probability",
                    "value": f"{signal['probability_itm']:.1f}%",
                    "inline": True
                }
            ],
            footer="Bullseye Bot | AI Intraday Signals"
        )

        await self.post_to_discord(embed)
        logger.info(f"Posted Bullseye signal: {signal['ticker']} {signal['type']} ${signal['strike']} Score:{signal['ai_score']}")
