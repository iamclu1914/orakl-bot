"""Breakouts Bot - Daily & Intraday stock breakouts"""
import logging
from datetime import datetime, timedelta
from typing import List, Dict
from .base_bot import BaseAutoBot
from src.data_fetcher import DataFetcher
from src.options_analyzer import OptionsAnalyzer
from src.utils.market_hours import MarketHours

logger = logging.getLogger(__name__)

class BreakoutsBot(BaseAutoBot):
    """
    Breakouts Bot
    Analyzes stocks for breakout patterns (price breaking above resistance or below support)
    Tracks volume, momentum, and technical indicators
    """

    def __init__(self, webhook_url: str, watchlist: List[str], fetcher: DataFetcher, analyzer: OptionsAnalyzer):
        super().__init__(webhook_url, "Breakouts Bot", scan_interval=300)  # 5 minutes
        self.watchlist = watchlist
        self.fetcher = fetcher
        self.analyzer = analyzer
        self.signal_history = {}
        self.price_history = {}
        self.volume_history = {}

    async def scan_and_post(self):
        """Scan for stock breakouts"""
        logger.info(f"{self.name} scanning for breakouts")

        # Only scan during market hours (9:30 AM - 4:00 PM EST, Monday-Friday)
        if not MarketHours.is_market_open():
            logger.debug(f"{self.name} - Market closed, skipping scan")
            return
        
        for symbol in self.watchlist:
            try:
                breakouts = await self._scan_breakout(symbol)
                for breakout in breakouts:
                    await self._post_signal(breakout)
            except Exception as e:
                logger.error(f"{self.name} error scanning {symbol}: {e}")

    async def _scan_breakout(self, symbol: str) -> List[Dict]:
        """Scan for breakout patterns"""
        breakouts = []

        try:
            # Get current price
            current_price = await self.fetcher.get_stock_price(symbol)
            if not current_price:
                return breakouts

            # Get historical data for pattern analysis
            # Using Polygon aggregates for the last 20 days
            end_date = datetime.now()
            start_date = end_date - timedelta(days=20)

            candles = await self._get_aggregates(
                symbol,
                start_date.strftime('%Y-%m-%d'),
                end_date.strftime('%Y-%m-%d'),
                timespan='day'
            )

            if not candles or len(candles) < 10:
                return breakouts

            # Calculate resistance and support levels with pattern detection
            highs = [c['high'] for c in candles]
            lows = [c['low'] for c in candles]
            closes = [c['close'] for c in candles]
            volumes = [c['volume'] for c in candles]

            # Find resistance with multiple touches (pattern recognition)
            resistance, resistance_touches = self._find_resistance_with_touches(highs[-10:])
            # Find support with multiple touches
            support, support_touches = self._find_support_with_touches(lows[-10:])

            # Average volume
            avg_volume = sum(volumes) / len(volumes)
            recent_volume = volumes[-1] if volumes else 0

            # Volume surge detection
            volume_surge = recent_volume / avg_volume if avg_volume > 0 else 1

            # Calculate technical indicators for momentum
            rsi = self._calculate_rsi(closes)
            sma_20 = sum(closes[-20:]) / min(20, len(closes)) if len(closes) >= 5 else current_price
            sma_50 = sum(closes) / len(closes) if len(closes) >= 10 else current_price

            # Price momentum
            prev_close = closes[-2] if len(closes) >= 2 else current_price
            price_change_pct = ((current_price - prev_close) / prev_close) * 100

            # Trend confirmation (price above MAs = bullish, below = bearish)
            above_sma20 = current_price > sma_20
            above_sma50 = current_price > sma_50

            # Volume pattern analysis (consolidation check)
            recent_avg_volume = sum(volumes[-5:]) / 5 if len(volumes) >= 5 else avg_volume
            volume_consolidation = recent_avg_volume < avg_volume * 0.9  # Decreasing volume before breakout

            # Breakout detection (more stringent criteria for quality)
            breakout_type = None
            breakout_level = None

            # Bullish breakout (breaking above resistance with conviction)
            if current_price > resistance * 1.005:  # 0.5% above resistance (stronger break)
                if volume_surge >= 2.0:  # Volume confirmation (institutional interest)
                    # Additional quality checks
                    if resistance_touches >= 2:  # Multiple tests of resistance
                        if above_sma20:  # Trending above 20-day MA
                            breakout_type = 'BULLISH'
                            breakout_level = resistance

            # Bearish breakdown (breaking below support with conviction)
            elif current_price < support * 0.995:  # 0.5% below support (stronger break)
                if volume_surge >= 2.0:  # Volume confirmation (institutional interest)
                    # Additional quality checks
                    if support_touches >= 2:  # Multiple tests of support
                        if not above_sma20:  # Trending below 20-day MA
                            breakout_type = 'BEARISH'
                            breakout_level = support

            if not breakout_type:
                return breakouts

            # Calculate breakout score
            breakout_score = self._calculate_breakout_score(
                volume_surge, abs(price_change_pct), current_price, breakout_level
            )

            if breakout_score >= 60:  # Lowered slightly to compensate for stricter entry criteria
                # Calculate next levels
                if breakout_type == 'BULLISH':
                    next_target = resistance * 1.05  # 5% above resistance
                    stop_loss = support
                else:
                    next_target = support * 0.95  # 5% below support
                    stop_loss = resistance

                breakout = {
                    'ticker': symbol,
                    'current_price': current_price,
                    'breakout_type': breakout_type,
                    'breakout_level': breakout_level,
                    'resistance': resistance,
                    'support': support,
                    'price_change_pct': price_change_pct,
                    'volume_surge': volume_surge,
                    'avg_volume': avg_volume,
                    'recent_volume': recent_volume,
                    'breakout_score': breakout_score,
                    'next_target': next_target,
                    'stop_loss': stop_loss
                }

                # Check if already posted (once per day per ticker)
                signal_key = f"{symbol}_{breakout_type}_{datetime.now().strftime('%Y%m%d')}"
                if signal_key not in self.signal_history:
                    breakouts.append(breakout)
                    self.signal_history[signal_key] = datetime.now()

        except Exception as e:
            logger.error(f"Error scanning breakout for {symbol}: {e}")

        return breakouts

    async def _get_aggregates(self, symbol: str, start_date: str, end_date: str, timespan: str = 'day') -> List[Dict]:
        """Get aggregate bars from Polygon"""
        endpoint = f"/v2/aggs/ticker/{symbol}/range/1/{timespan}/{start_date}/{end_date}"

        data = await self.fetcher._make_request(endpoint)

        if data and 'results' in data:
            # Convert to our format
            candles = []
            for bar in data['results']:
                candles.append({
                    'timestamp': datetime.fromtimestamp(bar['t'] / 1000),
                    'open': bar['o'],
                    'high': bar['h'],
                    'low': bar['l'],
                    'close': bar['c'],
                    'volume': bar['v']
                })
            return candles
        return []

    def _calculate_breakout_score(self, volume_surge: float, price_change: float,
                                  current_price: float, breakout_level: float) -> int:
        """Calculate breakout strength score"""
        score = 0

        # Volume confirmation (40%)
        if volume_surge >= 5.0:
            score += 40
        elif volume_surge >= 3.0:
            score += 35
        elif volume_surge >= 2.0:
            score += 30
        elif volume_surge >= 1.5:
            score += 25

        # Price momentum (30%)
        if abs(price_change) >= 5.0:
            score += 30
        elif abs(price_change) >= 3.0:
            score += 25
        elif abs(price_change) >= 2.0:
            score += 20
        elif abs(price_change) >= 1.0:
            score += 15

        # Distance from breakout level (30%)
        distance = abs((current_price - breakout_level) / breakout_level) * 100
        if distance >= 2.0:
            score += 30
        elif distance >= 1.0:
            score += 25
        elif distance >= 0.5:
            score += 20
        elif distance >= 0.1:
            score += 15

        return score

    async def _post_signal(self, breakout: Dict):
        """Post breakout signal to Discord"""
        color = 0x00FF00 if breakout['breakout_type'] == 'BULLISH' else 0xFF0000
        emoji = "🚀" if breakout['breakout_type'] == 'BULLISH' else "📉"

        direction = "UP" if breakout['breakout_type'] == 'BULLISH' else "DOWN"

        embed = self.create_embed(
            title=f"{emoji} BREAKOUT: {breakout['ticker']} {direction}",
            description=f"**{breakout['breakout_type']} Breakout** | Score: {breakout['breakout_score']}/100",
            color=color,
            fields=[
                {
                    "name": "💵 Current Price",
                    "value": f"${breakout['current_price']:.2f}",
                    "inline": True
                },
                {
                    "name": "📈 Change",
                    "value": f"{breakout['price_change_pct']:+.2f}%",
                    "inline": True
                },
                {
                    "name": "💪 Breakout Score",
                    "value": f"**{breakout['breakout_score']}/100**",
                    "inline": True
                },
                {
                    "name": "🎯 Breakout Level",
                    "value": f"${breakout['breakout_level']:.2f}",
                    "inline": True
                },
                {
                    "name": "📊 Resistance",
                    "value": f"${breakout['resistance']:.2f}",
                    "inline": True
                },
                {
                    "name": "📉 Support",
                    "value": f"${breakout['support']:.2f}",
                    "inline": True
                },
                {
                    "name": "📊 Volume Surge",
                    "value": f"**{breakout['volume_surge']:.2f}x**",
                    "inline": True
                },
                {
                    "name": "📊 Volume",
                    "value": f"{breakout['recent_volume']:,.0f}",
                    "inline": True
                },
                {
                    "name": "📊 Avg Volume",
                    "value": f"{breakout['avg_volume']:,.0f}",
                    "inline": True
                },
                {
                    "name": "🎯 Next Target",
                    "value": f"${breakout['next_target']:.2f}",
                    "inline": True
                },
                {
                    "name": "🛑 Stop Loss",
                    "value": f"${breakout['stop_loss']:.2f}",
                    "inline": True
                },
                {
                    "name": "📍 Pattern",
                    "value": f"{'Resistance' if breakout['breakout_type'] == 'BULLISH' else 'Support'} Breakout",
                    "inline": True
                },
                {
                    "name": "💡 Analysis",
                    "value": f"Strong {'upward' if breakout['breakout_type'] == 'BULLISH' else 'downward'} momentum with {breakout['volume_surge']:.1f}x volume confirmation",
                    "inline": False
                },
                {
                    "name": "",
                    "value": "Please always do your own due diligence on top of these trade ideas.",
                    "inline": False
                }
            ],
            footer="Breakouts Bot | Technical Breakout Scanner"
        )

        await self.post_to_discord(embed)
        logger.info(f"Posted Breakout: {breakout['ticker']} {breakout['breakout_type']} @ ${breakout['current_price']:.2f}")

    def _find_resistance_with_touches(self, highs: List[float]) -> tuple:
        """Find resistance level with multiple touches (pattern recognition)"""
        if not highs or len(highs) < 3:
            return (max(highs) if highs else 0, 0)

        max_high = max(highs)
        tolerance = max_high * 0.01  # 1% tolerance for "touching" resistance

        # Count how many times price came within tolerance of max high
        touches = sum(1 for h in highs if abs(h - max_high) <= tolerance)

        return (max_high, touches)

    def _find_support_with_touches(self, lows: List[float]) -> tuple:
        """Find support level with multiple touches (pattern recognition)"""
        if not lows or len(lows) < 3:
            return (min(lows) if lows else 0, 0)

        min_low = min(lows)
        tolerance = min_low * 0.01  # 1% tolerance for "touching" support

        # Count how many times price came within tolerance of min low
        touches = sum(1 for l in lows if abs(l - min_low) <= tolerance)

        return (min_low, touches)

    def _calculate_rsi(self, closes: List[float], period: int = 14) -> float:
        """Calculate Relative Strength Index (RSI)"""
        if len(closes) < period + 1:
            return 50.0  # Neutral if not enough data

        # Calculate price changes
        deltas = [closes[i] - closes[i-1] for i in range(1, len(closes))]

        # Separate gains and losses
        gains = [d if d > 0 else 0 for d in deltas[-period:]]
        losses = [-d if d < 0 else 0 for d in deltas[-period:]]

        # Calculate average gain and loss
        avg_gain = sum(gains) / period
        avg_loss = sum(losses) / period

        if avg_loss == 0:
            return 100.0  # All gains = overbought

        # Calculate RS and RSI
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))

        return rsi
