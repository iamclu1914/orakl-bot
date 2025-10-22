"""
ORAKL Flow Bot - Kafka Consumer Version
Consumes general flow analysis from Kafka processed-flows topic
"""
import logging
import aiohttp
from datetime import datetime
from typing import Dict, List
from src.kafka_base import KafkaConsumerBase
from src.options_analyzer import OptionsAnalyzer
from src.config import Config

logger = logging.getLogger(__name__)


class OraklFlowBotKafka(KafkaConsumerBase):
    """Real-time flow analysis from Kafka processed-flows"""

    def __init__(self, webhook_url: str, watchlist: List[str], analyzer: OptionsAnalyzer):
        super().__init__("ORAKL Flow Bot Kafka", topics=["processed-flows"])

        self.webhook_url = webhook_url
        self.watchlist = set(watchlist)
        self.analyzer = analyzer

        # Thresholds
        self.MIN_PREMIUM = Config.MIN_PREMIUM  # $10K
        self.MIN_VOLUME = 100

        # aiohttp session for Discord posting
        self.session = None

    async def process_message(self, data: Dict, topic: str):
        """Process pre-aggregated flow message from Kafka"""
        try:
            # Extract flow data
            ticker = data.get('ticker') or data.get('symbol')
            if not ticker:
                return

            # Flow metrics
            premium = data.get('premiumValue', 0) or data.get('premium', 0) or data.get('total_premium', 0)
            volume = data.get('volume', 0) or data.get('total_volume', 0)

            # Skip if below thresholds
            if premium < self.MIN_PREMIUM or volume < self.MIN_VOLUME:
                return

            # Contract details
            option_type = data.get('type') or data.get('option_type') or data.get('call_put')
            if option_type:
                option_type = option_type.upper()
                if option_type not in ['CALL', 'PUT', 'CALLS', 'PUTS']:
                    return
                option_type = 'CALL' if 'CALL' in option_type else 'PUT'
            else:
                return

            strike = data.get('strike', 0) or data.get('strike_price', 0)
            expiration = data.get('exp') or data.get('expiry') or data.get('expiration') or data.get('exp_date')
            current_price = data.get('spot_price', 0) or data.get('underlying_price', 0) or data.get('current_price', 0)

            # Flow metadata
            num_fills = data.get('num_fills', 1) or data.get('trade_count', 1)
            avg_price = data.get('avg_price', 0) or (premium / (volume * 100) if volume > 0 else 0)
            timestamp = data.get('timestamp', 0) or data.get('t', 0)

            # Flow direction
            flow_direction = data.get('flow_direction') or data.get('direction')
            sentiment = data.get('sentiment')

            # Calculate days to expiry
            if expiration:
                if isinstance(expiration, str):
                    if len(expiration) == 8:
                        exp_date = datetime.strptime(expiration, '%Y%m%d')
                    elif len(expiration) == 6:
                        exp_date = datetime.strptime(f"20{expiration}", '%Y%m%d')
                    else:
                        exp_date = datetime.fromisoformat(expiration.replace('Z', '+00:00'))
                else:
                    exp_date = datetime.fromtimestamp(expiration / 1000 if expiration > 1e10 else expiration)

                days_to_expiry = (exp_date - datetime.now()).days
            else:
                days_to_expiry = 30

            # Calculate metrics
            if current_price > 0 and strike > 0:
                strike_distance = abs((strike - current_price) / current_price) * 100
                prob_itm = self.analyzer.calculate_probability_itm(
                    option_type, strike, current_price, days_to_expiry
                )
            else:
                strike_distance = 5.0
                prob_itm = 0.5

            # Determine flow sentiment
            if not flow_direction:
                flow_direction = 'BULLISH' if option_type == 'CALL' else 'BEARISH'

            # Generate signal ID for deduplication
            signal_id = self.generate_signal_id(
                f"{ticker}_{option_type}_{strike}_{expiration}",
                int(timestamp) if timestamp else int(datetime.now().timestamp() * 1000),
                'flow'
            )

            if self.is_duplicate_signal(signal_id):
                return

            # Create flow signal
            flow = {
                'ticker': ticker,
                'type': option_type,
                'strike': strike,
                'expiration': expiration,
                'current_price': current_price,
                'days_to_expiry': days_to_expiry,
                'premium': premium,
                'volume': volume,
                'num_fills': num_fills,
                'avg_price': avg_price,
                'probability_itm': prob_itm,
                'strike_distance': strike_distance,
                'flow_direction': flow_direction,
                'sentiment': sentiment
            }

            # Post to Discord
            await self._post_signal(flow)

        except Exception as e:
            logger.error(f"[{self.bot_name}] Error processing message: {e}")
            logger.error(f"[{self.bot_name}] Message data: {data}")

    async def _post_signal(self, flow: Dict):
        """Post flow signal to Discord"""
        try:
            if not self.session:
                self.session = aiohttp.ClientSession()

            # Color based on flow direction
            if flow['flow_direction'] == 'BULLISH':
                color = 0x00FF00  # Green
                emoji = "📈"
            else:
                color = 0xFF0000  # Red
                emoji = "📉"

            now = datetime.now()
            time_str = now.strftime('%I:%M %p')
            date_str = now.strftime('%m/%d/%y')
            premium_k = flow['premium'] / 1000
            details = f"{flow['volume']:,} @ {flow['avg_price']:.2f}"

            embed = {
                "title": f"{emoji} {flow['ticker']} - {flow['flow_direction']} Flow (KAFKA REAL-TIME)",
                "color": color,
                "fields": [
                    {"name": "Date", "value": date_str, "inline": True},
                    {"name": "Time", "value": time_str, "inline": True},
                    {"name": "Ticker", "value": flow['ticker'], "inline": True},
                    {"name": "Exp", "value": flow['expiration'], "inline": True},
                    {"name": "Strike", "value": f"{flow['strike']:.0f}", "inline": True},
                    {"name": "C/P", "value": flow['type'] + "S", "inline": True},
                    {"name": "Spot", "value": f"{flow['current_price']:.2f}", "inline": True},
                    {"name": "Details", "value": details, "inline": True},
                    {"name": "Direction", "value": flow['flow_direction'], "inline": True},
                    {"name": "Prem", "value": f"${premium_k:.1f}K", "inline": True},
                    {"name": "Prob ITM", "value": f"{flow['probability_itm']*100:.0f}%", "inline": True},
                    {"name": "Source", "value": "Kafka", "inline": True},
                    {"name": "", "value": "Please always do your own due diligence on top of these trade ideas.", "inline": False}
                ],
                "footer": {"text": "ORAKL Bot - Flow Analysis (Kafka Stream)"}
            }

            payload = {"embeds": [embed], "username": "ORAKL Flow"}

            async with self.session.post(self.webhook_url, json=payload) as response:
                success = response.status == 204

            if success:
                logger.info(f"{emoji} FLOW (KAFKA): {flow['ticker']} {flow['type']} "
                          f"${flow['strike']} Premium:${premium_k:.1f}K "
                          f"{flow['flow_direction']}")

        except Exception as e:
            logger.error(f"[{self.bot_name}] Error posting signal: {e}")
