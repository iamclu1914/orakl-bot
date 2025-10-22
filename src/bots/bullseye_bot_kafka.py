"""
Bullseye Bot - Kafka Consumer Version
Consumes ATM high-probability options from Kafka processed-flows topic
"""
import logging
import aiohttp
from datetime import datetime
from typing import Dict, List
from src.kafka_base import KafkaConsumerBase
from src.options_analyzer import OptionsAnalyzer
from src.config import Config

logger = logging.getLogger(__name__)


class BullseyeBotKafka(KafkaConsumerBase):
    """Real-time Bullseye (ATM) detection from Kafka processed-flows"""

    def __init__(self, webhook_url: str, watchlist: List[str], analyzer: OptionsAnalyzer):
        super().__init__("Bullseye Bot Kafka", topics=["processed-flows"])

        self.webhook_url = webhook_url
        self.watchlist = set(watchlist)
        self.analyzer = analyzer

        # Thresholds
        self.MIN_PREMIUM = Config.BULLSEYE_MIN_PREMIUM  # $5K
        self.MIN_SCORE = Config.MIN_BULLSEYE_SCORE  # 60
        self.MAX_STRIKE_DISTANCE = 5.0  # ATM trades only

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

            # Skip if below threshold
            if premium < self.MIN_PREMIUM:
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
                return  # Need valid prices for Bullseye

            # ATM check - must be close to current price
            if strike_distance > self.MAX_STRIKE_DISTANCE:
                return  # Not ATM

            # Calculate score
            bullseye_score = data.get('bullseye_score') or data.get('score')
            if not bullseye_score:
                bullseye_score = self._calculate_bullseye_score(
                    premium, volume, strike_distance, days_to_expiry, prob_itm
                )

            # Check minimum score
            if bullseye_score < self.MIN_SCORE:
                return

            # Generate signal ID for deduplication
            signal_id = self.generate_signal_id(
                f"{ticker}_{option_type}_{strike}_{expiration}",
                int(timestamp) if timestamp else int(datetime.now().timestamp() * 1000),
                'bullseye'
            )

            if self.is_duplicate_signal(signal_id):
                return

            # Create bullseye signal
            bullseye = {
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
                'bullseye_score': int(bullseye_score),
                'strike_distance': strike_distance
            }

            # Post to Discord
            await self._post_signal(bullseye)

        except Exception as e:
            logger.error(f"[{self.bot_name}] Error processing message: {e}")
            logger.error(f"[{self.bot_name}] Message data: {data}")

    def _calculate_bullseye_score(self, premium: float, volume: int,
                                  strike_distance: float, dte: int, prob_itm: float) -> int:
        """Calculate bullseye score (0-100) - prioritizes ATM high probability"""
        score = 0

        # ATM proximity (30%) - closer is better
        if strike_distance <= 1:
            score += 30
        elif strike_distance <= 2:
            score += 25
        elif strike_distance <= 3:
            score += 20
        elif strike_distance <= 5:
            score += 15

        # Probability ITM (30%)
        if prob_itm >= 0.6:
            score += 30
        elif prob_itm >= 0.5:
            score += 25
        elif prob_itm >= 0.45:
            score += 20

        # Premium scoring (20%)
        if premium >= 50000:
            score += 20
        elif premium >= 25000:
            score += 17
        elif premium >= 10000:
            score += 14
        elif premium >= 5000:
            score += 10

        # DTE factor (20%) - prefer 30-60 days
        if 30 <= dte <= 60:
            score += 20
        elif 15 <= dte <= 90:
            score += 15
        elif dte <= 120:
            score += 10
        else:
            score += 5

        return min(score, 100)

    async def _post_signal(self, bullseye: Dict):
        """Post bullseye signal to Discord"""
        try:
            if not self.session:
                self.session = aiohttp.ClientSession()

            color = 0xFF0000  # Red

            now = datetime.now()
            time_str = now.strftime('%I:%M %p')
            date_str = now.strftime('%m/%d/%y')
            premium_k = bullseye['premium'] / 1000
            details = f"{bullseye['volume']:,} @ {bullseye['avg_price']:.2f}"

            embed = {
                "title": f"🎯 {bullseye['ticker']} - Bullseye ATM (KAFKA REAL-TIME)",
                "color": color,
                "fields": [
                    {"name": "Date", "value": date_str, "inline": True},
                    {"name": "Time", "value": time_str, "inline": True},
                    {"name": "Ticker", "value": bullseye['ticker'], "inline": True},
                    {"name": "Exp", "value": bullseye['expiration'], "inline": True},
                    {"name": "Strike", "value": f"{bullseye['strike']:.0f}", "inline": True},
                    {"name": "C/P", "value": bullseye['type'] + "S", "inline": True},
                    {"name": "Spot", "value": f"{bullseye['current_price']:.2f}", "inline": True},
                    {"name": "Details", "value": details, "inline": True},
                    {"name": "Type", "value": "ATM", "inline": True},
                    {"name": "Prem", "value": f"${premium_k:.1f}K", "inline": True},
                    {"name": "Algo Score", "value": str(int(bullseye['bullseye_score'])), "inline": True},
                    {"name": "Prob ITM", "value": f"{bullseye['probability_itm']*100:.0f}%", "inline": True},
                    {"name": "", "value": "Please always do your own due diligence on top of these trade ideas.", "inline": False}
                ],
                "footer": {"text": "ORAKL Bot - Bullseye (Kafka Stream)"}
            }

            payload = {"embeds": [embed], "username": "ORAKL Bullseye"}

            async with self.session.post(self.webhook_url, json=payload) as response:
                success = response.status == 204

            if success:
                logger.info(f"🎯 BULLSEYE (KAFKA): {bullseye['ticker']} {bullseye['type']} "
                          f"${bullseye['strike']} Premium:${premium_k:.1f}K "
                          f"Score:{int(bullseye['bullseye_score'])} Prob:{bullseye['probability_itm']*100:.0f}%")

        except Exception as e:
            logger.error(f"[{self.bot_name}] Error posting signal: {e}")
