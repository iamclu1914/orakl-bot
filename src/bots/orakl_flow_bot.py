"""Orakl Flow Bot - Repeat and dominant options signals"""
import logging
from datetime import datetime
from typing import List, Dict
from .base_bot import BaseAutoBot
from src.data_fetcher import DataFetcher
from src.options_analyzer import OptionsAnalyzer
from src.config import Config

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
        """Scan for repeat and dominant signals"""
        logger.info(f"{self.name} scanning {len(self.watchlist)} symbols")

        # Check market hours
        is_open = await self.fetcher.is_market_open()
        if not is_open:
            logger.debug(f"{self.name} - Market closed")
            return

        for symbol in self.watchlist:
            try:
                signals = await self._scan_symbol(symbol)
                for signal in signals:
                    await self._post_signal(signal)
            except Exception as e:
                logger.error(f"{self.name} error scanning {symbol}: {e}")

    async def _scan_symbol(self, symbol: str) -> List[Dict]:
        """Scan a symbol for repeat/dominant signals"""
        signals = []

        try:
            # Get current price
            current_price = await self.fetcher.get_stock_price(symbol)
            if not current_price:
                return signals

            # Get options trades
            trades = await self.fetcher.get_options_trades(symbol)
            if trades.empty:
                return signals

            # Filter significant trades
            significant = trades[
                (trades['premium'] >= Config.MIN_PREMIUM) &
                (trades['volume'] >= Config.MIN_VOLUME)
            ]

            # Group by contract
            for (contract, opt_type, strike, expiration), group in significant.groupby(
                ['contract', 'type', 'strike', 'expiration']
            ):
                total_premium = group['premium'].sum()
                total_volume = group['volume'].sum()

                # Check for repeat signals
                repeat_count = self.analyzer.identify_repeat_signals(
                    symbol, strike, opt_type, expiration, total_premium
                )

                # Must have at least 3 repeat signals
                if repeat_count < 3:
                    continue

                # Calculate days to expiry
                exp_date = datetime.strptime(expiration, '%Y-%m-%d')
                days_to_expiry = (exp_date - datetime.now()).days

                if days_to_expiry <= 0 or days_to_expiry > 45:
                    continue

                # Calculate probability ITM
                prob_itm = self.analyzer.calculate_probability_itm(
                    opt_type, strike, current_price, days_to_expiry
                )

                # High probability threshold
                if prob_itm >= 65:
                    signal = {
                        'ticker': symbol,
                        'type': opt_type,
                        'strike': strike,
                        'expiration': expiration,
                        'current_price': current_price,
                        'days_to_expiry': days_to_expiry,
                        'premium': total_premium,
                        'volume': total_volume,
                        'repeat_count': repeat_count,
                        'probability_itm': prob_itm
                    }

                    # Check if already posted
                    signal_key = f"{symbol}_{opt_type}_{strike}_{expiration}"
                    if signal_key not in self.signal_history:
                        signals.append(signal)
                        self.signal_history[signal_key] = datetime.now()

        except Exception as e:
            logger.error(f"Error scanning {symbol}: {e}")

        return signals

    async def _post_signal(self, signal: Dict):
        """Post Orakl Flow signal to Discord"""
        color = 0x00FF00 if signal['type'] == 'CALL' else 0xFF0000
        emoji = "🟢" if signal['type'] == 'CALL' else "🔴"

        embed = self.create_embed(
            title=f"{emoji} Orakl Flow: {signal['ticker']}",
            description=f"Repeat dominant {signal['type']} signal detected",
            color=color,
            fields=[
                {
                    "name": "📊 Contract",
                    "value": f"{signal['type']} ${signal['strike']}\nExp: {signal['expiration']}",
                    "inline": True
                },
                {
                    "name": "🎲 Probability ITM",
                    "value": f"**{signal['probability_itm']:.1f}%**",
                    "inline": True
                },
                {
                    "name": "💰 Premium Flow",
                    "value": f"${signal['premium']:,.0f}",
                    "inline": True
                },
                {
                    "name": "📈 Current Price",
                    "value": f"${signal['current_price']:.2f}",
                    "inline": True
                },
                {
                    "name": "📊 Volume",
                    "value": f"{signal['volume']:,}",
                    "inline": True
                },
                {
                    "name": "🔄 Repeat Signals",
                    "value": f"{signal['repeat_count']} detected",
                    "inline": True
                },
                {
                    "name": "🎯 Target",
                    "value": f"{'Break above' if signal['type'] == 'CALL' else 'Break below'} ${signal['strike']:.2f}",
                    "inline": False
                },
                {
                    "name": "⏰ Days to Expiry",
                    "value": f"{signal['days_to_expiry']} days",
                    "inline": True
                },
                {
                    "name": "",
                    "value": "Please always do your own due diligence on top of these trade ideas.",
                    "inline": False
                }
            ],
            footer="Orakl Flow Bot | High ITM Success Rate"
        )

        await self.post_to_discord(embed)
        logger.info(f"Posted Orakl Flow signal: {signal['ticker']} {signal['type']} ${signal['strike']}")
