"""Darkpool Bot - Large darkpool and block trades tracker"""
import logging
from datetime import datetime, timedelta
from typing import List, Dict
from .base_bot import BaseAutoBot
from src.data_fetcher import DataFetcher
from src.options_analyzer import OptionsAnalyzer
from src.config import Config

logger = logging.getLogger(__name__)

class DarkpoolBot(BaseAutoBot):
    """
    Darkpool Bot
    Tracks unusually large darkpool and block trades that are significant
    relative to market cap and average volume
    """

    def __init__(self, webhook_url: str, watchlist: List[str], fetcher: DataFetcher, analyzer: OptionsAnalyzer):
        super().__init__(webhook_url, "Darkpool Bot", scan_interval=240)  # 4 minutes
        self.watchlist = watchlist
        self.fetcher = fetcher
        self.analyzer = analyzer
        self.signal_history = {}
        self.MIN_BLOCK_SIZE = 10000  # Minimum 10k shares

    async def scan_and_post(self):
        """Scan for large darkpool and block trades"""
        logger.info(f"{self.name} scanning for darkpool activity")

        is_open = await self.fetcher.is_market_open()
        if not is_open:
            logger.debug(f"{self.name} - Market closed")
            return

        for symbol in self.watchlist:
            try:
                blocks = await self._scan_block_trades(symbol)
                for block in blocks:
                    await self._post_signal(block)
            except Exception as e:
                logger.error(f"{self.name} error scanning {symbol}: {e}")

    async def _scan_block_trades(self, symbol: str) -> List[Dict]:
        """Scan for block trades and darkpool activity"""
        blocks = []

        try:
            # Get current price and market data
            current_price = await self.fetcher.get_stock_price(symbol)
            if not current_price:
                return blocks

            # Get recent trades (Polygon provides trade-level data)
            # For block detection, we look for large single trades
            trades = await self.fetcher.get_stock_trades(symbol, limit=1000)
            if not trades:
                return blocks

            # Calculate average trade size
            avg_size = sum(t.get('size', 0) for t in trades) / len(trades) if trades else 0

            # Filter for block-sized trades
            recent_cutoff = datetime.now() - timedelta(minutes=15)

            for trade in trades:
                trade_time = datetime.fromtimestamp(trade.get('timestamp', 0) / 1000)
                if trade_time < recent_cutoff:
                    continue

                size = trade.get('size', 0)
                price = trade.get('price', current_price)

                # Block trade criteria:
                # 1. Size > 10,000 shares
                # 2. Size > 5x average trade size
                # 3. Significant dollar value

                dollar_value = size * price
                is_block = (
                    size >= self.MIN_BLOCK_SIZE and
                    size >= (avg_size * 5) and
                    dollar_value >= 100000  # $100k minimum
                )

                if not is_block:
                    continue

                # Detect potential darkpool characteristics
                # Darkpool trades often occur at specific exchanges
                exchange = trade.get('exchange', '')
                conditions = trade.get('conditions', [])

                # Common darkpool indicators
                is_darkpool = any([
                    'D' in str(exchange),  # Dark pool exchange
                    'T' in conditions,  # Extended hours
                    'I' in conditions,  # Odd lot
                    size >= 50000,  # Very large size
                ])

                # Calculate block score
                block_score = self._calculate_block_score(
                    size, dollar_value, avg_size, is_darkpool
                )

                if block_score >= 60:
                    block = {
                        'ticker': symbol,
                        'current_price': current_price,
                        'block_price': price,
                        'size': size,
                        'dollar_value': dollar_value,
                        'timestamp': trade_time,
                        'exchange': exchange,
                        'is_darkpool': is_darkpool,
                        'avg_size_multiple': size / avg_size if avg_size > 0 else 0,
                        'block_score': block_score,
                        'conditions': conditions
                    }

                    # Check if already posted
                    signal_key = f"{symbol}_{int(trade.get('timestamp', 0))}_{size}"
                    if signal_key not in self.signal_history:
                        blocks.append(block)
                        self.signal_history[signal_key] = datetime.now()

        except Exception as e:
            logger.error(f"Error scanning block trades for {symbol}: {e}")

        return blocks

    def _calculate_block_score(self, size: int, dollar_value: float,
                               avg_size: float, is_darkpool: bool) -> int:
        """Calculate block trade significance score"""
        score = 0

        # Size significance (35%)
        if size >= 100000:
            score += 35
        elif size >= 50000:
            score += 30
        elif size >= 25000:
            score += 25
        elif size >= 10000:
            score += 20

        # Dollar value (30%)
        if dollar_value >= 5000000:  # $5M+
            score += 30
        elif dollar_value >= 2000000:  # $2M+
            score += 25
        elif dollar_value >= 1000000:  # $1M+
            score += 20
        elif dollar_value >= 500000:  # $500k+
            score += 15

        # Relative to average (20%)
        if avg_size > 0:
            multiple = size / avg_size
            if multiple >= 20:
                score += 20
            elif multiple >= 10:
                score += 15
            elif multiple >= 5:
                score += 10

        # Darkpool indicator (15%)
        if is_darkpool:
            score += 15

        return score

    async def _post_signal(self, block: Dict):
        """Post darkpool/block trade signal to Discord"""

        # Color based on darkpool vs regular block
        color = 0x9B30FF if block['is_darkpool'] else 0x4169E1  # Purple for darkpool, blue for block
        emoji = "🌑" if block['is_darkpool'] else "🧱"

        trade_type = "DARKPOOL" if block['is_darkpool'] else "BLOCK TRADE"

        # Calculate premium/discount to current price
        price_diff = ((block['block_price'] - block['current_price']) / block['current_price']) * 100

        embed = self.create_embed(
            title=f"{emoji} {trade_type}: {block['ticker']}",
            description=f"Large {'darkpool' if block['is_darkpool'] else 'block'} trade detected | Score: {block['block_score']}/100",
            color=color,
            fields=[
                {
                    "name": "📊 Size",
                    "value": f"**{block['size']:,} shares**",
                    "inline": True
                },
                {
                    "name": "💰 Dollar Value",
                    "value": f"**${block['dollar_value']:,.0f}**",
                    "inline": True
                },
                {
                    "name": "📈 Block Score",
                    "value": f"{block['block_score']}/100",
                    "inline": True
                },
                {
                    "name": "💵 Block Price",
                    "value": f"${block['block_price']:.2f}",
                    "inline": True
                },
                {
                    "name": "📈 Current Price",
                    "value": f"${block['current_price']:.2f}",
                    "inline": True
                },
                {
                    "name": "📊 Price Diff",
                    "value": f"{price_diff:+.2f}%",
                    "inline": True
                },
                {
                    "name": "🔢 Avg Size Multiple",
                    "value": f"{block['avg_size_multiple']:.1f}x average",
                    "inline": True
                },
                {
                    "name": "🏢 Exchange",
                    "value": block['exchange'] or "N/A",
                    "inline": True
                },
                {
                    "name": "⏰ Timestamp",
                    "value": block['timestamp'].strftime("%H:%M:%S"),
                    "inline": True
                },
                {
                    "name": "💡 Analysis",
                    "value": f"{'Darkpool activity suggests institutional positioning' if block['is_darkpool'] else 'Large block trade indicates significant position'}\n"
                            f"Trade executed at {'premium' if price_diff > 0 else 'discount' if price_diff < 0 else 'market price'}",
                    "inline": False
                }
            ],
            footer=f"{'Darkpool' if block['is_darkpool'] else 'Block Trade'} Bot | Institutional Activity Tracker"
        )

        await self.post_to_discord(embed)
        logger.info(f"Posted {trade_type}: {block['ticker']} {block['size']:,} shares @ ${block['block_price']:.2f}")
