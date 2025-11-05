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

    # Configuration constants
    MIN_BLOCK_SIZE = 10000  # Minimum shares for institutional-scale blocks
    KEY_LEVEL_TOLERANCE_PCT = 0.02  # 2% tolerance for 52-week high/low detection
    DIRECTIONAL_BIAS_THRESHOLD_PCT = 0.0005  # 0.05% threshold for aggressive buying/selling
    MIN_DOLLAR_VALUE = 1000000  # Minimum $1M trade value for significant prints
    MIN_BLOCK_COUNT = 1
    BLOCK_SIZE_MULTIPLIER = 1.0  # Trade must meet raw size without multiplier
    MIN_MARKETCAP_RATIO = 0.0  # Informational only; no longer a hard filter

    def __init__(self, webhook_url: str, watchlist: List[str], fetcher: DataFetcher, analyzer: OptionsAnalyzer):
        super().__init__(webhook_url, "Darkpool Bot", scan_interval=Config.DARKPOOL_INTERVAL)
        self.watchlist = watchlist
        self.fetcher = fetcher
        self.analyzer = analyzer
        self.signal_history = {}
        self.MIN_SCORE = max(getattr(Config, 'MIN_DARKPOOL_SCORE', 30), 30)
        self._batch_index = 0
        self._last_watchlist_size = 0
        self.min_total_shares = getattr(Config, 'DARKPOOL_MIN_TOTAL_SHARES', 10000)
        self.min_total_dollar = getattr(Config, 'DARKPOOL_MIN_TOTAL_DOLLAR', 1000000.0)

    def should_run_now(self) -> bool:
        """Override to include pre-market and after-hours darkpool activity."""
        return MarketHours.is_market_open(include_extended=True)

    async def scan_and_post(self):
        """Scan for large darkpool and block trades using concurrent processing"""
        logger.info(f"{self.name} scanning for darkpool activity")

        # Darkpool trades occur throughout extended hours (4:00 AM - 8:00 PM EST)
        # We should scan during all extended hours, not just regular market hours
        # Note: is_market_open() already includes extended hours by default
        if not MarketHours.is_market_open(include_extended=True):
            logger.info(f"{self.name} - Outside extended hours (4 AM - 8 PM EST), skipping scan")
            return

        full_watchlist = getattr(self, 'watchlist', []) or []
        if not full_watchlist:
            logger.info(f"{self.name} watchlist empty, skipping scan")
            return

        batch_size = max(getattr(Config, 'DARKPOOL_BATCH_SIZE', 120), 1)
        total_symbols = len(full_watchlist)

        if total_symbols != self._last_watchlist_size:
            self._batch_index = 0
            self._last_watchlist_size = total_symbols

        total_batches = max((total_symbols + batch_size - 1) // batch_size, 1)
        if self._batch_index >= total_batches:
            self._batch_index = 0

        start = self._batch_index * batch_size
        end = min(start + batch_size, total_symbols)
        batch_symbols = full_watchlist[start:end]

        if not batch_symbols:
            # Fallback to first batch if slicing produced empty list (e.g. watchlist shrank)
            self._batch_index = 0
            total_batches = max((total_symbols + batch_size - 1) // batch_size, 1)
            start = 0
            end = min(batch_size, total_symbols)
            batch_symbols = full_watchlist[start:end]

        batch_label = f"batch {self._batch_index + 1}/{total_batches}" if total_batches > 1 else "single batch"
        logger.info(
            f"{self.name} scanning {batch_label}: {len(batch_symbols)} symbols "
            f"({start + 1}-{start + len(batch_symbols)} of {total_symbols})"
        )

        original_watchlist = self.watchlist

        try:
            self.watchlist = batch_symbols
            # Use base class concurrent implementation on the batch
            await super().scan_and_post()
        finally:
            self.watchlist = original_watchlist
            if total_batches > 0:
                self._batch_index = (self._batch_index + 1) % total_batches
    
    async def _scan_symbol(self, symbol: str) -> List[Dict]:
        """Scan a symbol for darkpool/block trades"""
        return await self._scan_block_trades(symbol)

    async def _scan_block_trades(self, symbol: str) -> List[Dict]:
        """Scan for block trades and darkpool activity with enhanced context"""
        blocks = []
        trades_analyzed = 0
        trades_too_old = 0

        try:
            # --- ENHANCEMENT 1: Get historical context ---
            current_price = await self.fetcher.get_stock_price(symbol)
            if not current_price:
                return blocks
            
            avg_30_day_volume = await self.fetcher.get_30_day_avg_volume(symbol)
            financials = await self.fetcher.get_financials(symbol)
            week_52_high = financials.get('52_week_high') if financials else None
            week_52_low = financials.get('52_week_low') if financials else None
            market_cap = financials.get('market_cap') if financials else None

            # Get recent trades
            trades = await self.fetcher.get_stock_trades(symbol, limit=400)
            if not trades:
                logger.debug(f"{symbol}: No trades found")
                return blocks
            
            logger.debug(f"{symbol}: Found {len(trades)} trades to analyze")

            avg_size = sum(t.get('size', 0) for t in trades) / len(trades) if trades else 0
            recent_cutoff = datetime.now() - timedelta(minutes=45)  # Capture a wider activity window
            
            for trade in trades:
                trade_time = datetime.fromtimestamp(trade.get('timestamp', 0) / 1000)
                if trade_time < recent_cutoff:
                    trades_too_old += 1
                    continue
                
                trades_analyzed += 1

                size = trade.get('size', 0)
                price = trade.get('price', current_price)
                dollar_value = size * price

                size_multiple_ok = avg_size == 0 or size >= (avg_size * self.BLOCK_SIZE_MULTIPLIER)
                is_block = (
                    size >= self.MIN_BLOCK_SIZE and
                    dollar_value >= self.MIN_DOLLAR_VALUE and
                    size_multiple_ok
                )

                if not is_block:
                    continue

                market_cap_ratio = (dollar_value / market_cap) if market_cap and market_cap > 0 else 0

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
                    size, dollar_value, avg_30_day_volume, market_cap_ratio, is_darkpool, 
                    key_level_info is not None, directional_bias != "Neutral"
                )

                if block_score >= self.MIN_SCORE:
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
                        'market_cap_ratio': market_cap_ratio,
                        'key_level_info': key_level_info,
                        'directional_bias': directional_bias,
                    }

                    signal_key = f"{symbol}_{int(trade.get('timestamp', 0))}_{size}"
                    if signal_key not in self.signal_history:
                        blocks.append(block)
                        self.signal_history[signal_key] = datetime.now()
                        logger.info(f"🌑 Darkpool/Block detected: {symbol} - {size:,} shares @ ${price:.2f} (Score: {block_score})")
                else:
                    logger.debug(f"{symbol}: Block trade found but score too low ({block_score} < 45) - {size:,} shares @ ${price:.2f}")

        except Exception as e:
            logger.error(f"Error scanning block trades for {symbol}: {e}")
        
        if trades_analyzed > 0:
            logger.debug(f"{symbol}: Analyzed {trades_analyzed} trades, skipped {trades_too_old} old trades, found {len(blocks)} blocks")

        if len(blocks) < self.MIN_BLOCK_COUNT:
            if blocks:
                self._log_skip(symbol, f'darkpool only {len(blocks)} qualifying blocks (< {self.MIN_BLOCK_COUNT})')
            return []

        total_shares = sum(block['size'] for block in blocks)
        total_dollar_value = sum(block['dollar_value'] for block in blocks)

        if total_shares < self.min_total_shares:
            self._log_skip(symbol, f'darkpool cumulative shares {total_shares:,} below {self.min_total_shares:,}')
            return []

        if total_dollar_value < self.min_total_dollar:
            self._log_skip(symbol, f'darkpool cumulative value ${total_dollar_value:,.0f} below ${self.min_total_dollar:,.0f}')
            return []

        top_block = max(blocks, key=lambda b: b.get('block_score', 0))
        top_block = dict(top_block)  # copy to avoid mutating reference in history
        top_block['total_shares'] = total_shares
        top_block['total_dollar_value'] = total_dollar_value
        top_block['trade_count'] = len(blocks)

        gamma_profile = await self.fetcher.get_gamma_profile(symbol)
        if gamma_profile:
            top_block['gamma_profile'] = gamma_profile

        return [top_block]

    def _calculate_block_score(self, size: int, dollar_value: float,
                               avg_30_day_volume: Optional[float], market_cap_ratio: float, is_darkpool: bool,
                               at_key_level: bool, has_bias: bool) -> int:
        """Calculate ENHANCED block trade significance score using generic scoring"""
        # Calculate percent of volume
        percent_of_volume = 0
        if avg_30_day_volume and avg_30_day_volume > 0:
            percent_of_volume = (size / avg_30_day_volume) * 100

        score = self.calculate_score({
            'volume_percent': (percent_of_volume, [
                (10.0, 40),  # 10%+ of daily volume → 40 points (40%)
                (5.0, 35),   # 5%+ → 35 points
                (2.0, 30),   # 2%+ → 30 points
                (1.0, 25),   # 1%+ → 25 points
                (0.5, 20)    # 0.5%+ → 20 points
            ]),
            'dollar_value': (dollar_value, [
                (10000000, 30),  # $10M+ → 30 points
                (5000000, 25),   # $5M+ → 25 points
                (1000000, 20)    # $1M+ → 20 points
            ]),
            'market_cap_ratio': (market_cap_ratio * 100, [  # convert to percentage for readability
                (0.10, 20),  # 0.10%+ of market cap → 20 points
                (0.05, 15),  # 0.05%+ → 15 points
                (0.03, 10)   # 0.03%+ → 10 points
            ])
        })

        # Darkpool indicator (15%)
        if is_darkpool:
            score += 15

        # Key level (10%)
        if at_key_level:
            score += 10

        # Directional bias (10%)
        if has_bias:
            score += 10

        return min(score, 100)

    def _check_key_levels(self, price: float, high_52w: Optional[float], low_52w: Optional[float]) -> Optional[str]:
        """Check if a trade occurred near a 52-week high or low"""
        tolerance = 1 - self.KEY_LEVEL_TOLERANCE_PCT
        if high_52w and (price / high_52w) >= tolerance:
            return f"Near 52-Week High (${high_52w:.2f})"
        if low_52w and (price / low_52w) <= (2 - tolerance):
            return f"Near 52-Week Low (${low_52w:.2f})"
        return None

    def _infer_directional_bias(self, trade_price: float, market_price: float) -> str:
        """Infer directional bias based on trade price vs market price"""
        diff = (trade_price - market_price) / market_price
        if diff >= self.DIRECTIONAL_BIAS_THRESHOLD_PCT:
            return "Aggressive Buying"
        if diff <= -self.DIRECTIONAL_BIAS_THRESHOLD_PCT:
            return "Aggressive Selling"
        return "Neutral"

    async def _post_signal(self, block: Dict):
        """Post ENHANCED darkpool/block trade signal to Discord"""

        emoji = "🌑" if block['is_darkpool'] else "🧱"
        color = 0x9B30FF if block['is_darkpool'] else 0x4169E1

        title = f"{emoji} {block['ticker']} Block Trade"
        description = f"Large block trade at ${block['block_price']:.2f}"

        fields = [
            {"name": "Shares", "value": f"{block['size']:,}", "inline": True},
            {"name": "Notional", "value": f"${block['dollar_value']:,.0f}", "inline": True},
        ]

        market_price = block.get('current_price')
        if market_price:
            fields.append({"name": "Last", "value": f"${market_price:.2f}", "inline": True})

        bias = block.get('directional_bias')
        if bias and bias != "Neutral":
            fields.append({"name": "Flow Bias", "value": bias, "inline": True})

        if block.get('is_darkpool'):
            fields.append({"name": "Venue", "value": "Dark Pool", "inline": True})

        embed = self.create_signal_embed_with_disclaimer(
            title=title,
            description=description,
            color=color,
            fields=fields,
            footer="Darkpool Bot"
        )

        await self.post_to_discord(embed)
        logger.info(
            f"Posted block signal: {block['ticker']} {block['size']:,} shares @ ${block['block_price']:.2f}"
        )

    @staticmethod
    def _format_gamma_value(value: float) -> str:
        if value is None:
            return "N/A"

        abs_value = abs(value)
        if abs_value >= 1e9:
            return f"{value/1e9:+.1f}B"
        if abs_value >= 1e6:
            return f"{value/1e6:+.1f}M"
        if abs_value >= 1e3:
            return f"{value/1e3:+.0f}K"
        return f"{value:+,.0f}"
