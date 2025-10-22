"""
Bullseye Bot - WebSocket Real-Time Version
Monitors $5K+ premium directional bets via Polygon WebSocket streaming
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


class BullseyeBotWS(PolygonWebSocketBase):
    """Real-time Bullseye detection via WebSocket"""

    def __init__(self, webhook_url: str, watchlist: List[str], analyzer: OptionsAnalyzer):
        super().__init__("Bullseye Bot WS")
        self.webhook_url = webhook_url
        self.watchlist = watchlist
        self.analyzer = analyzer

        # Thresholds
        self.MIN_PREMIUM = Config.BULLSEYE_MIN_PREMIUM  # $5K
        self.MIN_SCORE = Config.MIN_BULLSEYE_SCORE  # 70

        # Trade aggregation
        self.trade_windows: Dict[str, List[Dict]] = {}
        self.window_size = 60

        # Discord poster
        self.discord = DiscordPoster(webhook_url, "Bullseye Bot WS")

    async def subscribe(self):
        """Subscribe to options trades"""
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
        """Process individual options trade"""
        try:
            contract = trade.option_symbol if hasattr(trade, 'option_symbol') else str(trade)
            price = trade.price
            size = trade.size
            timestamp = datetime.fromtimestamp(trade.timestamp / 1000) if hasattr(trade, 'timestamp') else datetime.now()

            premium = price * size * 100

            if premium < self.MIN_PREMIUM:
                return

            ticker, option_type, strike, expiration = self._parse_contract(contract)

            if not ticker:
                return

            contract_key = f"{ticker}_{option_type}_{strike}_{expiration}"

            if contract_key not in self.trade_windows:
                self.trade_windows[contract_key] = []

            self.trade_windows[contract_key].append({
                'price': price,
                'size': size,
                'premium': premium,
                'timestamp': timestamp
            })

            # Clean old trades
            cutoff_time = datetime.now() - timedelta(seconds=self.window_size)
            self.trade_windows[contract_key] = [
                t for t in self.trade_windows[contract_key]
                if t['timestamp'] > cutoff_time
            ]

            total_premium = sum(t['premium'] for t in self.trade_windows[contract_key])
            total_volume = sum(t['size'] for t in self.trade_windows[contract_key])
            num_fills = len(self.trade_windows[contract_key])
            avg_price = sum(t['price'] for t in self.trade_windows[contract_key]) / num_fills

            if total_premium >= self.MIN_PREMIUM:
                current_price = strike * (1.05 if option_type == 'CALL' else 0.95)
                exp_date = datetime.strptime(expiration, '%Y%m%d')
                days_to_expiry = (exp_date - datetime.now()).days

                prob_itm = self.analyzer.calculate_probability_itm(
                    option_type, strike, current_price, days_to_expiry
                )

                strike_distance = abs((strike - current_price) / current_price) * 100
                bullseye_score = self._calculate_bullseye_score(
                    total_premium, total_volume, strike_distance, days_to_expiry
                )

                if bullseye_score >= self.MIN_SCORE:
                    signal_id = self.generate_signal_id(
                        contract_key, int(timestamp.timestamp()), 'bullseye'
                    )

                    if self.is_duplicate_signal(signal_id):
                        return

                    bet = {
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
                        'bullseye_score': bullseye_score,
                        'strike_distance': strike_distance
                    }

                    await self._post_signal(bet)

        except Exception as e:
            logger.error(f"[{self.bot_name}] Error processing trade: {e}")

    def _parse_contract(self, contract: str) -> tuple:
        """Parse Polygon options contract"""
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

    def _calculate_bullseye_score(self, premium: float, volume: int,
                                  strike_distance: float, dte: int) -> int:
        """Calculate bullseye score (0-100) - higher standards"""
        score = 0

        # Premium scoring (35%)
        if premium >= 100000:
            score += 35
        elif premium >= 50000:
            score += 30
        elif premium >= 25000:
            score += 25
        elif premium >= 5000:
            score += 20

        # Volume scoring (25%)
        if volume >= 500:
            score += 25
        elif volume >= 200:
            score += 20
        elif volume >= 100:
            score += 15
        else:
            score += 10

        # Strike proximity (25%) - reward tight strikes
        if strike_distance <= 2:
            score += 25
        elif strike_distance <= 5:
            score += 20
        elif strike_distance <= 10:
            score += 15

        # DTE factor (15%)
        if 7 <= dte <= 30:
            score += 15
        elif dte <= 60:
            score += 10
        else:
            score += 5

        return min(score, 100)

    async def _post_signal(self, bet: Dict):
        """Post bullseye signal to Discord"""
        try:
            color = 0xFF0000 if bet['type'] == 'PUT' else 0x00FF00

            now = datetime.now()
            time_str = now.strftime('%I:%M %p')
            date_str = now.strftime('%m/%d/%y')
            premium_k = bet['premium'] / 1000
            details = f"{bet['volume']:,} @ {bet['avg_price']:.2f}"

            embed = DiscordEmbed(
                title=f"🎯 {bet['ticker']} - Bullseye Bet (REAL-TIME)",
                color=color
            )

            embed.add_embed_field(name="Date", value=date_str, inline=True)
            embed.add_embed_field(name="Time", value=time_str, inline=True)
            embed.add_embed_field(name="Ticker", value=bet['ticker'], inline=True)
            embed.add_embed_field(name="Exp", value=bet['expiration'], inline=True)
            embed.add_embed_field(name="Strike", value=f"{bet['strike']:.0f}", inline=True)
            embed.add_embed_field(name="C/P", value=bet['type'] + "S", inline=True)
            embed.add_embed_field(name="Spot", value=f"{bet['current_price']:.2f}", inline=True)
            embed.add_embed_field(name="Details", value=details, inline=True)
            embed.add_embed_field(name="Type", value="BULLSEYE", inline=True)
            embed.add_embed_field(name="Prem", value=f"${premium_k:.1f}K", inline=True)
            embed.add_embed_field(name="Algo Score", value=str(int(bet['bullseye_score'])), inline=True)
            embed.add_embed_field(name="Mode", value="WebSocket", inline=True)

            embed.add_embed_field(
                name="",
                value="Please always do your own due diligence on top of these trade ideas.",
                inline=False
            )

            embed.set_footer(text="ORAKL Bot - Bullseye (Real-Time)")

            success = await self.discord.post_embed(embed)

            if success:
                logger.info(f"🚨 BULLSEYE (REAL-TIME): {bet['ticker']} {bet['type']} "
                          f"${bet['strike']} Premium:${premium_k:.1f}K "
                          f"Score:{int(bet['bullseye_score'])}")

        except Exception as e:
            logger.error(f"[{self.bot_name}] Error posting signal: {e}")
