"""
Scalps Bot - WebSocket Real-Time Version
Monitors $2K+ premium quick trades via Polygon WebSocket streaming
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


class ScalpsBotWS(PolygonWebSocketBase):
    """Real-time Scalps detection via WebSocket"""

    def __init__(self, webhook_url: str, watchlist: List[str], analyzer: OptionsAnalyzer):
        super().__init__("Scalps Bot WS")
        self.webhook_url = webhook_url
        self.watchlist = watchlist
        self.analyzer = analyzer

        # Thresholds
        self.MIN_PREMIUM = Config.SCALPS_MIN_PREMIUM  # $2K
        self.MIN_SCORE = Config.MIN_SCALP_SCORE  # 65

        # Trade aggregation (shorter window for scalps)
        self.trade_windows: Dict[str, List[Dict]] = {}
        self.window_size = 30  # 30 seconds for quick trades

        # Discord poster
        self.discord = DiscordPoster(webhook_url, "Scalps Bot WS")

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

            # For scalps, focus on very near-term expirations (0-7 DTE)
            exp_date = datetime.strptime(expiration, '%Y%m%d')
            days_to_expiry = (exp_date - datetime.now()).days

            if days_to_expiry > 7:
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

                prob_itm = self.analyzer.calculate_probability_itm(
                    option_type, strike, current_price, days_to_expiry
                )

                strike_distance = abs((strike - current_price) / current_price) * 100
                scalp_score = self._calculate_scalp_score(
                    total_premium, total_volume, strike_distance, days_to_expiry
                )

                if scalp_score >= self.MIN_SCORE:
                    signal_id = self.generate_signal_id(
                        contract_key, int(timestamp.timestamp()), 'scalp'
                    )

                    if self.is_duplicate_signal(signal_id):
                        return

                    scalp = {
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
                        'scalp_score': scalp_score,
                        'strike_distance': strike_distance
                    }

                    await self._post_signal(scalp)

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

    def _calculate_scalp_score(self, premium: float, volume: int,
                               strike_distance: float, dte: int) -> int:
        """Calculate scalp score (0-100) - focus on quick trades"""
        score = 0

        # Premium scoring (30%) - lower thresholds
        if premium >= 50000:
            score += 30
        elif premium >= 25000:
            score += 25
        elif premium >= 10000:
            score += 20
        elif premium >= 2000:
            score += 15

        # Volume scoring (25%)
        if volume >= 200:
            score += 25
        elif volume >= 100:
            score += 20
        elif volume >= 50:
            score += 15
        else:
            score += 10

        # Strike proximity (25%) - reward very tight strikes
        if strike_distance <= 1:
            score += 25
        elif strike_distance <= 3:
            score += 20
        elif strike_distance <= 5:
            score += 15

        # DTE factor (20%) - reward very short term (0-3 DTE most valuable)
        if dte <= 1:
            score += 20
        elif dte <= 3:
            score += 15
        elif dte <= 7:
            score += 10

        return min(score, 100)

    async def _post_signal(self, scalp: Dict):
        """Post scalp signal to Discord"""
        try:
            color = 0xFFFF00  # Yellow for scalps

            now = datetime.now()
            time_str = now.strftime('%I:%M %p')
            date_str = now.strftime('%m/%d/%y')
            premium_k = scalp['premium'] / 1000
            details = f"{scalp['volume']:,} @ {scalp['avg_price']:.2f}"

            embed = DiscordEmbed(
                title=f"⚡ {scalp['ticker']} - Scalp Opportunity (REAL-TIME)",
                color=color
            )

            embed.add_embed_field(name="Date", value=date_str, inline=True)
            embed.add_embed_field(name="Time", value=time_str, inline=True)
            embed.add_embed_field(name="Ticker", value=scalp['ticker'], inline=True)
            embed.add_embed_field(name="Exp", value=scalp['expiration'], inline=True)
            embed.add_embed_field(name="Strike", value=f"{scalp['strike']:.0f}", inline=True)
            embed.add_embed_field(name="C/P", value=scalp['type'] + "S", inline=True)
            embed.add_embed_field(name="Spot", value=f"{scalp['current_price']:.2f}", inline=True)
            embed.add_embed_field(name="Details", value=details, inline=True)
            embed.add_embed_field(name="Type", value="SCALP", inline=True)
            embed.add_embed_field(name="Prem", value=f"${premium_k:.1f}K", inline=True)
            embed.add_embed_field(name="Algo Score", value=str(int(scalp['scalp_score'])), inline=True)
            embed.add_embed_field(name="DTE", value=f"{scalp['days_to_expiry']}d", inline=True)

            embed.add_embed_field(
                name="",
                value="Please always do your own due diligence on top of these trade ideas.",
                inline=False
            )

            embed.set_footer(text="ORAKL Bot - Scalps (Real-Time)")

            success = await self.discord.post_embed(embed)

            if success:
                logger.info(f"🚨 SCALP (REAL-TIME): {scalp['ticker']} {scalp['type']} "
                          f"${scalp['strike']} {scalp['days_to_expiry']}DTE "
                          f"Premium:${premium_k:.1f}K Score:{int(scalp['scalp_score'])}")

        except Exception as e:
            logger.error(f"[{self.bot_name}] Error posting signal: {e}")
