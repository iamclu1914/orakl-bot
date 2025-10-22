"""
Sweeps Bot - Kafka Consumer Version
Consumes $50K+ premium sweeps from Kafka processed-flows topic
"""
import logging
import aiohttp
from datetime import datetime
from typing import Dict, List
from src.kafka_base import KafkaConsumerBase
from src.options_analyzer import OptionsAnalyzer
from src.config import Config

logger = logging.getLogger(__name__)


class SweepsBotKafka(KafkaConsumerBase):
    """Real-time Sweeps detection from Kafka processed-flows"""

    def __init__(self, webhook_url: str, watchlist: List[str], analyzer: OptionsAnalyzer):
        super().__init__("Sweeps Bot Kafka", topics=["processed-flows"])

        self.webhook_url = webhook_url
        self.watchlist = set(watchlist)
        self.analyzer = analyzer

        # Thresholds
        self.MIN_PREMIUM = Config.SWEEPS_MIN_PREMIUM  # $50K
        self.MIN_SCORE = Config.MIN_SWEEP_SCORE  # 60

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
            premium = data.get('premiumValue', 0) or data.get('premium', 0) or data.get('total_premium', 0)
            volume = data.get('volume', 0) or data.get('total_volume', 0)

            # Skip if below sweep threshold
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

            # Flow classification
            flow_type = data.get('flow_type') or data.get('signal_type')
            is_sweep = data.get('isSweep', False) or data.get('is_sweep', False) or flow_type in ['SWEEP', 'GOLDEN_SWEEP', 'sweep', 'golden']

            # Only process sweeps
            if not is_sweep:
                return

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

            # Calculate score
            sweep_score = data.get('sweep_score') or data.get('score')
            if not sweep_score:
                sweep_score = self._calculate_sweep_score(
                    premium, volume, strike_distance, days_to_expiry
                )

            # Check minimum score
            if sweep_score < self.MIN_SCORE:
                return

            # Generate signal ID for deduplication
            signal_id = self.generate_signal_id(
                f"{ticker}_{option_type}_{strike}_{expiration}",
                int(timestamp) if timestamp else int(datetime.now().timestamp() * 1000),
                'sweep'
            )

            if self.is_duplicate_signal(signal_id):
                return

            # Create sweep signal
            sweep = {
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
                'sweep_score': int(sweep_score),
                'strike_distance': strike_distance
            }

            # Post to Discord
            await self._post_signal(sweep)

        except Exception as e:
            logger.error(f"[{self.bot_name}] Error processing message: {e}")
            logger.error(f"[{self.bot_name}] Message data: {data}")

    def _calculate_sweep_score(self, premium: float, volume: int,
                               strike_distance: float, dte: int) -> int:
        """Calculate sweep score (0-100)"""
        score = 0

        # Premium scoring (40%)
        if premium >= 500000:
            score += 40
        elif premium >= 250000:
            score += 35
        elif premium >= 100000:
            score += 30
        elif premium >= 50000:
            score += 25

        # Volume scoring (25%)
        if volume >= 1000:
            score += 25
        elif volume >= 500:
            score += 20
        elif volume >= 250:
            score += 15
        else:
            score += 10

        # Strike proximity (20%)
        if strike_distance <= 5:
            score += 20
        elif strike_distance <= 10:
            score += 15
        elif strike_distance <= 20:
            score += 10

        # DTE factor (15%)
        if 7 <= dte <= 45:
            score += 15
        elif dte <= 90:
            score += 10
        else:
            score += 5

        return min(score, 100)

    async def _post_signal(self, sweep: Dict):
        """Post sweep signal to Discord"""
        try:
            if not self.session:
                self.session = aiohttp.ClientSession()

            color = 0x00FF00  # Green

            now = datetime.now()
            time_str = now.strftime('%I:%M %p')
            date_str = now.strftime('%m/%d/%y')
            premium_k = sweep['premium'] / 1000
            details = f"{sweep['volume']:,} @ {sweep['avg_price']:.2f}"

            embed = {
                "title": f"💰 {sweep['ticker']} - Sweep (KAFKA REAL-TIME)",
                "color": color,
                "fields": [
                    {"name": "Date", "value": date_str, "inline": True},
                    {"name": "Time", "value": time_str, "inline": True},
                    {"name": "Ticker", "value": sweep['ticker'], "inline": True},
                    {"name": "Exp", "value": sweep['expiration'], "inline": True},
                    {"name": "Strike", "value": f"{sweep['strike']:.0f}", "inline": True},
                    {"name": "C/P", "value": sweep['type'] + "S", "inline": True},
                    {"name": "Spot", "value": f"{sweep['current_price']:.2f}", "inline": True},
                    {"name": "Details", "value": details, "inline": True},
                    {"name": "Type", "value": "SWEEP", "inline": True},
                    {"name": "Prem", "value": f"${premium_k:.1f}K", "inline": True},
                    {"name": "Algo Score", "value": str(int(sweep['sweep_score'])), "inline": True},
                    {"name": "Source", "value": "Kafka", "inline": True},
                    {"name": "", "value": "Please always do your own due diligence on top of these trade ideas.", "inline": False}
                ],
                "footer": {"text": "ORAKL Bot - Sweeps (Kafka Stream)"}
            }

            payload = {"embeds": [embed], "username": "ORAKL Sweeps"}

            async with self.session.post(self.webhook_url, json=payload) as response:
                success = response.status == 204

            if success:
                logger.info(f"🚨 SWEEP (KAFKA): {sweep['ticker']} {sweep['type']} "
                          f"${sweep['strike']} Premium:${premium_k:.1f}K "
                          f"Score:{int(sweep['sweep_score'])}")

        except Exception as e:
            logger.error(f"[{self.bot_name}] Error posting signal: {e}")
