"""Bullseye Bot - AI signal tool for intraday movements"""
import logging
from datetime import datetime, timedelta
from typing import List, Dict
import pandas as pd
from .base_bot import BaseAutoBot
from src.data_fetcher import DataFetcher
from src.options_analyzer import OptionsAnalyzer
from src.config import Config

logger = logging.getLogger(__name__)

class BullseyeBot(BaseAutoBot):
    """
    Bullseye Bot
    AI signal tool that anticipates intraday movements in options contracts
    Focuses on same-day or very short-term expiries with momentum
    """

    def __init__(self, webhook_url: str, watchlist: List[str], fetcher: DataFetcher, analyzer: OptionsAnalyzer):
        super().__init__(webhook_url, "Bullseye Bot", scan_interval=180)  # 3 minutes for intraday
        self.watchlist = watchlist
        self.fetcher = fetcher
        self.analyzer = analyzer
        self.signal_history = {}
        self.price_history = {}  # Track price momentum

    async def scan_and_post(self):
        """Scan for intraday momentum signals"""
        logger.info(f"{self.name} scanning for intraday movements")

        # Only run during market hours
        is_open = await self.fetcher.is_market_open()
        if not is_open:
            logger.debug(f"{self.name} - Market closed")
            return

        for symbol in self.watchlist:
            try:
                signals = await self._scan_intraday_momentum(symbol)
                for signal in signals:
                    await self._post_signal(signal)
            except Exception as e:
                logger.error(f"{self.name} error scanning {symbol}: {e}")

    async def _scan_intraday_momentum(self, symbol: str) -> List[Dict]:
        """PRD Enhanced: Scan with relative volume, smart money, and directional conviction"""
        signals = []

        try:
            # Get current price
            current_price = await self.fetcher.get_stock_price(symbol)
            if not current_price:
                return signals

            # Get options trades (recent only)
            trades = await self.fetcher.get_options_trades(symbol)
            if trades.empty:
                return signals

            # Calculate relative volume vs 20-day baseline (PRD Enhancement #1)
            current_volume = trades['volume'].sum()
            volume_ratio = await self._calculate_relative_volume(symbol, current_volume)

            # Require 3x minimum (PRD requirement)
            if volume_ratio < 3.0:
                logger.debug(f"{symbol}: Volume ratio {volume_ratio:.1f}x below 3x minimum")
                return signals

            # Filter for smart money only ($10k+ trades) (PRD Enhancement #2)
            smart_trades = self._filter_smart_money(trades)

            if smart_trades.empty:
                logger.debug(f"{symbol}: No smart money trades detected")
                return signals

            # Calculate directional conviction (80/20 split) (PRD Enhancement #3)
            call_premium = smart_trades[smart_trades['type'] == 'CALL']['premium'].sum()
            put_premium = smart_trades[smart_trades['type'] == 'PUT']['premium'].sum()

            conviction_data = self._calculate_directional_conviction(call_premium, put_premium)

            # Require 80/20 split (PRD requirement)
            if not conviction_data['passes']:
                logger.debug(f"{symbol}: Directional conviction {conviction_data['split']} below 80/20 minimum")
                return signals

            # Calculate real multi-timeframe momentum
            momentum = await self._calculate_momentum(symbol)

            if momentum is None or momentum['strength'] < 0.2:
                return signals

            # Extract momentum value for backward compatibility
            momentum_value = momentum['momentum_5m']

            # Filter for high activity and near-term expiry
            today = datetime.now()

            recent_trades = smart_trades[
                (smart_trades['timestamp'] > datetime.now() - timedelta(minutes=30))
            ]

            if recent_trades.empty:
                return signals

            # Group by contract - only process ATM/near-money strikes (PRD Enhancement #4)
            for (contract, opt_type, strike, expiration), group in recent_trades.groupby(
                ['contract', 'type', 'strike', 'expiration']
            ):
                exp_date = pd.to_datetime(expiration)

                # Only 0-3 DTE
                days_to_expiry = (exp_date - today).days
                if days_to_expiry < 0 or days_to_expiry > 3:
                    continue

                # Calculate strike distance
                strike_distance = abs(strike - current_price) / current_price * 100

                # ATM/near-money only (within 5%) - PRD requirement
                if strike_distance > 5.0:
                    continue

                total_premium = group['premium'].sum()
                total_volume = group['volume'].sum()
                avg_price = group['price'].mean()
                avg_trade_size = total_premium / len(group)

                # Check momentum alignment with direction
                momentum_aligned = (
                    (momentum['direction'] == 'bullish' and opt_type == 'CALL') or
                    (momentum['direction'] == 'bearish' and opt_type == 'PUT')
                )

                if not momentum_aligned:
                    continue

                # Calculate probability with high volatility assumption
                prob_itm = self.analyzer.calculate_probability_itm(
                    opt_type, strike, current_price, days_to_expiry,
                    implied_volatility=0.5  # Higher IV for intraday
                )

                # Enhanced AI scoring with new factors
                ai_score = self._calculate_enhanced_ai_score(
                    momentum['strength'], total_volume, total_premium, strike_distance,
                    days_to_expiry, volume_ratio, conviction_data['conviction'], avg_trade_size
                )

                # Lower threshold for high-quality signals
                if ai_score >= 70:  # Raised from 60 due to stricter filters
                    signal = {
                        'ticker': symbol,
                        'type': opt_type,
                        'strike': strike,
                        'expiration': expiration,
                        'current_price': current_price,
                        'days_to_expiry': days_to_expiry,
                        'premium': total_premium,
                        'volume': total_volume,
                        'avg_price': avg_price,
                        'momentum': momentum_value,
                        'momentum_5m': momentum['momentum_5m'],
                        'momentum_15m': momentum['momentum_15m'],
                        'volume_ratio': volume_ratio,  # PRD: Relative volume
                        'directional_conviction': conviction_data['conviction'],  # PRD: 80/20 split
                        'conviction_split': conviction_data['split'],
                        'avg_trade_size': avg_trade_size,  # PRD: Smart money indicator
                        'strike_distance': strike_distance,
                        'probability_itm': prob_itm,
                        'ai_score': ai_score
                    }

                    # Check if already posted
                    signal_key = f"{symbol}_{opt_type}_{strike}_{expiration}"
                    if signal_key not in self.signal_history:
                        signals.append(signal)
                        self.signal_history[signal_key] = datetime.now()
                        logger.info(f"✅ Bullseye signal: {symbol} {opt_type} - Vol:{volume_ratio:.1f}x, Conv:{conviction_data['split']}, Score:{ai_score}")

        except Exception as e:
            logger.error(f"Error scanning intraday momentum for {symbol}: {e}")

        return signals

    def _update_price_history(self, symbol: str, price: float):
        """Track recent price history for momentum - DEPRECATED"""
        # This method is no longer used - momentum now calculated from real bars
        pass

    async def _calculate_momentum(self, symbol: str) -> Dict:
        """Calculate REAL momentum with multiple timeframes and volume confirmation"""
        try:
            now = datetime.now()
            # Polygon API requires YYYY-MM-DD format only
            from_date = (now - timedelta(hours=2)).strftime('%Y-%m-%d')
            to_date = now.strftime('%Y-%m-%d')

            # Get 5-minute bars (last 30 minutes = 6 bars)
            bars_5m = await self.fetcher.get_aggregates(
                symbol,
                timespan='minute',
                multiplier=5,
                from_date=from_date,
                to_date=to_date
            )

            # Get 15-minute bars (last 1 hour = 4 bars)
            bars_15m = await self.fetcher.get_aggregates(
                symbol,
                timespan='minute',
                multiplier=15,
                from_date=from_date,
                to_date=to_date
            )

            if bars_5m.empty or bars_15m.empty:
                return None

            # Calculate 5-minute momentum
            momentum_5m = ((bars_5m.iloc[-1]['close'] - bars_5m.iloc[0]['close']) /
                           bars_5m.iloc[0]['close']) * 100

            # Calculate 15-minute momentum
            momentum_15m = ((bars_15m.iloc[-1]['close'] - bars_15m.iloc[0]['close']) /
                            bars_15m.iloc[0]['close']) * 100

            # Volume confirmation
            avg_volume_5m = bars_5m['volume'].mean()
            current_volume = bars_5m.iloc[-1]['volume']
            volume_ratio = current_volume / avg_volume_5m if avg_volume_5m > 0 else 1.0

            # Determine direction and strength
            if momentum_5m > 0 and momentum_15m > 0:
                direction = 'bullish'
                strength = (momentum_5m + momentum_15m) / 2
            elif momentum_5m < 0 and momentum_15m < 0:
                direction = 'bearish'
                strength = abs((momentum_5m + momentum_15m) / 2)
            else:
                direction = 'mixed'
                strength = 0

            return {
                'direction': direction,
                'strength': strength,
                'momentum_5m': momentum_5m,
                'momentum_15m': momentum_15m,
                'volume_ratio': volume_ratio,
                'volume_confirmed': volume_ratio >= 1.5  # 50% above average
            }

        except Exception as e:
            logger.error(f"Error calculating momentum for {symbol}: {e}")
            return None

    async def _calculate_relative_volume(self, symbol: str, current_volume: int) -> float:
        """PRD Enhancement: Calculate volume vs 20-day baseline"""
        try:
            # Get 20-day bars
            bars_20d = await self.fetcher.get_aggregates(
                symbol, 'day', 1,
                (datetime.now() - timedelta(days=25)).strftime('%Y-%m-%d'),
                datetime.now().strftime('%Y-%m-%d')
            )

            if bars_20d.empty:
                return 1.0

            baseline_avg_volume = bars_20d['volume'].mean()

            if baseline_avg_volume > 0:
                volume_ratio = current_volume / baseline_avg_volume
            else:
                volume_ratio = 1.0

            return volume_ratio

        except Exception as e:
            logger.error(f"Error calculating relative volume for {symbol}: {e}")
            return 1.0

    def _calculate_directional_conviction(self, call_premium: float, put_premium: float) -> Dict:
        """PRD Enhancement: Require 80/20 directional split"""
        total = call_premium + put_premium

        if total == 0:
            return {'conviction': 0, 'direction': 'NEUTRAL', 'split': '0/0', 'passes': False}

        call_pct = call_premium / total
        put_pct = put_premium / total

        # Check for 80/20 split
        if call_pct >= 0.80:
            return {
                'conviction': call_pct,
                'direction': 'BULLISH',
                'split': f"{call_pct*100:.0f}/{put_pct*100:.0f}",
                'passes': True
            }
        elif put_pct >= 0.80:
            return {
                'conviction': put_pct,
                'direction': 'BEARISH',
                'split': f"{call_pct*100:.0f}/{put_pct*100:.0f}",
                'passes': True
            }
        else:
            return {
                'conviction': max(call_pct, put_pct),
                'direction': 'MIXED',
                'split': f"{call_pct*100:.0f}/{put_pct*100:.0f}",
                'passes': False
            }

    def _filter_smart_money(self, trades_df: pd.DataFrame) -> pd.DataFrame:
        """PRD Enhancement: Filter for smart money trades ($10k+ avg)"""
        if trades_df.empty:
            return trades_df

        # Calculate premium if not already present
        if 'premium' not in trades_df.columns:
            trades_df['premium'] = trades_df['price'] * trades_df['size'] * 100

        # Filter for $10k+ trades
        smart_money = trades_df[trades_df['premium'] >= 10_000]

        return smart_money

    def _calculate_enhanced_ai_score(self, momentum: float, volume: int, premium: float,
                                    strike_distance: float, dte: int, volume_ratio: float,
                                    conviction: float, avg_trade_size: float) -> int:
        """PRD Enhanced: AI scoring with new factors"""
        score = 0

        # Momentum strength (30%)
        if abs(momentum) >= 2.0:
            score += 30
        elif abs(momentum) >= 1.0:
            score += 22
        elif abs(momentum) >= 0.5:
            score += 15

        # Volume intensity (20%)
        if volume >= 500:
            score += 20
        elif volume >= 200:
            score += 15
        elif volume >= 100:
            score += 10

        # Premium flow (15%)
        if premium >= 50000:
            score += 15
        elif premium >= 20000:
            score += 11
        elif premium >= 10000:
            score += 7

        # Relative volume (15% - NEW PRD factor)
        if volume_ratio >= 5.0:
            score += 15
        elif volume_ratio >= 4.0:
            score += 12
        elif volume_ratio >= 3.0:
            score += 9

        # Directional conviction (10% - NEW PRD factor)
        if conviction >= 0.90:  # 90/10 split
            score += 10
        elif conviction >= 0.85:  # 85/15 split
            score += 8
        elif conviction >= 0.80:  # 80/20 split
            score += 6

        # Smart money size (5% - NEW PRD factor)
        if avg_trade_size >= 50_000:
            score += 5
        elif avg_trade_size >= 25_000:
            score += 3
        elif avg_trade_size >= 10_000:
            score += 2

        # Strike proximity (3%)
        if strike_distance <= 1:
            score += 3
        elif strike_distance <= 3:
            score += 2

        # DTE factor (2%)
        if dte == 0:
            score += 2
        elif dte <= 1:
            score += 1

        return score

    def _calculate_ai_score(self, momentum: float, volume: int, premium: float,
                           strike_distance: float, dte: int) -> int:
        """DEPRECATED: Legacy AI scoring algorithm - use _calculate_enhanced_ai_score"""
        score = 0

        # Momentum strength (40%)
        if abs(momentum) >= 2.0:
            score += 40
        elif abs(momentum) >= 1.0:
            score += 30
        elif abs(momentum) >= 0.5:
            score += 20

        # Volume intensity (25%)
        if volume >= 500:
            score += 25
        elif volume >= 200:
            score += 20
        elif volume >= 100:
            score += 15

        # Premium flow (20%)
        if premium >= 50000:
            score += 20
        elif premium >= 20000:
            score += 15
        elif premium >= 10000:
            score += 10

        # Strike proximity (10%)
        if strike_distance <= 1:
            score += 10
        elif strike_distance <= 3:
            score += 7

        # DTE factor (5%)
        if dte == 0:
            score += 5
        elif dte <= 1:
            score += 4

        return score

    async def _post_signal(self, signal: Dict):
        """Post Bullseye signal to Discord"""
        # Teal/turquoise color like in the image
        color = 0x5DADE2

        # Format expiration date
        exp_date = pd.to_datetime(signal.get('expiration', datetime.now()))
        exp_str = exp_date.strftime('%m/%d/%Y')

        # Determine Call/Put
        call_put = "Call" if signal['type'] == 'CALL' else "Put"

        # Determine Buy/Sell (for Bullseye, these are always Buy signals)
        buy_sell = "Buy"

        # Format premium in M if over 1M, otherwise in K
        premium = signal['premium']
        if premium >= 1000000:
            prem_str = f"{premium/1000000:.2f}M"
        elif premium >= 1000:
            prem_str = f"{premium/1000:.0f}K"
        else:
            prem_str = f"{premium:.0f}"

        # OI (Open Interest) - placeholder if not available
        oi = signal.get('open_interest', 'N/A')

        # Volume
        volume = signal['volume']

        embed = self.create_embed(
            title=f"∞ Bullseye Trade Idea",
            description=f"Expected to pan out within 1-2 days.",
            color=color,
            fields=[
                {
                    "name": "Symbol",
                    "value": signal['ticker'],
                    "inline": True
                },
                {
                    "name": "Strike",
                    "value": f"{signal['strike']:.1f}",
                    "inline": True
                },
                {
                    "name": "Expiration",
                    "value": exp_str,
                    "inline": True
                },
                {
                    "name": "Call/Put",
                    "value": call_put,
                    "inline": True
                },
                {
                    "name": "Buy/Sell",
                    "value": buy_sell,
                    "inline": True
                },
                {
                    "name": "AI Confidence",
                    "value": f"{signal['ai_score']:.2f}%",
                    "inline": True
                },
                {
                    "name": "Prems Spent",
                    "value": prem_str,
                    "inline": True
                },
                {
                    "name": "Volume",
                    "value": f"{volume:,}",
                    "inline": True
                },
                {
                    "name": "OI",
                    "value": str(oi),
                    "inline": True
                }
            ]
        )

        # Add disclaimer footer
        embed['fields'].append({
            "name": "∞",
            "value": "Please always do your own due diligence on top of these trade ideas. For shorter term expirations, it is better to add some extra time.",
            "inline": False
        })

        embed['footer'] = f"ORAKL Bot - Bullseye • {datetime.now().strftime('%m/%d/%Y')}"

        await self.post_to_discord(embed)
        logger.info(f"Posted Bullseye signal: {signal['ticker']} {signal['type']} ${signal['strike']} Score:{signal['ai_score']}")
