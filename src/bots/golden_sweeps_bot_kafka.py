"""
Golden Sweeps Bot - Kafka Consumer Version
Consumes $1M+ premium sweeps from Kafka raw-trades topic
"""
import logging
import aiohttp
from datetime import datetime, timedelta
from typing import Dict, List
from src.kafka_base import KafkaConsumerBase
from src.options_analyzer import OptionsAnalyzer
from src.config import Config

logger = logging.getLogger(__name__)


class GoldenSweepsBotKafka(KafkaConsumerBase):
    """Real-time Golden Sweeps detection from Kafka"""

    def __init__(self, webhook_url: str, watchlist: List[str], analyzer: OptionsAnalyzer):
        super().__init__("Golden Sweeps Bot Kafka", topics=["processed-flows"])

        self.webhook_url = webhook_url
        self.watchlist = set(watchlist)  # Convert to set for O(1) lookup
        self.analyzer = analyzer

        # Thresholds
        self.MIN_PREMIUM = Config.GOLDEN_MIN_PREMIUM  # $1M
        self.MIN_SCORE = Config.MIN_GOLDEN_SCORE  # 60

        # Trade aggregation windows (group trades within 60 seconds)
        self.trade_windows: Dict[str, List[Dict]] = {}
        self.window_size = 60  # seconds

        # aiohttp session for Discord posting
        self.session = None

    async def process_message(self, data: Dict, topic: str):
        """Process pre-aggregated flow message from Kafka processed-flows topic"""
        try:
            # Extract flow data (adjust keys based on your actual schema)
            ticker = data.get('ticker') or data.get('symbol')
            if not ticker or ticker not in self.watchlist:
                return  # Not in watchlist

            # Flow metrics (pre-calculated in your pipeline)
            premium = data.get('premium', 0) or data.get('total_premium', 0)
            volume = data.get('volume', 0) or data.get('total_volume', 0)

            # Skip if below golden threshold
            if premium < self.MIN_PREMIUM:
                return

            # Contract details
            option_type = data.get('option_type') or data.get('type') or data.get('call_put')
            if option_type:
                option_type = option_type.upper()
                if option_type not in ['CALL', 'PUT', 'CALLS', 'PUTS']:
                    return  # Skip non-options flows
                # Normalize to CALL/PUT
                option_type = 'CALL' if 'CALL' in option_type else 'PUT'
            else:
                return  # No option type

            strike = data.get('strike', 0) or data.get('strike_price', 0)
            expiration = data.get('expiration') or data.get('exp_date') or data.get('expiry')
            current_price = data.get('spot_price', 0) or data.get('underlying_price', 0) or data.get('current_price', 0)

            # Flow metadata
            num_fills = data.get('num_fills', 1) or data.get('trade_count', 1)
            avg_price = data.get('avg_price', 0) or (premium / (volume * 100) if volume > 0 else 0)
            timestamp = data.get('timestamp', 0) or data.get('t', 0)

            # Flow classification
            flow_type = data.get('flow_type') or data.get('signal_type')
            is_sweep = data.get('is_sweep', False) or flow_type in ['SWEEP', 'GOLDEN_SWEEP', 'sweep', 'golden']

            # Only process sweeps for Golden Sweeps bot
            if not is_sweep:
                return

            # Calculate days to expiry
            if expiration:
                # Handle different date formats
                if isinstance(expiration, str):
                    if len(expiration) == 8:  # YYYYMMDD
                        exp_date = datetime.strptime(expiration, '%Y%m%d')
                    elif len(expiration) == 6:  # YYMMDD
                        exp_date = datetime.strptime(f"20{expiration}", '%Y%m%d')
                    else:
                        exp_date = datetime.fromisoformat(expiration.replace('Z', '+00:00'))
                else:
                    exp_date = datetime.fromtimestamp(expiration / 1000 if expiration > 1e10 else expiration)

                days_to_expiry = (exp_date - datetime.now()).days
            else:
                days_to_expiry = 30  # Default estimate

            # Use pre-calculated metrics or calculate if needed
            if current_price > 0 and strike > 0:
                strike_distance = abs((strike - current_price) / current_price) * 100

                # Calculate probability ITM
                prob_itm = self.analyzer.calculate_probability_itm(
                    option_type, strike, current_price, days_to_expiry
                )
            else:
                strike_distance = 5.0  # Default estimate
                prob_itm = 0.5  # Default estimate

            # Calculate or use pre-calculated golden score
            golden_score = data.get('golden_score') or data.get('score')
            if not golden_score:
                golden_score = self._calculate_golden_score(
                    premium, volume, strike_distance, days_to_expiry
                )

            # Check minimum score
            if golden_score < self.MIN_SCORE:
                return

            # Generate signal ID for deduplication
            signal_id = self.generate_signal_id(
                f"{ticker}_{option_type}_{strike}_{expiration}",
                int(timestamp) if timestamp else int(datetime.now().timestamp() * 1000),
                'golden'
            )

            # Check if already alerted
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
                'golden_score': int(golden_score),
                'strike_distance': strike_distance
            }

            # Post to Discord
            await self._post_signal(sweep)

        except Exception as e:
            logger.error(f"[{self.bot_name}] Error processing message: {e}")
            logger.error(f"[{self.bot_name}] Message data: {data}")

    def _extract_ticker(self, symbol: str) -> str:
        """Extract underlying ticker from options symbol (O:SPY250117C00600000 -> SPY)"""
        try:
            # Remove 'O:' prefix
            symbol = symbol.replace('O:', '')

            # Find where date starts (6 digits YYMMDD)
            for i in range(len(symbol)):
                if symbol[i:i+6].isdigit() and len(symbol[i:i+6]) == 6:
                    return symbol[:i]

            return None
        except:
            return None

    def _parse_contract(self, symbol: str) -> tuple:
        """Parse options contract symbol (O:SPY250117C00600000 -> CALL, 600.0, 20250117)"""
        try:
            symbol = symbol.replace('O:', '')

            # Find date start
            date_start = None
            for i in range(len(symbol)):
                if symbol[i:i+6].isdigit() and len(symbol[i:i+6]) == 6:
                    date_start = i
                    break

            if date_start is None:
                return None, None, None

            date_str = symbol[date_start:date_start+6]
            option_type = symbol[date_start+6]
            strike_str = symbol[date_start+7:]

            expiration = f"20{date_str}"
            strike = int(strike_str) / 1000
            opt_type = 'CALL' if option_type == 'C' else 'PUT'

            return opt_type, strike, expiration

        except Exception as e:
            logger.error(f"Error parsing contract {symbol}: {e}")
            return None, None, None

    def _calculate_golden_score(self, premium: float, volume: int,
                                strike_distance: float, dte: int) -> int:
        """Calculate golden sweep score (0-100)"""
        score = 0

        # Premium scoring (50%)
        if premium >= 10000000:
            score += 50
        elif premium >= 5000000:
            score += 45
        elif premium >= 2500000:
            score += 40
        elif premium >= 1000000:
            score += 35

        # Volume scoring (20%)
        if volume >= 2000:
            score += 20
        elif volume >= 1000:
            score += 17
        elif volume >= 500:
            score += 14
        else:
            score += 10

        # Strike proximity (15%)
        if strike_distance <= 3:
            score += 15
        elif strike_distance <= 7:
            score += 12
        elif strike_distance <= 15:
            score += 8

        # DTE factor (15%)
        if 7 <= dte <= 45:
            score += 15
        elif dte <= 90:
            score += 10
        else:
            score += 5

        return min(score, 100)

    async def _post_signal(self, sweep: Dict):
        """Post golden sweep signal to Discord"""
        try:
            # Create session if needed
            if not self.session:
                self.session = aiohttp.ClientSession()

            color = 0xFFD700  # Gold

            now = datetime.now()
            time_str = now.strftime('%I:%M %p')
            date_str = now.strftime('%m/%d/%y')
            premium_millions = sweep['premium'] / 1000000
            details = f"{sweep['volume']:,} @ {sweep['avg_price']:.2f}"

            embed = {
                "title": f"🏆 {sweep['ticker']} - Golden Sweep (KAFKA REAL-TIME)",
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
                    {"name": "Prem", "value": f"${premium_millions:.1f}M", "inline": True},
                    {"name": "Algo Score", "value": str(int(sweep['golden_score'])), "inline": True},
                    {"name": "Source", "value": "Kafka", "inline": True},
                    {"name": "", "value": "Please always do your own due diligence on top of these trade ideas.", "inline": False}
                ],
                "footer": {"text": "ORAKL Bot - Golden Sweeps (Kafka Stream)"}
            }

            payload = {"embeds": [embed], "username": "ORAKL Golden Sweeps"}

            async with self.session.post(self.webhook_url, json=payload) as response:
                success = response.status == 204

            if success:
                logger.info(f"🚨 GOLDEN SWEEP (KAFKA): {sweep['ticker']} {sweep['type']} "
                          f"${sweep['strike']} Premium:${premium_millions:.1f}M "
                          f"Score:{int(sweep['golden_score'])}")

        except Exception as e:
            logger.error(f"[{self.bot_name}] Error posting signal: {e}")
