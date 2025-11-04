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
        self.MIN_TOTAL_PREMIUM = 750000
        self.MIN_UNIQUE_CONTRACTS = 3
        self.MAX_STRIKE_DISTANCE = 5  # percent
        self.MIN_PROB_ITM = 75  # Require high probability ITM
        self.MIN_SUCCESS_RATE = getattr(Config, 'SUCCESS_RATE_THRESHOLD', 0.8)
        self.DOMINANT_PREMIUM_RATIO = 1.5
        self.MIN_TRADE_PREMIUM = 50000

    async def scan_and_post(self):
        """Scan for repeat and dominant signals using concurrent processing"""
        logger.info(f"{self.name} scanning {len(self.watchlist)} symbols")

        # Only scan during market hours (9:30 AM - 4:00 PM EST, Monday-Friday)
        if not MarketHours.is_market_open(include_extended=False):
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
                min_premium=self.MIN_TRADE_PREMIUM,
                min_volume_delta=10
            )

            if not flows:
                return signals

            flows_by_type = {'CALL': [], 'PUT': []}
            premium_by_type = {'CALL': 0.0, 'PUT': 0.0}
            contract_ids_by_type = {'CALL': set(), 'PUT': set()}

            for flow in flows:
                premium = flow.get('premium', 0.0)
                if premium < self.MIN_TRADE_PREMIUM:
                    self._log_skip(symbol, f"orakl flow premium ${premium:,.0f} below ${self.MIN_TRADE_PREMIUM:,.0f}")
                    continue
                strike = flow['strike']
                strike_distance = abs(strike - current_price) / current_price * 100
                if strike_distance > self.MAX_STRIKE_DISTANCE:
                    self._log_skip(symbol, f"orakl strike distance {strike_distance:.1f}% exceeds {self.MAX_STRIKE_DISTANCE}%")
                    continue
                opt_type = flow['type']
                flows_by_type[opt_type].append(flow)
                contract_ids_by_type[opt_type].add(flow['ticker'])
                premium_by_type[opt_type] += premium

            dominant_type = 'CALL' if premium_by_type['CALL'] >= premium_by_type['PUT'] else 'PUT'
            dominant_premium = premium_by_type[dominant_type]
            secondary_premium = premium_by_type['PUT' if dominant_type == 'CALL' else 'CALL']

            if dominant_premium == 0:
                return signals

            if dominant_premium < self.MIN_TOTAL_PREMIUM:
                self._log_skip(symbol, f"orakl dominant {dominant_type} premium ${dominant_premium:,.0f} below ${self.MIN_TOTAL_PREMIUM:,.0f}")
                return signals

            if secondary_premium > 0 and (dominant_premium / secondary_premium) < self.DOMINANT_PREMIUM_RATIO:
                self._log_skip(symbol, f"orakl dominant premium ratio {dominant_premium/secondary_premium:.2f} < {self.DOMINANT_PREMIUM_RATIO}")
                return signals

            dominant_contracts = len(contract_ids_by_type[dominant_type])
            if dominant_contracts < self.MIN_UNIQUE_CONTRACTS:
                self._log_skip(symbol, f"orakl only {dominant_contracts} unique {dominant_type} contracts")
                return signals

            success_rate = self.analyzer.calculate_success_rate(symbol)
            if success_rate < self.MIN_SUCCESS_RATE:
                self._log_skip(symbol, f"orakl success rate {success_rate:.2%} below {self.MIN_SUCCESS_RATE:.2%}")
                return signals

            dominant_flows = flows_by_type[dominant_type]

            # Process each flow signal in dominant direction
            for flow in dominant_flows:
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

                    # Filter: Valid DTE range (1-21 days)
                    if days_to_expiry <= 0 or days_to_expiry > 21:
                        continue

                    # Check for repeat signals
                    repeat_count = self.analyzer.identify_repeat_signals(
                        symbol, strike, opt_type, expiration, premium
                    )

                    # Must have at least 10 repeat signals for ORAKL Flow
                    if repeat_count < 10:
                        continue

                    # Calculate probability ITM
                    prob_itm = self.analyzer.calculate_probability_itm(
                        opt_type, strike, current_price, days_to_expiry
                    )

                    # High probability threshold (minimum configured)
                    if prob_itm < self.MIN_PROB_ITM:
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
                        'delta': flow.get('delta', 0),
                        'dominant_type': dominant_type,
                        'success_rate': success_rate
                    }

                    # Check if already posted (deduplication)
                    signal_key = f"{symbol}_{opt_type}_{strike}_{expiration}"
                    if self._cooldown_active(signal_key):
                        self._log_skip(symbol, f"orakl cooldown {signal_key}")
                        continue

                    if signal_key not in self.signal_history:
                        signals.append(signal)
                        self.signal_history[signal_key] = datetime.now()
                        self._mark_cooldown(signal_key)
                        logger.info(
                            f"ORAKL Flow detected: {symbol} {opt_type} ${strike} "
                            f"(Premium: ${premium:,.0f}, Repeats: {repeat_count}, "
                            f"ITM Prob: {prob_itm:.1f}%, Success:{success_rate:.1%})"
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
            {"name": "📈 Success Rate", "value": f"{signal['success_rate']*100:.0f}%", "inline": True},
            {"name": "💰 Premium Flow", "value": f"${signal['premium']:,.0f}", "inline": True},
            {"name": "📈 Current Price", "value": f"${signal['current_price']:.2f}", "inline": True},
            {"name": "📊 Volume", "value": f"{signal['volume']:,}", "inline": True},
            {"name": "🔄 Repeat Signals", "value": f"{signal['repeat_count']} detected", "inline": True},
            {"name": "🏹 Dominant Flow", "value": signal.get('dominant_type', 'N/A'), "inline": True},
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
