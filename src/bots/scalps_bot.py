"""Scalps Bot - Quick stock and options signals using The Strat"""
import logging
from datetime import datetime, timedelta
from typing import List, Dict
import pandas as pd
from .base_bot import BaseAutoBot
from src.data_fetcher import DataFetcher
from src.options_analyzer import OptionsAnalyzer
from src.config import Config

logger = logging.getLogger(__name__)

class ScalpsBot(BaseAutoBot):
    """
    Scalps Bot
    Uses The Strat to identify quick stock and options signals that pan out immediately
    Focuses on 2-2 reversals, 3-2-2 inside-outside patterns, and momentum continuation
    """

    def __init__(self, webhook_url: str, watchlist: List[str], fetcher: DataFetcher, analyzer: OptionsAnalyzer):
        super().__init__(webhook_url, "Scalps Bot", scan_interval=120)  # 2 minutes for scalps
        self.watchlist = watchlist
        self.fetcher = fetcher
        self.analyzer = analyzer
        self.signal_history = {}
        self.candle_history = {}

    async def scan_and_post(self):
        """Scan for Strat-based scalp signals"""
        logger.info(f"{self.name} scanning for quick scalp setups")

        # Only during market hours
        is_open = await self.fetcher.is_market_open()
        if not is_open:
            logger.debug(f"{self.name} - Market closed")
            return

        for symbol in self.watchlist:
            try:
                signals = await self._scan_strat_setup(symbol)
                for signal in signals:
                    await self._post_signal(signal)
            except Exception as e:
                logger.error(f"{self.name} error scanning {symbol}: {e}")

    async def _scan_strat_setup(self, symbol: str) -> List[Dict]:
        """Scan for Strat patterns and quick scalp opportunities"""
        signals = []

        try:
            # Get current price
            current_price = await self.fetcher.get_stock_price(symbol)
            if not current_price:
                return signals

            # Get recent candle data (5-minute bars)
            candles = await self._get_recent_candles(symbol)
            if not candles or len(candles) < 3:
                return signals

            # Identify Strat pattern
            pattern = self._identify_strat_pattern(candles)
            if not pattern:
                return signals

            # Get active options with volume
            trades = await self.fetcher.get_options_trades(symbol)
            if trades.empty:
                return signals

            # Filter for scalp-friendly options
            recent_trades = trades[
                (trades['timestamp'] > datetime.now() - timedelta(minutes=15)) &
                (trades['volume'] >= 30) &
                (trades['premium'] >= 2000)
            ]

            if recent_trades.empty:
                return signals

            # Group by contract
            for (contract, opt_type, strike, expiration), group in recent_trades.groupby(
                ['contract', 'type', 'strike', 'expiration']
            ):
                exp_date = pd.to_datetime(expiration)
                days_to_expiry = (exp_date - datetime.now()).days

                # Prefer 0-7 DTE for scalps
                if days_to_expiry < 0 or days_to_expiry > 7:
                    continue

                total_volume = group['volume'].sum()
                total_premium = group['premium'].sum()

                # Check pattern alignment
                pattern_aligned = (
                    (pattern['direction'] == 'bullish' and opt_type == 'CALL') or
                    (pattern['direction'] == 'bearish' and opt_type == 'PUT')
                )

                if not pattern_aligned:
                    continue

                # Strike proximity check
                strike_distance = abs(strike - current_price) / current_price * 100
                if strike_distance > 3:  # Within 3% for scalps
                    continue

                # Volume intensity check
                if total_volume < 50:
                    continue

                # Calculate scalp score
                scalp_score = self._calculate_scalp_score(
                    pattern, total_volume, strike_distance, days_to_expiry
                )

                if scalp_score >= 65:
                    signal = {
                        'ticker': symbol,
                        'type': opt_type,
                        'strike': strike,
                        'expiration': expiration,
                        'current_price': current_price,
                        'days_to_expiry': days_to_expiry,
                        'volume': total_volume,
                        'premium': total_premium,
                        'pattern': pattern['name'],
                        'pattern_direction': pattern['direction'],
                        'strike_distance': strike_distance,
                        'scalp_score': scalp_score,
                        'timeframe': '5m'
                    }

                    # Check if already posted
                    signal_key = f"{symbol}_{opt_type}_{strike}_{expiration}"
                    if signal_key not in self.signal_history:
                        signals.append(signal)
                        self.signal_history[signal_key] = datetime.now()

        except Exception as e:
            logger.error(f"Error scanning Strat setup for {symbol}: {e}")

        return signals

    async def _get_recent_candles(self, symbol: str) -> List[Dict]:
        """Get REAL 5-minute candles from Polygon API"""
        try:
            # Get actual price bars from Polygon (last 1 hour = 12 bars)
            now = datetime.now()
            # Polygon API requires YYYY-MM-DD format only
            from_date = (now - timedelta(hours=1)).strftime('%Y-%m-%d')
            to_date = now.strftime('%Y-%m-%d')

            aggregates = await self.fetcher.get_aggregates(
                symbol,
                timespan='minute',
                multiplier=5,
                from_date=from_date,
                to_date=to_date
            )

            if aggregates.empty:
                logger.debug(f"No candle data for {symbol}")
                return []

            # Convert to candle format
            candles = []
            for _, row in aggregates.iterrows():
                candles.append({
                    'timestamp': row.get('timestamp', datetime.now()),
                    'open': row['open'],
                    'high': row['high'],
                    'low': row['low'],
                    'close': row['close'],
                    'volume': row.get('volume', 0)
                })

            # Return last 5 candles for pattern analysis
            return candles[-5:] if len(candles) >= 5 else candles

        except Exception as e:
            logger.error(f"Error fetching real candles for {symbol}: {e}")
            return []

    def _identify_strat_pattern(self, candles: List[Dict]) -> Dict:
        """Identify Strat pattern from candles"""
        if len(candles) < 3:
            return None

        last = candles[-1]
        prev = candles[-2]
        prev2 = candles[-3]

        # Inside bar (2)
        is_inside = (last['high'] < prev['high'] and last['low'] > prev['low'])

        # Outside bar (3)
        is_outside = (last['high'] > prev['high'] and last['low'] < prev['low'])

        # Directional bar (1)
        is_bullish = (last['close'] > last['open'])
        is_bearish = (last['close'] < last['open'])

        # 2-2 Reversal (inside bar after inside bar with direction change)
        if is_inside:
            prev_inside = (prev['high'] < prev2['high'] and prev['low'] > prev2['low'])
            if prev_inside:
                if is_bullish:
                    return {'name': '2-2 Bullish Reversal', 'direction': 'bullish', 'strength': 85}
                elif is_bearish:
                    return {'name': '2-2 Bearish Reversal', 'direction': 'bearish', 'strength': 85}

        # 3-2-2 Pattern (outside bar followed by inside bars)
        prev_outside = (prev['high'] > prev2['high'] and prev['low'] < prev2['low'])
        if is_inside and prev_outside:
            if is_bullish:
                return {'name': '3-2-2 Bullish', 'direction': 'bullish', 'strength': 90}
            elif is_bearish:
                return {'name': '3-2-2 Bearish', 'direction': 'bearish', 'strength': 90}

        # Simple directional continuation
        if is_bullish and prev['close'] > prev['open']:
            return {'name': 'Bullish Continuation', 'direction': 'bullish', 'strength': 70}
        elif is_bearish and prev['close'] < prev['open']:
            return {'name': 'Bearish Continuation', 'direction': 'bearish', 'strength': 70}

        return None

    def _calculate_scalp_score(self, pattern: Dict, volume: int,
                              strike_distance: float, dte: int) -> int:
        """Calculate scalp opportunity score"""
        score = 0

        # Pattern strength (40%)
        score += int(pattern['strength'] * 0.4)

        # Volume (30%)
        if volume >= 300:
            score += 30
        elif volume >= 150:
            score += 25
        elif volume >= 75:
            score += 20
        else:
            score += 15

        # Strike proximity (20%)
        if strike_distance <= 0.5:
            score += 20
        elif strike_distance <= 1:
            score += 15
        elif strike_distance <= 2:
            score += 10

        # DTE preference (10%)
        if dte <= 2:
            score += 10
        elif dte <= 5:
            score += 7

        return score

    async def _post_signal(self, signal: Dict):
        """Post Scalps signal to Discord"""
        color = 0x00FF00 if signal['type'] == 'CALL' else 0xFF0000
        emoji = "⚡" if signal['type'] == 'CALL' else "⚡"

        embed = self.create_embed(
            title=f"{emoji} Scalp: {signal['ticker']}",
            description=f"**{signal['pattern']}** | Quick {signal['type']} Setup",
            color=color,
            fields=[
                {
                    "name": "📊 Contract",
                    "value": f"{signal['type']} ${signal['strike']}\n{signal['days_to_expiry']}DTE",
                    "inline": True
                },
                {
                    "name": "⚡ Scalp Score",
                    "value": f"**{signal['scalp_score']}/100**",
                    "inline": True
                },
                {
                    "name": "📈 Pattern",
                    "value": f"{signal['pattern']}",
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
                    "name": "🎯 Strike",
                    "value": f"${signal['strike']:.2f}",
                    "inline": True
                },
                {
                    "name": "⏱️ Timeframe",
                    "value": f"{signal['timeframe']} bars",
                    "inline": True
                },
                {
                    "name": "📍 Distance",
                    "value": f"{signal['strike_distance']:.2f}%",
                    "inline": True
                },
                {
                    "name": "⚠️ Note",
                    "value": "Quick scalp - monitor closely",
                    "inline": False
                }
            ],
            footer="Scalps Bot | The Strat Quick Signals"
        )

        await self.post_to_discord(embed)
        logger.info(f"Posted Scalp signal: {signal['ticker']} {signal['type']} ${signal['strike']} Pattern:{signal['pattern']}")
