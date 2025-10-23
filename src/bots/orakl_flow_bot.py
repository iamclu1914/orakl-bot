"""Orakl Flow Bot - Repeat and dominant options signals"""
import logging
from datetime import datetime
from typing import List, Dict
from .base_bot import BaseAutoBot
from src.data_fetcher import DataFetcher
from src.options_analyzer import OptionsAnalyzer
from src.config import Config
from src.utils.market_hours import MarketHours

logger = logging.getLogger(__name__)

class TradyFlowBot(BaseAutoBot):
    """
    Orakl Flow Bot
    Looks at repeat and dominant options signals with high success rate of hitting ITM
    """

    def __init__(self, webhook_url: str, watchlist: List[str], fetcher: DataFetcher, analyzer: OptionsAnalyzer):
        super().__init__(webhook_url, "Orakl Flow Bot", scan_interval=300)  # 5 minutes
        self.watchlist = watchlist
        self.fetcher = fetcher
        self.analyzer = analyzer
        self.signal_history = {}

    async def scan_and_post(self):
        """Scan for repeat and dominant signals using concurrent processing"""
        logger.info(f"{self.name} scanning {len(self.watchlist)} symbols")

        # Only scan during market hours (9:30 AM - 4:00 PM EST, Monday-Friday)
        if not MarketHours.is_market_open():
            logger.debug(f"{self.name} - Market closed, skipping scan")
            return
        
        # Use base class concurrent implementation
        await super().scan_and_post()

    async def _scan_symbol(self, symbol: str) -> List[Dict]:
        """
        Scan a symbol for repeat/dominant signals using efficient REST flow detection.

        NEW APPROACH (REST):
        - Uses detect_unusual_flow() for efficient volume delta detection
        - Single API call per symbol (vs 50+ in old approach)
        - Detects flows via volume changes between polling intervals
        """
        signals = []

        try:
            # Get current price for context
            current_price = await self.fetcher.get_stock_price(symbol)
            if not current_price:
                return signals

            # NEW: Use efficient flow detection (single API call)
            flows = await self.fetcher.detect_unusual_flow(
                underlying=symbol,
                min_premium=1000,  # $1K minimum for testing (was Config.MIN_PREMIUM $10K)
                min_volume_delta=5  # At least 5 contracts of volume change (was 10)
            )

            if not flows:
                return signals

            # Process each flow signal
            for flow in flows:
                try:
                    # Extract flow data
                    contract_ticker = flow['ticker']
                    opt_type = flow['type']
                    strike = flow['strike']
                    expiration = flow['expiration']
                    premium = flow['premium']
                    volume = flow['volume_delta']

                    # Calculate days to expiry
                    exp_date = datetime.strptime(expiration, '%Y-%m-%d')
                    days_to_expiry = (exp_date - datetime.now()).days

                    # Filter: Valid DTE range (1-45 days)
                    if days_to_expiry <= 0 or days_to_expiry > 45:
                        continue

                    # Check for repeat signals
                    repeat_count = self.analyzer.identify_repeat_signals(
                        symbol, strike, opt_type, expiration, premium
                    )

                    # Must have at least 3 repeat signals for ORAKL Flow
                    if repeat_count < 3:
                        continue

                    # Calculate probability ITM
                    prob_itm = self.analyzer.calculate_probability_itm(
                        opt_type, strike, current_price, days_to_expiry
                    )

                    # High probability threshold (minimum 50%)
                    if prob_itm < 50:
                        continue

                    # Create signal
                    signal = {
                        'ticker': symbol,
                        'contract': contract_ticker,
                        'type': opt_type,
                        'strike': strike,
                        'expiration': expiration,
                        'current_price': current_price,
                        'underlying_price': flow.get('underlying_price', current_price),
                        'days_to_expiry': days_to_expiry,
                        'premium': premium,
                        'volume': volume,
                        'total_volume': flow.get('total_volume', volume),
                        'open_interest': flow.get('open_interest', 0),
                        'repeat_count': repeat_count,
                        'probability_itm': prob_itm,
                        'implied_volatility': flow.get('implied_volatility', 0),
                        'delta': flow.get('delta', 0)
                    }

                    # Check if already posted (deduplication)
                    signal_key = f"{symbol}_{opt_type}_{strike}_{expiration}"
                    if signal_key not in self.signal_history:
                        signals.append(signal)
                        self.signal_history[signal_key] = datetime.now()
                        logger.info(
                            f"ORAKL Flow detected: {symbol} {opt_type} ${strike} "
                            f"(Premium: ${premium:,.0f}, Repeats: {repeat_count}, "
                            f"ITM Prob: {prob_itm:.1f}%)"
                        )

                except Exception as e:
                    logger.debug(f"Error processing flow for {symbol}: {e}")
                    continue

        except Exception as e:
            logger.error(f"Error scanning {symbol} for ORAKL Flow: {e}")

        return signals

    async def _post_signal(self, signal: Dict):
        """Post Orakl Flow signal to Discord"""
        color = 0x00FF00 if signal['type'] == 'CALL' else 0xFF0000
        emoji = "🟢" if signal['type'] == 'CALL' else "🔴"

        # Build fields
        fields = [
            {"name": "📊 Contract", "value": f"{signal['type']} ${signal['strike']}\nExp: {signal['expiration']}", "inline": True},
            {"name": "🎲 Probability ITM", "value": f"**{signal['probability_itm']:.1f}%**", "inline": True},
            {"name": "💰 Premium Flow", "value": f"${signal['premium']:,.0f}", "inline": True},
            {"name": "📈 Current Price", "value": f"${signal['current_price']:.2f}", "inline": True},
            {"name": "📊 Volume", "value": f"{signal['volume']:,}", "inline": True},
            {"name": "🔄 Repeat Signals", "value": f"{signal['repeat_count']} detected", "inline": True},
            {"name": "🎯 Target", "value": f"{'Break above' if signal['type'] == 'CALL' else 'Break below'} ${signal['strike']:.2f}", "inline": False},
            {"name": "⏰ Days to Expiry", "value": f"{signal['days_to_expiry']} days", "inline": True}
        ]

        # Create embed with auto-disclaimer
        embed = self.create_signal_embed_with_disclaimer(
            title=f"{emoji} Orakl Flow: {signal['ticker']}",
            description=f"Repeat dominant {signal['type']} signal detected",
            color=color,
            fields=fields,
            footer="Orakl Flow Bot | High ITM Success Rate"
        )

        await self.post_to_discord(embed)
        logger.info(f"Posted Orakl Flow signal: {signal['ticker']} {signal['type']} ${signal['strike']}")
