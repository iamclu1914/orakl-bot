"""
Darkpool Bot - WebSocket Real-Time Version
Monitors large block trades (10K+ shares) via Polygon WebSocket streaming
"""
import asyncio
from datetime import datetime, timedelta
from typing import List, Dict
from polygon.websocket.models import Trade
from src.websocket_base import PolygonWebSocketBase
from src.config import Config
from src.utils.logger import logger
from src.utils.discord_poster import DiscordPoster
from discord_webhook import DiscordEmbed


class DarkpoolBotWS(PolygonWebSocketBase):
    """Real-time Darkpool block trades detection via WebSocket"""

    def __init__(self, webhook_url: str, watchlist: List[str]):
        super().__init__("Darkpool Bot WS")
        self.webhook_url = webhook_url
        self.watchlist = watchlist

        # Thresholds
        self.MIN_BLOCK_SIZE = Config.DARKPOOL_MIN_BLOCK_SIZE  # 10K shares
        self.MIN_SCORE = Config.MIN_DARKPOOL_SCORE  # 60

        # Trade aggregation (group block trades within 60 seconds)
        self.trade_windows: Dict[str, List[Dict]] = {}
        self.window_size = 60

        # Discord poster
        self.discord = DiscordPoster(webhook_url, "Darkpool Bot WS")

    async def subscribe(self):
        """Subscribe to stock trades for watchlist"""
        await self.subscribe_stock_trades(self.watchlist)

    def on_message(self, msgs: List):
        """Handle incoming stock trade messages"""
        for msg in msgs:
            if not hasattr(msg, 'price') or not hasattr(msg, 'size'):
                continue

            try:
                asyncio.create_task(self.process_trade(msg))
            except Exception as e:
                logger.error(f"[{self.bot_name}] Error processing trade: {e}")

    async def process_trade(self, trade: Trade):
        """Process individual stock trade"""
        try:
            ticker = trade.symbol if hasattr(trade, 'symbol') else str(trade)
            price = trade.price
            size = trade.size
            timestamp = datetime.fromtimestamp(trade.timestamp / 1000) if hasattr(trade, 'timestamp') else datetime.now()

            # Skip if below block size threshold
            if size < self.MIN_BLOCK_SIZE:
                return

            # Calculate total value
            total_value = price * size

            # Initialize trade window
            if ticker not in self.trade_windows:
                self.trade_windows[ticker] = []

            self.trade_windows[ticker].append({
                'price': price,
                'size': size,
                'value': total_value,
                'timestamp': timestamp
            })

            # Clean old trades
            cutoff_time = datetime.now() - timedelta(seconds=self.window_size)
            self.trade_windows[ticker] = [
                t for t in self.trade_windows[ticker]
                if t['timestamp'] > cutoff_time
            ]

            # Calculate aggregated metrics
            total_volume = sum(t['size'] for t in self.trade_windows[ticker])
            total_dollars = sum(t['value'] for t in self.trade_windows[ticker])
            num_blocks = len(self.trade_windows[ticker])
            avg_price = sum(t['price'] for t in self.trade_windows[ticker]) / num_blocks

            # Calculate darkpool score
            darkpool_score = self._calculate_darkpool_score(size, total_value, num_blocks)

            if darkpool_score >= self.MIN_SCORE:
                # Generate signal ID
                signal_id = self.generate_signal_id(
                    ticker, int(timestamp.timestamp()), 'darkpool'
                )

                # Check deduplication
                if self.is_duplicate_signal(signal_id):
                    return

                # Create block trade signal
                block = {
                    'ticker': ticker,
                    'price': price,
                    'size': size,
                    'total_value': total_value,
                    'num_blocks': num_blocks,
                    'total_volume': total_volume,
                    'total_dollars': total_dollars,
                    'avg_price': avg_price,
                    'darkpool_score': darkpool_score
                }

                # Post to Discord
                await self._post_signal(block)

        except Exception as e:
            logger.error(f"[{self.bot_name}] Error processing trade: {e}")

    def _calculate_darkpool_score(self, size: int, value: float, num_blocks: int) -> int:
        """Calculate darkpool score (0-100)"""
        score = 0

        # Size scoring (40%)
        if size >= 100000:
            score += 40
        elif size >= 50000:
            score += 35
        elif size >= 25000:
            score += 30
        elif size >= 10000:
            score += 25

        # Dollar value scoring (40%)
        if value >= 10000000:
            score += 40
        elif value >= 5000000:
            score += 35
        elif value >= 2000000:
            score += 30
        elif value >= 500000:
            score += 25

        # Multiple blocks bonus (20%)
        if num_blocks >= 5:
            score += 20
        elif num_blocks >= 3:
            score += 15
        elif num_blocks >= 2:
            score += 10
        else:
            score += 5

        return min(score, 100)

    async def _post_signal(self, block: Dict):
        """Post darkpool block trade to Discord"""
        try:
            color = 0x800080  # Purple for darkpool

            now = datetime.now()
            time_str = now.strftime('%I:%M %p')
            date_str = now.strftime('%m/%d/%y')
            value_millions = block['total_value'] / 1000000

            embed = DiscordEmbed(
                title=f"🔮 {block['ticker']} - Darkpool Block Trade (REAL-TIME)",
                color=color
            )

            embed.add_embed_field(name="Date", value=date_str, inline=True)
            embed.add_embed_field(name="Time", value=time_str, inline=True)
            embed.add_embed_field(name="Ticker", value=block['ticker'], inline=True)
            embed.add_embed_field(name="Price", value=f"${block['price']:.2f}", inline=True)
            embed.add_embed_field(name="Size", value=f"{block['size']:,}", inline=True)
            embed.add_embed_field(name="Value", value=f"${value_millions:.2f}M", inline=True)
            embed.add_embed_field(name="Num Blocks", value=str(block['num_blocks']), inline=True)
            embed.add_embed_field(name="Avg Price", value=f"${block['avg_price']:.2f}", inline=True)
            embed.add_embed_field(name="Type", value="BLOCK", inline=True)
            embed.add_embed_field(name="Total Vol", value=f"{block['total_volume']:,}", inline=True)
            embed.add_embed_field(name="Algo Score", value=str(int(block['darkpool_score'])), inline=True)
            embed.add_embed_field(name="Mode", value="WebSocket", inline=True)

            embed.add_embed_field(
                name="",
                value="Please always do your own due diligence on top of these trade ideas.",
                inline=False
            )

            embed.set_footer(text="ORAKL Bot - Darkpool (Real-Time)")

            success = await self.discord.post_embed(embed)

            if success:
                logger.info(f"🚨 DARKPOOL (REAL-TIME): {block['ticker']} "
                          f"{block['size']:,} shares @ ${block['price']:.2f} "
                          f"Value:${value_millions:.2f}M Score:{int(block['darkpool_score'])}")

        except Exception as e:
            logger.error(f"[{self.bot_name}] Error posting signal: {e}")
