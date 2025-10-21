"""Darkpool Bot - Large darkpool and block trades tracker"""
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from .base_bot import BaseAutoBot
from src.data_fetcher import DataFetcher
from src.options_analyzer import OptionsAnalyzer
from src.config import Config
from src.utils.market_hours import MarketHours

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
        """Scan for large darkpool and block trades using concurrent processing"""
        logger.info(f"{self.name} scanning for darkpool activity")

        # Only scan during market hours (9:30 AM - 4:00 PM EST, Monday-Friday)
        if not MarketHours.is_market_open():
            logger.debug(f"{self.name} - Market closed, skipping scan")
            return
        
        # Use base class concurrent implementation
        await super().scan_and_post()
    
    async def _scan_symbol(self, symbol: str) -> List[Dict]:
        """Scan a symbol for darkpool/block trades"""
        return await self._scan_block_trades(symbol)

    async def _scan_block_trades(self, symbol: str) -> List[Dict]:
        """Scan for block trades and darkpool activity with enhanced context"""
        blocks = []

        try:
            # --- ENHANCEMENT 1: Get historical context ---
            current_price = await self.fetcher.get_stock_price(symbol)
            if not current_price:
                return blocks
            
            avg_30_day_volume = await self.fetcher.get_30_day_avg_volume(symbol)
            financials = await self.fetcher.get_financials(symbol)
            week_52_high = financials.get('52_week_high') if financials else None
            week_52_low = financials.get('52_week_low') if financials else None

            # Get recent trades
            trades = await self.fetcher.get_stock_trades(symbol, limit=1000)
            if not trades:
                return blocks

            avg_size = sum(t.get('size', 0) for t in trades) / len(trades) if trades else 0
            recent_cutoff = datetime.now() - timedelta(minutes=15)

            for trade in trades:
                trade_time = datetime.fromtimestamp(trade.get('timestamp', 0) / 1000)
                if trade_time < recent_cutoff:
                    continue

                size = trade.get('size', 0)
                price = trade.get('price', current_price)
                dollar_value = size * price

                is_block = (
                    size >= self.MIN_BLOCK_SIZE and
                    size >= (avg_size * 5) and
                    dollar_value >= 100000
                )

                if not is_block:
                    continue

                # --- ENHANCEMENT 2: Key level and directional bias analysis ---
                key_level_info = self._check_key_levels(price, week_52_high, week_52_low)
                directional_bias = self._infer_directional_bias(price, current_price)

                exchange = trade.get('exchange', '')
                conditions = trade.get('conditions', [])
                is_darkpool = any([
                    'D' in str(exchange), 'T' in conditions, 'I' in conditions, size >= 50000,
                ])

                # Calculate block score with enhanced context
                block_score = self._calculate_block_score(
                    size, dollar_value, avg_30_day_volume, is_darkpool, 
                    key_level_info is not None, directional_bias != "Neutral"
                )

                if block_score >= 60:  # Higher threshold for enhanced signals
                    block = {
                        'ticker': symbol,
                        'current_price': current_price,
                        'block_price': price,
                        'size': size,
                        'dollar_value': dollar_value,
                        'timestamp': trade_time,
                        'exchange': exchange,
                        'is_darkpool': is_darkpool,
                        'block_score': block_score,
                        'conditions': conditions,
                        # --- ENHANCEMENT 3: Add new data to signal ---
                        'percent_of_avg_volume': (size / avg_30_day_volume) * 100 if avg_30_day_volume else 0,
                        'key_level_info': key_level_info,
                        'directional_bias': directional_bias,
                    }

                    signal_key = f"{symbol}_{int(trade.get('timestamp', 0))}_{size}"
                    if signal_key not in self.signal_history:
                        blocks.append(block)
                        self.signal_history[signal_key] = datetime.now()

        except Exception as e:
            logger.error(f"Error scanning block trades for {symbol}: {e}")

        return blocks

    def _calculate_block_score(self, size: int, dollar_value: float,
                               avg_30_day_volume: Optional[float], is_darkpool: bool,
                               at_key_level: bool, has_bias: bool) -> int:
        """Calculate ENHANCED block trade significance score"""
        score = 0

        # --- ENHANCED SCORING ---
        # 1. Percent of Daily Volume (40%) - MOST IMPORTANT METRIC
        if avg_30_day_volume and avg_30_day_volume > 0:
            percent_of_volume = (size / avg_30_day_volume) * 100
            if percent_of_volume >= 10:  # 10%+ of daily volume in one trade
                score += 40
            elif percent_of_volume >= 5:   # 5%
                score += 35
            elif percent_of_volume >= 2:   # 2%
                score += 30
            elif percent_of_volume >= 1:   # 1%
                score += 25
            elif percent_of_volume >= 0.5: # 0.5%
                score += 20

        # 2. Dollar Value (25%)
        if dollar_value >= 10_000_000: score += 25  # $10M+
        elif dollar_value >= 5_000_000: score += 20 # $5M+
        elif dollar_value >= 1_000_000: score += 15 # $1M+

        # 3. Darkpool Indicator (15%)
        if is_darkpool:
            score += 15

        # 4. Key Level (10%)
        if at_key_level:
            score += 10
        
        # 5. Directional Bias (10%)
        if has_bias:
            score += 10

        return min(score, 100)

    def _check_key_levels(self, price: float, high_52w: Optional[float], low_52w: Optional[float]) -> Optional[str]:
        """Check if a trade occurred near a 52-week high or low"""
        if high_52w and (price / high_52w) >= 0.98: # Within 2% of 52w high
            return f"Near 52-Week High (${high_52w:.2f})"
        if low_52w and (price / low_52w) <= 1.02: # Within 2% of 52w low
            return f"Near 52-Week Low (${low_52w:.2f})"
        return None

    def _infer_directional_bias(self, trade_price: float, market_price: float) -> str:
        """Infer directional bias based on trade price vs market price"""
        diff = (trade_price - market_price) / market_price
        if diff >= 0.001:  # 0.1% above market price
            return "Aggressive Buying"
        if diff <= -0.001: # 0.1% below market price
            return "Aggressive Selling"
        return "Neutral"

    async def _post_signal(self, block: Dict):
        """Post ENHANCED darkpool/block trade signal to Discord"""

        color = 0x9B30FF if block['is_darkpool'] else 0x4169E1
        emoji = "🌑" if block['is_darkpool'] else "🧱"
        trade_type = "DARKPOOL" if block['is_darkpool'] else "BLOCK TRADE"
        
        # Set title based on bias
        bias = block['directional_bias']
        if bias == "Aggressive Buying":
            title = f"{emoji} {block['ticker']} - Aggressive Buying Detected"
            color = 0x00FF00 # Green
        elif bias == "Aggressive Selling":
            title = f"{emoji} {block['ticker']} - Aggressive Selling Detected"
            color = 0xFF0000 # Red
        else:
            title = f"{emoji} {block['ticker']} - Large {trade_type}"

        description = (
            f"**{block['size']:,} shares** worth **${block['dollar_value']:,.0f}** traded.\n"
            f"This represents **{block['percent_of_avg_volume']:.2f}%** of the 30-day average volume."
        )

        fields = [
            {"name": "📈 Block Score", "value": f"**{block['block_score']}/100**", "inline": True},
            {"name": "💵 Executed Price", "value": f"${block['block_price']:.2f}", "inline": True},
            {"name": "📊 Market Price", "value": f"${block['current_price']:.2f}", "inline": True},
        ]

        # Add key level info if present
        if block['key_level_info']:
            fields.append({"name": "🎯 Key Level", "value": block['key_level_info'], "inline": False})
            
        # Add analysis note
        analysis_note = f"A trade of this magnitude suggests significant institutional interest. The execution price was **{bias.lower()}**."
        fields.append({"name": "💡 Analysis", "value": analysis_note, "inline": False})
        
        fields.append({
            "name": "",
            "value": "Please always do your own due diligence on top of these trade ideas.",
            "inline": False
        })

        embed = self.create_embed(
            title=title,
            description=description,
            color=color,
            fields=fields,
            footer=f"{'Darkpool' if block['is_darkpool'] else 'Block Trade'} Bot | Enhanced Institutional Tracker"
        )

        await self.post_to_discord(embed)
        logger.info(f"Posted ENHANCED {trade_type}: {block['ticker']} {block['size']:,} shares @ ${block['block_price']:.2f}")
