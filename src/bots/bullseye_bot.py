"""Bullseye Bot - AI signal tool for intraday movements"""
import logging
from datetime import datetime, timedelta
from typing import List, Dict
import pandas as pd
import asyncio
import numpy as np
from .base_bot import BaseAutoBot
from src.data_fetcher import DataFetcher
from src.options_analyzer import OptionsAnalyzer
from src.config import Config
from src.utils.market_hours import MarketHours
from src.utils.market_context import MarketContext
from src.utils.exit_strategies import ExitStrategies

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
        """Enhanced scan with market context and concurrent processing"""
        logger.info(f"{self.name} scanning for intraday movements")

        # Only scan during market hours (9:30 AM - 4:00 PM EST, Monday-Friday)
        if not MarketHours.is_market_open():
            logger.debug(f"{self.name} - Market closed, skipping scan")
            return
        
        # Get market context
        market_context = await MarketContext.get_market_context(self.fetcher)
        logger.info(f"{self.name} - Market: {market_context['regime']}, Risk: {market_context['risk_level']}")
        
        # Adjust threshold based on market conditions (minimum 50%)
        base_threshold = 50  # Base AI score threshold (50% minimum)
        adjusted_threshold = max(50, MarketContext.adjust_signal_threshold(base_threshold, market_context))
        logger.debug(f"{self.name} - Adjusted threshold: {adjusted_threshold} (base: {base_threshold})")
        
        # Batch processing for efficiency
        batch_size = 8
        all_signals = []
        
        for i in range(0, len(self.watchlist), batch_size):
            batch = self.watchlist[i:i+batch_size]
            
            # Concurrent scanning within batch
            tasks = [self._scan_intraday_momentum(symbol, market_context, adjusted_threshold) 
                    for symbol in batch]
            batch_results = await asyncio.gather(*tasks, return_exceptions=True)
            
            for signals in batch_results:
                if isinstance(signals, list):
                    all_signals.extend(signals)
        
        # Apply quality filters and rank signals
        filtered_signals = [sig for sig in all_signals if self.apply_quality_filters(sig)]
        top_signals = self.rank_signals(filtered_signals)
        
        # Post top signals
        for signal in top_signals:
            await self._post_signal(signal)

    async def _scan_intraday_momentum(self, symbol: str, market_context: Dict = None,
                                     adjusted_threshold: int = 50) -> List[Dict]:
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

            # Require above-average volume (2x for strong institutional interest)
            if volume_ratio < 2.0:
                logger.debug(f"{symbol}: Volume ratio {volume_ratio:.1f}x below 2x minimum")
                return signals

            # Filter for smart money only ($10k+ trades) (PRD Enhancement #2)
            smart_trades = self._filter_smart_money(trades)

            if smart_trades.empty:
                logger.debug(f"{symbol}: No smart money trades detected")
                return signals

            # Calculate directional conviction (70/30 split for strong bias)
            call_premium = smart_trades[smart_trades['type'] == 'CALL']['premium'].sum()
            put_premium = smart_trades[smart_trades['type'] == 'PUT']['premium'].sum()

            conviction_data = self._calculate_directional_conviction(call_premium, put_premium)

            # Require 70/30 split (strong directional bias)
            if not conviction_data['passes']:
                logger.debug(f"{symbol}: Directional conviction {conviction_data['split']} below 70/30 minimum")
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
                if ai_score >= adjusted_threshold:
                    # Analyze order flow
                    flow_analysis = await self._analyze_order_flow(symbol, group)
                    
                    # Calculate exit strategies
                    exits = ExitStrategies.calculate_exits(
                        'bullseye', avg_price, current_price, opt_type,
                        atr=current_price * 0.02, dte=days_to_expiry
                    )
                    
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
                        'momentum_accelerating': momentum['momentum_accelerating'],
                        'volume_ratio': volume_ratio,  # PRD: Relative volume
                        'directional_conviction': conviction_data['conviction'],  # PRD: 80/20 split
                        'conviction_split': conviction_data['split'],
                        'avg_trade_size': avg_trade_size,  # PRD: Smart money indicator
                        'strike_distance': strike_distance,
                        'probability_itm': prob_itm,
                        'ai_score': ai_score,
                        'flow_analysis': flow_analysis,
                        'sweep_detected': flow_analysis['sweep_detected'],
                        'stop_loss': exits['stop_loss'],
                        'target_1': exits['target_1'],
                        'target_2': exits['target_2'],
                        'target_3': exits.get('target_3'),
                        'risk_reward_1': exits['risk_reward_1'],
                        'risk_reward_2': exits['risk_reward_2'],
                        'exit_strategy': exits,
                        'market_context': market_context
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
        """Enhanced momentum calculation with volume weighting and divergence detection"""
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

            # Calculate standard momentum
            momentum_5m = ((bars_5m.iloc[-1]['close'] - bars_5m.iloc[0]['close']) /
                           bars_5m.iloc[0]['close']) * 100

            momentum_15m = ((bars_15m.iloc[-1]['close'] - bars_15m.iloc[0]['close']) /
                            bars_15m.iloc[0]['close']) * 100

            # Calculate volume-weighted momentum
            vwap_5m = (bars_5m['close'] * bars_5m['volume']).sum() / bars_5m['volume'].sum()
            vw_momentum_5m = ((bars_5m.iloc[-1]['close'] - vwap_5m) / vwap_5m) * 100

            # Check for momentum acceleration
            if len(bars_5m) >= 3:
                recent_momentum = ((bars_5m.iloc[-1]['close'] - bars_5m.iloc[-3]['close']) /
                                 bars_5m.iloc[-3]['close']) * 100
                older_momentum = ((bars_5m.iloc[-3]['close'] - bars_5m.iloc[-5]['close']) /
                                bars_5m.iloc[-5]['close']) * 100 if len(bars_5m) >= 5 else 0
                accelerating = abs(recent_momentum) > abs(older_momentum)
            else:
                accelerating = False

            # Check for momentum divergence
            price_trend = momentum_5m > 0
            volume_trend = bars_5m.iloc[-3:]['volume'].mean() > bars_5m.iloc[:-3]['volume'].mean()
            divergence = (price_trend and not volume_trend) or (not price_trend and volume_trend)

            # Volume analysis
            avg_volume_5m = bars_5m['volume'].mean()
            current_volume = bars_5m.iloc[-1]['volume']
            volume_ratio = current_volume / avg_volume_5m if avg_volume_5m > 0 else 1.0

            # Determine direction and strength
            if momentum_5m > 0 and momentum_15m > 0:
                direction = 'bullish'
                strength = (abs(momentum_5m) + abs(momentum_15m) + abs(vw_momentum_5m)) / 3
            elif momentum_5m < 0 and momentum_15m < 0:
                direction = 'bearish'
                strength = (abs(momentum_5m) + abs(momentum_15m) + abs(vw_momentum_5m)) / 3
            else:
                direction = 'mixed'
                strength = 0

            return {
                'direction': direction,
                'strength': strength,
                'momentum_5m': momentum_5m,
                'momentum_15m': momentum_15m,
                'vw_momentum_5m': vw_momentum_5m,
                'volume_ratio': volume_ratio,
                'volume_confirmed': volume_ratio >= 1.5,
                'momentum_accelerating': accelerating,
                'divergence': divergence
            }

        except Exception as e:
            logger.error(f"Error calculating momentum for {symbol}: {e}")
            return None
    
    async def _analyze_order_flow(self, symbol: str, trades_df: pd.DataFrame) -> Dict:
        """Analyze order flow for sweep patterns and buy/sell pressure"""
        try:
            if trades_df.empty:
                return {'sweep_detected': False, 'buy_pressure': 0.5}
            
            # Identify large block trades (>$100k)
            block_trades = trades_df[trades_df['premium'] >= 100_000]
            
            # Check for sweep patterns (multiple exchanges hit quickly)
            recent_trades = trades_df[trades_df['timestamp'] > datetime.now() - timedelta(minutes=5)]
            
            sweep_detected = False
            if len(recent_trades) >= 5:
                # Check if trades hit multiple exchanges in quick succession
                time_spread = (recent_trades['timestamp'].max() - recent_trades['timestamp'].min()).total_seconds()
                if time_spread < 60 and recent_trades['exchange'].nunique() >= 3:
                    sweep_detected = True
            
            # Calculate buy/sell pressure
            call_premium = trades_df[trades_df['type'] == 'CALL']['premium'].sum()
            put_premium = trades_df[trades_df['type'] == 'PUT']['premium'].sum()
            total_premium = call_premium + put_premium
            
            buy_pressure = call_premium / total_premium if total_premium > 0 else 0.5
            
            # Identify aggressive orders (at ask)
            # Note: This is simplified - real implementation would need bid/ask data
            aggressive_ratio = len(trades_df[trades_df['price'] > trades_df['price'].median()]) / len(trades_df)
            
            return {
                'sweep_detected': sweep_detected,
                'buy_pressure': buy_pressure,
                'block_trades_count': len(block_trades),
                'block_trades_value': block_trades['premium'].sum(),
                'aggressive_ratio': aggressive_ratio,
                'flow_direction': 'bullish' if buy_pressure > 0.7 else 'bearish' if buy_pressure < 0.3 else 'neutral'
            }
            
        except Exception as e:
            logger.error(f"Error analyzing order flow for {symbol}: {e}")
            return {'sweep_detected': False, 'buy_pressure': 0.5}

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
        """Calculate directional conviction - requires 70/30 split for strong bias"""
        total = call_premium + put_premium

        if total == 0:
            return {'conviction': 0, 'direction': 'NEUTRAL', 'split': '0/0', 'passes': False}

        call_pct = call_premium / total
        put_pct = put_premium / total

        # Check for 70/30 split (strong directional bias)
        if call_pct >= 0.70:
            return {
                'conviction': call_pct,
                'direction': 'BULLISH',
                'split': f"{call_pct*100:.0f}/{put_pct*100:.0f}",
                'passes': True
            }
        elif put_pct >= 0.70:
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
        """Post enhanced Bullseye signal to Discord"""
        # Teal/turquoise color like in the image
        color = 0x5DADE2

        # Format expiration date
        exp_date = pd.to_datetime(signal.get('expiration', datetime.now()))
        exp_str = exp_date.strftime('%m/%d/%Y')

        # Format priority
        priority_level = "URGENT" if signal.get('priority_score', 0) >= 85 else "HIGH" if signal.get('priority_score', 0) >= 75 else "MEDIUM"

        # Format smart money
        smart_money = signal['premium']
        if smart_money >= 1000000:
            smart_str = f"${smart_money/1000000:.1f}M"
        else:
            smart_str = f"${smart_money/1000:.0f}K"

        # Format momentum
        momentum_str = f"{'Accelerating' if signal.get('momentum_accelerating', False) else ''} {signal['momentum_5m']:+.1f}%"

        # Market context
        market = signal.get('market_context', {})
        market_status = f"{market.get('regime', 'normal').replace('_', ' ').title()}"

        embed = self.create_embed(
            title=f"🎯 Bullseye: {signal['ticker']}",
            description=f"AI Score: **{signal['ai_score']:.0f}%** | Priority: **{priority_level}**",
            color=color,
            fields=[
                {
                    "name": "📊 Contract",
                    "value": f"{signal['type']} ${signal['strike']} {signal['days_to_expiry']}DTE\n{exp_str}",
                    "inline": True
                },
                {
                    "name": "💰 Smart Money",
                    "value": f"{smart_str} ({signal['conviction_split']} split)",
                    "inline": True
                },
                {
                    "name": "📈 Momentum",
                    "value": momentum_str,
                    "inline": True
                },
                {
                    "name": "💵 Entry Zone",
                    "value": f"${signal['exit_strategy']['entry_zone']['lower']:.2f} - ${signal['exit_strategy']['entry_zone']['upper']:.2f}",
                    "inline": True
                },
                {
                    "name": "🛑 Stop Loss",
                    "value": f"${signal['stop_loss']:.2f}",
                    "inline": True
                },
                {
                    "name": "🎯 Targets",
                    "value": f"T1: ${signal['target_1']:.2f}\nT2: ${signal['target_2']:.2f}\nT3: ${signal.get('target_3', 0):.2f}",
                    "inline": True
                },
                {
                    "name": "📊 Volume Metrics",
                    "value": f"Relative: {signal['volume_ratio']:.1f}x\nVolume: {signal['volume']:,}",
                    "inline": True
                },
                {
                    "name": "🎲 Avg Trade",
                    "value": f"${signal['avg_trade_size']:,.0f}",
                    "inline": True
                },
                {
                    "name": "🌍 Market",
                    "value": market_status,
                    "inline": True
                }
            ]
        )

        # Add flow analysis if sweep detected
        if signal.get('sweep_detected', False):
            embed['fields'].append({
                "name": "🚨 Order Flow",
                "value": f"**SWEEP DETECTED** - Aggressive buying across exchanges",
                "inline": False
            })

        # Add scale out plan
        scale_out = signal['exit_strategy']['scale_out']
        embed['fields'].append({
            "name": "📋 Scale Out Plan",
            "value": f"• {int(scale_out['target_1_size']*100)}% at T1 (R:R {signal['risk_reward_1']:.1f}:1)\n"
                   f"• {int(scale_out['target_2_size']*100)}% at T2 (R:R {signal['risk_reward_2']:.1f}:1)\n"
                   f"• {int(scale_out['runner_size']*100)}% runner",
            "inline": False
        })

        # Add management note
        embed['fields'].append({
            "name": "💡 Management",
            "value": signal['exit_strategy']['management'],
            "inline": False
        })

        # Add disclaimer
        embed['fields'].append({
            "name": "",
            "value": "Please always do your own due diligence on top of these trade ideas.",
            "inline": False
        })

        embed['footer'] = f"Bullseye Bot | AI Score: {signal['ai_score']:.0f} | {signal['volume_ratio']:.1f}x Vol | {signal['conviction_split']}"

        await self.post_to_discord(embed)
        logger.info(f"Posted Bullseye signal: {signal['ticker']} {signal['type']} ${signal['strike']} Score:{signal['ai_score']:.0f} Priority:{signal.get('priority_score', 0):.0f}")
