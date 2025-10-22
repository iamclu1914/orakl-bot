"""
Breakouts Bot - Kafka Consumer Version
Detects price breakouts with volume surges from Kafka aggregated-metrics topic
"""
import logging
import aiohttp
from datetime import datetime
from typing import Dict, List
from collections import defaultdict
from src.kafka_base import KafkaConsumerBase
from src.config import Config

logger = logging.getLogger(__name__)


class BreakoutsBotKafka(KafkaConsumerBase):
    """Real-time breakout detection from Kafka aggregated-metrics"""

    def __init__(self, webhook_url: str, watchlist: List[str]):
        super().__init__("Breakouts Bot Kafka", topics=["aggregated-metrics"])

        self.webhook_url = webhook_url
        self.watchlist = set(watchlist)

        # Thresholds
        self.MIN_VOLUME_SURGE = Config.BREAKOUT_MIN_VOLUME_SURGE  # 1.5x
        self.MIN_BREAKOUT_SCORE = Config.MIN_BREAKOUT_SCORE  # 65

        # Price tracking for breakout detection (rolling 20-bar window)
        self.price_history: Dict[str, List[Dict]] = defaultdict(list)
        self.volume_history: Dict[str, List[float]] = defaultdict(list)
        self.window_size = 20  # 20 bars for support/resistance

        # aiohttp session for Discord posting
        self.session = None

    async def process_message(self, data: Dict, topic: str):
        """Process aggregated bar message from Kafka"""
        try:
            # Extract bar data (1-minute OHLCV bars)
            ticker = data.get('ticker') or data.get('symbol') or data.get('s')
            if not ticker or ticker not in self.watchlist:
                return

            # OHLCV data
            open_price = data.get('open') or data.get('o', 0)
            high_price = data.get('high') or data.get('h', 0)
            low_price = data.get('low') or data.get('l', 0)
            close_price = data.get('close') or data.get('c', 0)
            volume = data.get('volume') or data.get('v', 0)
            timestamp = data.get('timestamp') or data.get('t', 0)

            # Skip if missing critical data
            if not all([open_price, high_price, low_price, close_price, volume]):
                return

            # Add to price history
            bar = {
                'open': open_price,
                'high': high_price,
                'low': low_price,
                'close': close_price,
                'volume': volume,
                'timestamp': timestamp
            }

            self.price_history[ticker].append(bar)
            self.volume_history[ticker].append(volume)

            # Keep only last 20 bars
            if len(self.price_history[ticker]) > self.window_size:
                self.price_history[ticker].pop(0)
            if len(self.volume_history[ticker]) > self.window_size:
                self.volume_history[ticker].pop(0)

            # Need at least 10 bars for analysis
            if len(self.price_history[ticker]) < 10:
                return

            # Calculate support/resistance levels
            recent_highs = [bar['high'] for bar in self.price_history[ticker][-10:]]
            recent_lows = [bar['low'] for bar in self.price_history[ticker][-10:]]

            resistance = max(recent_highs[:-1]) if len(recent_highs) > 1 else recent_highs[0]
            support = min(recent_lows[:-1]) if len(recent_lows) > 1 else recent_lows[0]

            # Calculate average volume (exclude current bar)
            avg_volume = sum(self.volume_history[ticker][:-1]) / len(self.volume_history[ticker][:-1])

            # Volume surge check
            volume_ratio = volume / avg_volume if avg_volume > 0 else 1
            if volume_ratio < self.MIN_VOLUME_SURGE:
                return  # Not enough volume surge

            # Breakout detection
            breakout_type = None
            breakout_level = None

            # Bullish breakout (close above resistance with volume)
            if close_price > resistance and close_price > open_price:
                breakout_type = 'BULLISH'
                breakout_level = resistance

            # Bearish breakdown (close below support with volume)
            elif close_price < support and close_price < open_price:
                breakout_type = 'BEARISH'
                breakout_level = support

            # No breakout detected
            if not breakout_type:
                return

            # Calculate price change
            price_change = ((close_price - open_price) / open_price) * 100

            # Calculate breakout score
            breakout_score = self._calculate_breakout_score(
                volume_ratio, abs(price_change), close_price, breakout_level
            )

            # Check minimum score
            if breakout_score < self.MIN_BREAKOUT_SCORE:
                return

            # Generate signal ID for deduplication
            signal_id = self.generate_signal_id(
                f"{ticker}_{breakout_type}",
                int(timestamp) if timestamp else int(datetime.now().timestamp() * 1000),
                'breakout'
            )

            if self.is_duplicate_signal(signal_id):
                return

            # Create breakout signal
            breakout = {
                'ticker': ticker,
                'type': breakout_type,
                'close_price': close_price,
                'breakout_level': breakout_level,
                'volume': volume,
                'avg_volume': avg_volume,
                'volume_ratio': volume_ratio,
                'price_change': price_change,
                'breakout_score': int(breakout_score),
                'resistance': resistance,
                'support': support
            }

            # Post to Discord
            await self._post_signal(breakout)

        except Exception as e:
            logger.error(f"[{self.bot_name}] Error processing message: {e}")
            logger.error(f"[{self.bot_name}] Message data: {data}")

    def _calculate_breakout_score(self, volume_ratio: float, price_change: float,
                                  close_price: float, breakout_level: float) -> int:
        """Calculate breakout score (0-100)"""
        score = 0

        # Volume surge (40%) - stronger is better
        if volume_ratio >= 5.0:
            score += 40
        elif volume_ratio >= 3.0:
            score += 35
        elif volume_ratio >= 2.0:
            score += 30
        elif volume_ratio >= 1.5:
            score += 25

        # Price change magnitude (30%)
        if abs(price_change) >= 5.0:
            score += 30
        elif abs(price_change) >= 3.0:
            score += 25
        elif abs(price_change) >= 2.0:
            score += 20
        elif abs(price_change) >= 1.0:
            score += 15

        # Breakout strength (30%) - distance from level
        if breakout_level > 0:
            breakout_strength = abs((close_price - breakout_level) / breakout_level) * 100
            if breakout_strength >= 2.0:
                score += 30
            elif breakout_strength >= 1.0:
                score += 25
            elif breakout_strength >= 0.5:
                score += 20
            else:
                score += 15

        return min(score, 100)

    async def _post_signal(self, breakout: Dict):
        """Post breakout signal to Discord"""
        try:
            if not self.session:
                self.session = aiohttp.ClientSession()

            # Color based on breakout type
            if breakout['type'] == 'BULLISH':
                color = 0x00FF00  # Green
                emoji = "📈"
                direction = "ABOVE"
            else:
                color = 0xFF0000  # Red
                emoji = "📉"
                direction = "BELOW"

            now = datetime.now()
            time_str = now.strftime('%I:%M %p')
            date_str = now.strftime('%m/%d/%y')

            embed = {
                "title": f"{emoji} {breakout['ticker']} - {breakout['type']} Breakout (KAFKA REAL-TIME)",
                "color": color,
                "fields": [
                    {"name": "Date", "value": date_str, "inline": True},
                    {"name": "Time", "value": time_str, "inline": True},
                    {"name": "Ticker", "value": breakout['ticker'], "inline": True},
                    {"name": "Price", "value": f"${breakout['close_price']:.2f}", "inline": True},
                    {"name": "Breakout Level", "value": f"${breakout['breakout_level']:.2f}", "inline": True},
                    {"name": "Change", "value": f"{breakout['price_change']:+.2f}%", "inline": True},
                    {"name": "Volume", "value": f"{int(breakout['volume']):,}", "inline": True},
                    {"name": "Avg Volume", "value": f"{int(breakout['avg_volume']):,}", "inline": True},
                    {"name": "Volume Surge", "value": f"{breakout['volume_ratio']:.1f}x", "inline": True},
                    {"name": "Support", "value": f"${breakout['support']:.2f}", "inline": True},
                    {"name": "Resistance", "value": f"${breakout['resistance']:.2f}", "inline": True},
                    {"name": "Algo Score", "value": str(int(breakout['breakout_score'])), "inline": True},
                    {"name": "", "value": "Please always do your own due diligence on top of these trade ideas.", "inline": False}
                ],
                "footer": {"text": "ORAKL Bot - Breakouts (Kafka Stream)"}
            }

            payload = {"embeds": [embed], "username": "ORAKL Breakouts"}

            async with self.session.post(self.webhook_url, json=payload) as response:
                success = response.status == 204

            if success:
                logger.info(f"{emoji} BREAKOUT (KAFKA): {breakout['ticker']} {breakout['type']} "
                          f"${breakout['close_price']:.2f} ({breakout['price_change']:+.2f}%) "
                          f"Vol:{breakout['volume_ratio']:.1f}x Score:{int(breakout['breakout_score'])}")

        except Exception as e:
            logger.error(f"[{self.bot_name}] Error posting signal: {e}")
