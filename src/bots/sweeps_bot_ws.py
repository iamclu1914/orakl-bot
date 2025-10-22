"""
Sweeps Bot - WebSocket Real-Time Version
Monitors $50K+ premium options sweeps via Polygon WebSocket streaming
"""
import asyncio
from datetime import datetime, timedelta
from typing import List, Dict
from polygon.websocket.models import OptionTrade
from src.websocket_base import PolygonWebSocketBase
from src.options_analyzer import OptionsAnalyzer
from src.config import Config
from src.utils.logger import logger
from src.utils.discord_poster import DiscordPoster
from discord_webhook import DiscordEmbed


class SweepsBotWS(PolygonWebSocketBase):
    """Real-time Sweeps detection via WebSocket"""

    def __init__(self, webhook_url: str, watchlist: List[str], analyzer: OptionsAnalyzer):
        super().__init__("Sweeps Bot WS")
        self.webhook_url = webhook_url
        self.watchlist = watchlist
        self.analyzer = analyzer

        # Thresholds
        self.MIN_PREMIUM = Config.SWEEPS_MIN_PREMIUM  # $50K
        self.MIN_SCORE = Config.MIN_SWEEP_SCORE  # 60

        # Trade aggregation
        self.trade_windows: Dict[str, List[Dict]] = {}
        self.window_size = 60  # seconds

        # Discord poster
        self.discord = DiscordPoster(webhook_url, "Sweeps Bot WS")

    async def subscribe(self):
        """Subscribe to options trades for all watchlist symbols"""
        await self.subscribe_options_trades(self.watchlist)

    def on_message(self, msgs: List):
        """Handle incoming options trade messages"""
        for msg in msgs:
            if not hasattr(msg, 'price') or not hasattr(msg, 'size'):
                continue

            try:
                asyncio.create_task(self.process_trade(msg))
            except Exception as e:
                logger.error(f"[{self.bot_name}] Error processing trade: {e}")

    async def process_trade(self, trade: OptionTrade):
        """Process individual options trade and aggregate"""
        try:
            # Extract trade details
            contract = trade.option_symbol if hasattr(trade, 'option_symbol') else str(trade)
            price = trade.price
            size = trade.size
            timestamp = datetime.fromtimestamp(trade.timestamp / 1000) if hasattr(trade, 'timestamp') else datetime.now()

            # Calculate premium
            premium = price * size * 100

            # Skip if below sweeps threshold
            if premium < self.MIN_PREMIUM:
                return

            # Parse contract
            ticker, option_type, strike, expiration = self._parse_contract(contract)

            if not ticker:
                return

            # Create contract key
            contract_key = f"{ticker}_{option_type}_{strike}_{expiration}"

            # Initialize/update trade window
            if contract_key not in self.trade_windows:
                self.trade_windows[contract_key] = []

            self.trade_windows[contract_key].append({
                'price': price,
                'size': size,
                'premium': premium,
                'timestamp': timestamp,
                'contract': contract
            })

            # Clean old trades
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

            # Check if meets sweep criteria
            if total_premium >= self.MIN_PREMIUM and num_fills >= 2:
                # Estimate current price
                current_price = strike * (1.05 if option_type == 'CALL' else 0.95)

                # Calculate days to expiry
                exp_date = datetime.strptime(expiration, '%Y%m%d')
                days_to_expiry = (exp_date - datetime.now()).days

                # Calculate probability ITM
                prob_itm = self.analyzer.calculate_probability_itm(
                    option_type, strike, current_price, days_to_expiry
                )

                # Calculate sweep score
                strike_distance = abs((strike - current_price) / current_price) * 100
                sweep_score = self._calculate_sweep_score(
                    total_premium, total_volume, strike_distance, days_to_expiry
                )

                # Check minimum score
                if sweep_score >= self.MIN_SCORE:
                    # Generate signal ID
                    signal_id = self.generate_signal_id(
                        contract_key, int(timestamp.timestamp()), 'sweep'
                    )

                    # Check deduplication
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
                        'sweep_score': sweep_score,
                        'strike_distance': strike_distance
                    }

                    # Post to Discord
                    await self._post_signal(sweep)

        except Exception as e:
            logger.error(f"[{self.bot_name}] Error processing trade: {e}")

    def _parse_contract(self, contract: str) -> tuple:
        """Parse Polygon options contract symbol"""
        try:
            contract = contract.replace('O:', '')

            date_start = None
            for i in range(len(contract)):
                if contract[i:i+6].isdigit() and len(contract[i:i+6]) == 6:
                    date_start = i
                    break

            if date_start is None:
                return None, None, None, None

            ticker = contract[:date_start]
            date_str = contract[date_start:date_start+6]
            option_type = contract[date_start+6]
            strike_str = contract[date_start+7:]

            expiration = f"20{date_str}"
            strike = int(strike_str) / 1000
            opt_type = 'CALL' if option_type == 'C' else 'PUT'

            return ticker, opt_type, strike, expiration

        except Exception as e:
            logger.error(f"Error parsing contract {contract}: {e}")
            return None, None, None, None

    def _calculate_sweep_score(self, premium: float, volume: int,
                               strike_distance: float, dte: int) -> int:
        """Calculate sweep score (0-100)"""
        score = 0

        # Premium scoring (40%) - lower thresholds than golden
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
        elif volume >= 200:
            score += 15
        else:
            score += 10

        # Strike proximity (20%)
        if strike_distance <= 3:
            score += 20
        elif strike_distance <= 7:
            score += 15
        elif strike_distance <= 15:
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
            color = 0x00FF00  # Green

            now = datetime.now()
            time_str = now.strftime('%I:%M %p')
            date_str = now.strftime('%m/%d/%y')
            premium_k = sweep['premium'] / 1000
            details = f"{sweep['volume']:,} @ {sweep['avg_price']:.2f}"

            embed = DiscordEmbed(
                title=f"💎 {sweep['ticker']} - Sweep Detected (REAL-TIME)",
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
            embed.add_embed_field(name="Prem", value=f"${premium_k:.0f}K", inline=True)
            embed.add_embed_field(name="Algo Score", value=str(int(sweep['sweep_score'])), inline=True)
            embed.add_embed_field(name="Mode", value="WebSocket", inline=True)

            embed.add_embed_field(
                name="",
                value="Please always do your own due diligence on top of these trade ideas.",
                inline=False
            )

            embed.set_footer(text="ORAKL Bot - Sweeps (Real-Time)")

            success = await self.discord.post_embed(embed)

            if success:
                logger.info(f"🚨 SWEEP (REAL-TIME): {sweep['ticker']} {sweep['type']} "
                          f"${sweep['strike']} Premium:${premium_k:.0f}K "
                          f"Score:{int(sweep['sweep_score'])}")

        except Exception as e:
            logger.error(f"[{self.bot_name}] Error posting signal: {e}")
