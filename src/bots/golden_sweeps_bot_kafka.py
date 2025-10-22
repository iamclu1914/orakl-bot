"""
Golden Sweeps Bot - Kafka Consumer Version
Consumes $1M+ premium sweeps from Kafka raw-trades topic
"""
from datetime import datetime, timedelta
from typing import Dict, List
from src.kafka_base import KafkaConsumerBase
from src.options_analyzer import OptionsAnalyzer
from src.config import Config
from src.utils.logger import logger
from src.utils.discord_poster import DiscordPoster
from discord_webhook import DiscordEmbed


class GoldenSweepsBotKafka(KafkaConsumerBase):
    """Real-time Golden Sweeps detection from Kafka"""

    def __init__(self, webhook_url: str, watchlist: List[str], analyzer: OptionsAnalyzer):
        super().__init__("Golden Sweeps Bot Kafka", topics=["raw-trades"])

        self.webhook_url = webhook_url
        self.watchlist = set(watchlist)  # Convert to set for O(1) lookup
        self.analyzer = analyzer

        # Thresholds
        self.MIN_PREMIUM = Config.GOLDEN_MIN_PREMIUM  # $1M
        self.MIN_SCORE = Config.MIN_GOLDEN_SCORE  # 60

        # Trade aggregation windows (group trades within 60 seconds)
        self.trade_windows: Dict[str, List[Dict]] = {}
        self.window_size = 60  # seconds

        # Discord poster
        self.discord = DiscordPoster(webhook_url, "Golden Sweeps Bot Kafka")

    async def process_message(self, data: Dict, topic: str):
        """Process options trade message from Kafka"""
        try:
            # Skip non-options trades
            if data.get('ev') != 'T':  # T = Trade
                return

            # Parse symbol (format: O:SPY250117C00600000)
            symbol_full = data.get('sym', '')
            if not symbol_full.startswith('O:'):
                return  # Not an options trade

            # Extract underlying ticker
            ticker = self._extract_ticker(symbol_full)
            if not ticker or ticker not in self.watchlist:
                return  # Not in watchlist

            # Extract trade details
            price = data.get('p', 0)  # Price
            size = data.get('s', 0)  # Size (contracts)
            timestamp = data.get('t', 0)  # Timestamp (ms)
            exchange = data.get('x', 0)  # Exchange ID

            # Calculate premium
            premium = price * size * 100  # Options multiplier

            # Skip if below golden threshold
            if premium < self.MIN_PREMIUM:
                return

            # Parse contract details
            option_type, strike, expiration = self._parse_contract(symbol_full)
            if not option_type:
                return

            # Create contract key for aggregation
            contract_key = f"{ticker}_{option_type}_{strike}_{expiration}"

            # Initialize trade window
            if contract_key not in self.trade_windows:
                self.trade_windows[contract_key] = []

            # Add trade to window
            trade_time = datetime.fromtimestamp(timestamp / 1000)
            self.trade_windows[contract_key].append({
                'price': price,
                'size': size,
                'premium': premium,
                'timestamp': trade_time,
                'exchange': exchange
            })

            # Clean old trades (older than 60 seconds)
            cutoff_time = datetime.now() - timedelta(seconds=self.window_size)
            self.trade_windows[contract_key] = [
                t for t in self.trade_windows[contract_key]
                if t['timestamp'] > cutoff_time
            ]

            # Calculate aggregated metrics
            total_premium = sum(t['premium'] for t in self.trade_windows[contract_key])
            total_volume = sum(t['size'] for t in self.trade_windows[contract_key])
            num_fills = len(self.trade_windows[contract_key])
            avg_price = sum(t['price'] for t in self.trade_windows[contract_key]) / num_fills

            # Check if meets golden sweep criteria
            if total_premium >= self.MIN_PREMIUM and num_fills >= 3:
                # Calculate days to expiry
                exp_date = datetime.strptime(expiration, '%Y%m%d')
                days_to_expiry = (exp_date - datetime.now()).days

                # Estimate current price (would ideally get from aggregated-metrics topic)
                current_price = strike * (1.05 if option_type == 'CALL' else 0.95)

                # Calculate probability ITM
                prob_itm = self.analyzer.calculate_probability_itm(
                    option_type, strike, current_price, days_to_expiry
                )

                # Calculate golden score
                strike_distance = abs((strike - current_price) / current_price) * 100
                golden_score = self._calculate_golden_score(
                    total_premium, total_volume, strike_distance, days_to_expiry
                )

                # Check minimum score
                if golden_score >= self.MIN_SCORE:
                    # Generate signal ID for deduplication
                    signal_id = self.generate_signal_id(
                        contract_key, int(timestamp), 'golden'
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
                        'premium': total_premium,
                        'volume': total_volume,
                        'num_fills': num_fills,
                        'avg_price': avg_price,
                        'probability_itm': prob_itm,
                        'golden_score': golden_score,
                        'strike_distance': strike_distance
                    }

                    # Post to Discord
                    await self._post_signal(sweep)

        except Exception as e:
            logger.error(f"[{self.bot_name}] Error processing message: {e}")

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
            color = 0xFFD700  # Gold

            now = datetime.now()
            time_str = now.strftime('%I:%M %p')
            date_str = now.strftime('%m/%d/%y')
            premium_millions = sweep['premium'] / 1000000
            details = f"{sweep['volume']:,} @ {sweep['avg_price']:.2f}"

            embed = DiscordEmbed(
                title=f"🏆 {sweep['ticker']} - Golden Sweep (KAFKA REAL-TIME)",
                color=color
            )

            embed.add_embed_field(name="Date", value=date_str, inline=True)
            embed.add_embed_field(name="Time", value=time_str, inline=True)
            embed.add_embed_field(name="Ticker", value=sweep['ticker'], inline=True)
            embed.add_embed_field(name="Exp", value=sweep['expiration'], inline=True)
            embed.add_embed_field(name="Strike", value=f"{sweep['strike']:.0f}", inline=True)
            embed.add_embed_field(name="C/P", value=sweep['type'] + "S", inline=True)
            embed.add_embed_field(name="Spot", value=f"{sweep['current_price']:.2f}", inline=True)
            embed.add_embed_field(name="Details", value=details, inline=True)
            embed.add_embed_field(name="Type", value="SWEEP", inline=True)
            embed.add_embed_field(name="Prem", value=f"${premium_millions:.1f}M", inline=True)
            embed.add_embed_field(name="Algo Score", value=str(int(sweep['golden_score'])), inline=True)
            embed.add_embed_field(name="Source", value="Kafka", inline=True)

            embed.add_embed_field(
                name="",
                value="Please always do your own due diligence on top of these trade ideas.",
                inline=False
            )

            embed.set_footer(text="ORAKL Bot - Golden Sweeps (Kafka Stream)")

            success = await self.discord.post_embed(embed)

            if success:
                logger.info(f"🚨 GOLDEN SWEEP (KAFKA): {sweep['ticker']} {sweep['type']} "
                          f"${sweep['strike']} Premium:${premium_millions:.1f}M "
                          f"Score:{int(sweep['golden_score'])}")

        except Exception as e:
            logger.error(f"[{self.bot_name}] Error posting signal: {e}")
