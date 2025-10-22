"""
Scalps Bot - Kafka Consumer Version
Consumes short-term scalping opportunities from Kafka processed-flows topic
"""
import logging
import aiohttp
from datetime import datetime
from typing import Dict, List
from src.kafka_base import KafkaConsumerBase
from src.options_analyzer import OptionsAnalyzer
from src.config import Config

logger = logging.getLogger(__name__)


class ScalpsBotKafka(KafkaConsumerBase):
    """Real-time Scalps detection from Kafka processed-flows"""

    def __init__(self, webhook_url: str, watchlist: List[str], analyzer: OptionsAnalyzer):
        super().__init__("Scalps Bot Kafka", topics=["processed-flows"])

        self.webhook_url = webhook_url
        self.watchlist = set(watchlist)
        self.analyzer = analyzer

        # Thresholds
        self.MIN_PREMIUM = Config.SCALPS_MIN_PREMIUM  # $2K
        self.MIN_SCORE = Config.MIN_SCALP_SCORE  # 65
        self.MAX_DTE = 7  # Short-term only

        # aiohttp session for Discord posting
        self.session = None

    async def process_message(self, data: Dict, topic: str):
        """Process pre-aggregated flow message from Kafka"""
        try:
            # Extract flow data
            ticker = data.get('ticker') or data.get('symbol')
            if not ticker or ticker not in self.watchlist:
                return

            # Flow metrics
            premium = data.get('premium', 0) or data.get('total_premium', 0)
            volume = data.get('volume', 0) or data.get('total_volume', 0)

            # Skip if below threshold
            if premium < self.MIN_PREMIUM:
                return

            # Contract details
            option_type = data.get('option_type') or data.get('type') or data.get('call_put')
            if option_type:
                option_type = option_type.upper()
                if option_type not in ['CALL', 'PUT', 'CALLS', 'PUTS']:
                    return
                option_type = 'CALL' if 'CALL' in option_type else 'PUT'
            else:
                return

            strike = data.get('strike', 0) or data.get('strike_price', 0)
            expiration = data.get('expiration') or data.get('exp_date') or data.get('expiry')
            current_price = data.get('spot_price', 0) or data.get('underlying_price', 0) or data.get('current_price', 0)

            # Flow metadata
            num_fills = data.get('num_fills', 1) or data.get('trade_count', 1)
            avg_price = data.get('avg_price', 0) or (premium / (volume * 100) if volume > 0 else 0)
            timestamp = data.get('timestamp', 0) or data.get('t', 0)

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
                return  # Need valid expiration for scalps

            # Short-term check
            if days_to_expiry > self.MAX_DTE:
                return  # Not a scalp trade

            # Calculate metrics
            if current_price > 0 and strike > 0:
                strike_distance = abs((strike - current_price) / current_price) * 100
                prob_itm = self.analyzer.calculate_probability_itm(
                    option_type, strike, current_price, days_to_expiry
                )
            else:
                strike_distance = 5.0
                prob_itm = 0.5

            # Calculate score
            scalp_score = data.get('scalp_score') or data.get('score')
            if not scalp_score:
                scalp_score = self._calculate_scalp_score(
                    premium, volume, strike_distance, days_to_expiry, prob_itm
                )

            # Check minimum score
            if scalp_score < self.MIN_SCORE:
                return

            # Generate signal ID for deduplication
            signal_id = self.generate_signal_id(
                f"{ticker}_{option_type}_{strike}_{expiration}",
                int(timestamp) if timestamp else int(datetime.now().timestamp() * 1000),
                'scalp'
            )

            if self.is_duplicate_signal(signal_id):
                return

            # Create scalp signal
            scalp = {
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
                'scalp_score': int(scalp_score),
                'strike_distance': strike_distance
            }

            # Post to Discord
            await self._post_signal(scalp)

        except Exception as e:
            logger.error(f"[{self.bot_name}] Error processing message: {e}")
            logger.error(f"[{self.bot_name}] Message data: {data}")

    def _calculate_scalp_score(self, premium: float, volume: int,
                               strike_distance: float, dte: int, prob_itm: float) -> int:
        """Calculate scalp score (0-100) - prioritizes short-term momentum"""
        score = 0

        # DTE factor (35%) - shorter is better for scalps
        if dte == 0:
            score += 35
        elif dte == 1:
            score += 32
        elif dte <= 3:
            score += 28
        elif dte <= 5:
            score += 23
        elif dte <= 7:
            score += 18

        # Volume scoring (25%) - need momentum
        if volume >= 500:
            score += 25
        elif volume >= 250:
            score += 20
        elif volume >= 100:
            score += 15
        elif volume >= 50:
            score += 10

        # Strike proximity (20%)
        if strike_distance <= 3:
            score += 20
        elif strike_distance <= 5:
            score += 15
        elif strike_distance <= 10:
            score += 10

        # Probability ITM (20%)
        if prob_itm >= 0.55:
            score += 20
        elif prob_itm >= 0.45:
            score += 15
        elif prob_itm >= 0.35:
            score += 10

        return min(score, 100)

    async def _post_signal(self, scalp: Dict):
        """Post scalp signal to Discord"""
        try:
            if not self.session:
                self.session = aiohttp.ClientSession()

            color = 0xFFA500  # Orange

            now = datetime.now()
            time_str = now.strftime('%I:%M %p')
            date_str = now.strftime('%m/%d/%y')
            premium_k = scalp['premium'] / 1000
            details = f"{scalp['volume']:,} @ {scalp['avg_price']:.2f}"

            embed = {
                "title": f"⚡ {scalp['ticker']} - Scalp ({scalp['days_to_expiry']}DTE) (KAFKA REAL-TIME)",
                "color": color,
                "fields": [
                    {"name": "Date", "value": date_str, "inline": True},
                    {"name": "Time", "value": time_str, "inline": True},
                    {"name": "Ticker", "value": scalp['ticker'], "inline": True},
                    {"name": "Exp", "value": scalp['expiration'], "inline": True},
                    {"name": "Strike", "value": f"{scalp['strike']:.0f}", "inline": True},
                    {"name": "C/P", "value": scalp['type'] + "S", "inline": True},
                    {"name": "Spot", "value": f"{scalp['current_price']:.2f}", "inline": True},
                    {"name": "Details", "value": details, "inline": True},
                    {"name": "Type", "value": "SCALP", "inline": True},
                    {"name": "Prem", "value": f"${premium_k:.1f}K", "inline": True},
                    {"name": "Algo Score", "value": str(int(scalp['scalp_score'])), "inline": True},
                    {"name": "DTE", "value": str(scalp['days_to_expiry']), "inline": True},
                    {"name": "", "value": "Please always do your own due diligence on top of these trade ideas.", "inline": False}
                ],
                "footer": {"text": "ORAKL Bot - Scalps (Kafka Stream)"}
            }

            payload = {"embeds": [embed], "username": "ORAKL Scalps"}

            async with self.session.post(self.webhook_url, json=payload) as response:
                success = response.status == 204

            if success:
                logger.info(f"⚡ SCALP (KAFKA): {scalp['ticker']} {scalp['type']} "
                          f"${scalp['strike']} Premium:${premium_k:.1f}K "
                          f"Score:{int(scalp['scalp_score'])} DTE:{scalp['days_to_expiry']}")

        except Exception as e:
            logger.error(f"[{self.bot_name}] Error posting signal: {e}")
