"""
Darkpool Bot - Kafka Consumer Version
Detects large block trades from Kafka aggregated-metrics topic
"""
import logging
import aiohttp
from datetime import datetime
from typing import Dict, List
from collections import defaultdict
from src.kafka_base import KafkaConsumerBase
from src.config import Config

logger = logging.getLogger(__name__)


class DarkpoolBotKafka(KafkaConsumerBase):
    """Real-time darkpool/block trade detection from Kafka aggregated-metrics"""

    def __init__(self, webhook_url: str, watchlist: List[str]):
        super().__init__("Darkpool Bot Kafka", topics=["aggregated-metrics"])

        self.webhook_url = webhook_url
        self.watchlist = set(watchlist)

        # Thresholds
        self.MIN_BLOCK_SIZE = Config.DARKPOOL_MIN_BLOCK_SIZE  # 10K shares
        self.MIN_DARKPOOL_SCORE = Config.MIN_DARKPOOL_SCORE  # 60

        # Volume tracking for unusual activity detection
        self.volume_history: Dict[str, List[float]] = defaultdict(list)
        self.window_size = 20  # 20 bars for average volume

        # aiohttp session for Discord posting
        self.session = None

    async def process_message(self, data: Dict, topic: str):
        """Process aggregated bar message from Kafka"""
        try:
            # Extract bar data
            ticker = data.get('ticker') or data.get('symbol') or data.get('s')
            if not ticker or ticker not in self.watchlist:
                return

            # Volume data
            volume = data.get('volume') or data.get('v', 0)
            close_price = data.get('close') or data.get('c', 0)
            timestamp = data.get('timestamp') or data.get('t', 0)

            # Skip if missing critical data
            if not volume or not close_price:
                return

            # Check if this is a block trade
            if volume < self.MIN_BLOCK_SIZE:
                # Add to history for average calculation
                self.volume_history[ticker].append(volume)
                if len(self.volume_history[ticker]) > self.window_size:
                    self.volume_history[ticker].pop(0)
                return

            # Calculate average volume
            if len(self.volume_history[ticker]) > 5:
                avg_volume = sum(self.volume_history[ticker]) / len(self.volume_history[ticker])
            else:
                avg_volume = volume  # Not enough history

            # Add to history
            self.volume_history[ticker].append(volume)
            if len(self.volume_history[ticker]) > self.window_size:
                self.volume_history[ticker].pop(0)

            # Calculate metrics
            volume_ratio = volume / avg_volume if avg_volume > 0 else 1
            notional_value = volume * close_price

            # Calculate darkpool score
            darkpool_score = self._calculate_darkpool_score(
                volume, avg_volume, volume_ratio, notional_value
            )

            # Check minimum score
            if darkpool_score < self.MIN_DARKPOOL_SCORE:
                return

            # Generate signal ID for deduplication
            signal_id = self.generate_signal_id(
                f"{ticker}_block",
                int(timestamp) if timestamp else int(datetime.now().timestamp() * 1000),
                'darkpool'
            )

            if self.is_duplicate_signal(signal_id):
                return

            # Create darkpool signal
            darkpool = {
                'ticker': ticker,
                'price': close_price,
                'volume': volume,
                'avg_volume': avg_volume,
                'volume_ratio': volume_ratio,
                'notional_value': notional_value,
                'darkpool_score': int(darkpool_score)
            }

            # Post to Discord
            await self._post_signal(darkpool)

        except Exception as e:
            logger.error(f"[{self.bot_name}] Error processing message: {e}")
            logger.error(f"[{self.bot_name}] Message data: {data}")

    def _calculate_darkpool_score(self, volume: float, avg_volume: float,
                                  volume_ratio: float, notional_value: float) -> int:
        """Calculate darkpool score (0-100)"""
        score = 0

        # Block size (40%)
        if volume >= 100000:
            score += 40
        elif volume >= 50000:
            score += 35
        elif volume >= 25000:
            score += 30
        elif volume >= 10000:
            score += 25

        # Volume ratio (30%) - how unusual compared to average
        if volume_ratio >= 10.0:
            score += 30
        elif volume_ratio >= 5.0:
            score += 25
        elif volume_ratio >= 3.0:
            score += 20
        elif volume_ratio >= 2.0:
            score += 15

        # Notional value (30%)
        if notional_value >= 10000000:  # $10M+
            score += 30
        elif notional_value >= 5000000:  # $5M+
            score += 25
        elif notional_value >= 1000000:  # $1M+
            score += 20
        elif notional_value >= 500000:  # $500K+
            score += 15

        return min(score, 100)

    async def _post_signal(self, darkpool: Dict):
        """Post darkpool signal to Discord"""
        try:
            if not self.session:
                self.session = aiohttp.ClientSession()

            color = 0x9400D3  # Dark Violet

            now = datetime.now()
            time_str = now.strftime('%I:%M %p')
            date_str = now.strftime('%m/%d/%y')
            notional_m = darkpool['notional_value'] / 1000000

            embed = {
                "title": f"🌑 {darkpool['ticker']} - Darkpool Block Trade (KAFKA REAL-TIME)",
                "color": color,
                "fields": [
                    {"name": "Date", "value": date_str, "inline": True},
                    {"name": "Time", "value": time_str, "inline": True},
                    {"name": "Ticker", "value": darkpool['ticker'], "inline": True},
                    {"name": "Price", "value": f"${darkpool['price']:.2f}", "inline": True},
                    {"name": "Block Size", "value": f"{int(darkpool['volume']):,}", "inline": True},
                    {"name": "Avg Volume", "value": f"{int(darkpool['avg_volume']):,}", "inline": True},
                    {"name": "Volume Ratio", "value": f"{darkpool['volume_ratio']:.1f}x", "inline": True},
                    {"name": "Notional", "value": f"${notional_m:.2f}M", "inline": True},
                    {"name": "Type", "value": "BLOCK", "inline": True},
                    {"name": "Algo Score", "value": str(int(darkpool['darkpool_score'])), "inline": True},
                    {"name": "Source", "value": "Kafka", "inline": True},
                    {"name": "", "value": "", "inline": True},
                    {"name": "", "value": "Please always do your own due diligence on top of these trade ideas.", "inline": False}
                ],
                "footer": {"text": "ORAKL Bot - Darkpool (Kafka Stream)"}
            }

            payload = {"embeds": [embed], "username": "ORAKL Darkpool"}

            async with self.session.post(self.webhook_url, json=payload) as response:
                success = response.status == 204

            if success:
                logger.info(f"🌑 DARKPOOL (KAFKA): {darkpool['ticker']} "
                          f"Block:{int(darkpool['volume']):,} "
                          f"${darkpool['price']:.2f} "
                          f"Notional:${notional_m:.2f}M "
                          f"Score:{int(darkpool['darkpool_score'])}")

        except Exception as e:
            logger.error(f"[{self.bot_name}] Error posting signal: {e}")
