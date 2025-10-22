"""Scalps Bot - Quick stock and options signals using The Strat"""
import logging
from datetime import datetime, timedelta
from typing import List, Dict
import pandas as pd
import asyncio
from .base_bot import BaseAutoBot
from src.data_fetcher import DataFetcher
from src.options_analyzer import OptionsAnalyzer
from src.config import Config
from src.utils.market_hours import MarketHours
from src.utils.market_context import MarketContext
from src.utils.exit_strategies import ExitStrategies
from src.utils.technical_indicators import TechnicalIndicators

logger = logging.getLogger(__name__)

class ScalpsBot(BaseAutoBot):
    """
    Scalps Bot
    Uses The Strat to identify quick stock and options signals that pan out immediately
    Focuses on 2-2 reversals, 3-2-2 inside-outside patterns, and momentum continuation
    """

    def __init__(self, webhook_url: str, watchlist: List[str], fetcher: DataFetcher, analyzer: OptionsAnalyzer):
        super().__init__(webhook_url, "Scalps Bot", scan_interval=120)  # 2 minutes for scalps
        self.watchlist = watchlist
        self.fetcher = fetcher
        self.analyzer = analyzer
        self.signal_history = {}
        self.candle_history = {}

    async def scan_and_post(self):
        """Enhanced scan with market context and concurrent processing"""
        logger.info(f"{self.name} scanning for quick scalp setups")

        # Only scan during market hours (9:30 AM - 4:00 PM EST, Monday-Friday)
        if not MarketHours.is_market_open():
            logger.debug(f"{self.name} - Market closed, skipping scan")
            return
        
        # Get market context
        market_context = await MarketContext.get_market_context(self.fetcher)
        logger.info(f"{self.name} - Market: {market_context['regime']}, Bias: {market_context['trading_bias']}")
        
        # Adjust threshold based on market conditions (minimum 50%)
        base_threshold = 50  # Base scalp score threshold (50% minimum)
        adjusted_threshold = max(50, MarketContext.adjust_signal_threshold(base_threshold, market_context))
        logger.debug(f"{self.name} - Adjusted threshold: {adjusted_threshold} (base: {base_threshold})")
        
        # Prioritize watchlist by recent activity
        prioritized_watchlist = await self._prioritize_by_activity(self.watchlist)
        
        # Batch processing for efficiency
        batch_size = 10
        all_signals = []
        
        for i in range(0, len(prioritized_watchlist), batch_size):
            batch = prioritized_watchlist[i:i+batch_size]
            
            # Concurrent scanning within batch
            tasks = [self._scan_strat_setup(symbol, market_context, adjusted_threshold) 
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
    
    async def _prioritize_by_activity(self, watchlist: List[str]) -> List[str]:
        """Prioritize tickers by recent trading activity"""
        try:
            # For now, return original order
            # TODO: Implement activity-based prioritization
            return watchlist
        except Exception as e:
            logger.error(f"Error prioritizing watchlist: {e}")
            return watchlist

    async def _scan_strat_setup(self, symbol: str, market_context: Dict = None,
                               adjusted_threshold: int = 50) -> List[Dict]:
        """
        Scan for Strat patterns and quick scalp opportunities using efficient REST flow detection.

        NEW APPROACH (REST):
        - Uses detect_unusual_flow() with $2K premium threshold
        - DTE ≤7 days filter for scalps
        - Pattern and momentum confirmation
        """
        signals = []

        try:
            # Get current price
            current_price = await self.fetcher.get_stock_price(symbol)
            if not current_price:
                return signals

            # Get recent candle data (5-minute bars)
            candles = await self._get_recent_candles(symbol)
            if not candles or len(candles) < 3:
                return signals

            # Identify Strat pattern
            pattern = self._identify_strat_pattern(candles)
            if not pattern:
                return signals

            # Calculate momentum indicators for confirmation (RSI required)
            closes = [c['close'] for c in candles]
            rsi = TechnicalIndicators.calculate_rsi(closes)

            # RSI momentum alignment check (avoid overbought/oversold extremes)
            rsi_aligned = self._check_rsi_alignment(rsi, pattern['direction'])
            if not rsi_aligned:
                logger.debug(f"{symbol}: RSI {rsi:.1f} not aligned with {pattern['direction']} pattern")
                return signals

            # NEW: Use efficient flow detection (single API call)
            flows = await self.fetcher.detect_unusual_flow(
                underlying=symbol,
                min_premium=Config.SCALPS_MIN_PREMIUM,  # $2K minimum
                min_volume_delta=10  # At least 10 contracts of volume change
            )

            # Process each flow signal
            for flow in flows:
                # Extract flow data
                opt_type = flow['type']
                strike = flow['strike']
                expiration = flow['expiration']
                premium = flow['premium']
                total_volume = flow['total_volume']
                volume_delta = flow['volume_delta']

                # Calculate DTE
                exp_date = datetime.strptime(expiration, '%Y-%m-%d')
                days_to_expiry = (exp_date - datetime.now()).days

                # Filter 1: DTE ≤7 days for scalps
                if days_to_expiry < 0 or days_to_expiry > 7:
                    continue

                # Filter 2: Pattern alignment
                pattern_aligned = (
                    (pattern['direction'] == 'bullish' and opt_type == 'CALL') or
                    (pattern['direction'] == 'bearish' and opt_type == 'PUT')
                )

                if not pattern_aligned:
                    continue

                # Filter 3: Strike proximity (within 3% for scalps)
                strike_distance = abs(strike - current_price) / current_price * 100
                if strike_distance > 3:
                    continue

                # Filter 4: Volume intensity check
                if total_volume < 50:
                    continue

                # Calculate scalp score
                scalp_score = self._calculate_scalp_score(
                    pattern, total_volume, strike_distance, days_to_expiry
                )

                if scalp_score >= adjusted_threshold:
                    # Calculate average price from premium and volume
                    avg_price = premium / (total_volume * 100) if total_volume > 0 else 0

                    # Calculate exit strategies
                    exits = ExitStrategies.calculate_exits(
                        'scalp', avg_price, current_price, opt_type,
                        atr=current_price * 0.02, dte=days_to_expiry
                    )

                    signal = {
                        'ticker': symbol,
                        'type': opt_type,
                        'strike': strike,
                        'expiration': expiration,
                        'current_price': current_price,
                        'days_to_expiry': days_to_expiry,
                        'volume': total_volume,
                        'premium': premium,
                        'pattern': pattern['name'],
                        'pattern_direction': pattern['direction'],
                        'pattern_strength': pattern['strength'],
                        'strike_distance': strike_distance,
                        'scalp_score': scalp_score,
                        'timeframe': '5m',
                        'avg_price': avg_price,
                        'stop_loss': exits['stop_loss'],
                        'target_1': exits['target_1'],
                        'target_2': exits['target_2'],
                        'risk_reward_1': exits['risk_reward_1'],
                        'risk_reward_2': exits['risk_reward_2'],
                        'exit_strategy': exits,
                        'market_context': market_context,
                        'volume_delta': volume_delta,
                        'delta': flow.get('delta', 0),
                        'gamma': flow.get('gamma', 0),
                        'rsi': rsi
                    }

                    # Check if already posted
                    signal_key = f"{symbol}_{opt_type}_{strike}_{expiration}"
                    if signal_key not in self.signal_history:
                        signals.append(signal)
                        self.signal_history[signal_key] = datetime.now()

        except Exception as e:
            logger.error(f"Error scanning Strat setup for {symbol}: {e}")

        return signals

    async def _get_recent_candles(self, symbol: str) -> List[Dict]:
        """Get REAL 5-minute candles from Polygon API"""
        try:
            # Get actual price bars from Polygon (last 1 hour = 12 bars)
            now = datetime.now()
            # Polygon API requires YYYY-MM-DD format only
            from_date = (now - timedelta(hours=1)).strftime('%Y-%m-%d')
            to_date = now.strftime('%Y-%m-%d')

            aggregates = await self.fetcher.get_aggregates(
                symbol,
                timespan='minute',
                multiplier=5,
                from_date=from_date,
                to_date=to_date
            )

            if aggregates.empty:
                logger.debug(f"No candle data for {symbol}")
                return []

            # Convert to candle format
            candles = []
            for _, row in aggregates.iterrows():
                candles.append({
                    'timestamp': row.get('timestamp', datetime.now()),
                    'open': row['open'],
                    'high': row['high'],
                    'low': row['low'],
                    'close': row['close'],
                    'volume': row.get('volume', 0)
                })

            # Return last 5 candles for pattern analysis
            return candles[-5:] if len(candles) >= 5 else candles

        except Exception as e:
            logger.error(f"Error fetching real candles for {symbol}: {e}")
            return []

    def _identify_strat_pattern(self, candles: List[Dict]) -> Dict:
        """Enhanced pattern identification with advanced patterns"""
        if len(candles) < 3:
            return None

        last = candles[-1]
        prev = candles[-2]
        prev2 = candles[-3]

        # Check advanced patterns first
        advanced_pattern = self._identify_advanced_patterns(candles)
        if advanced_pattern:
            return advanced_pattern

        # Inside bar (2)
        is_inside = (last['high'] < prev['high'] and last['low'] > prev['low'])

        # Outside bar (3)
        is_outside = (last['high'] > prev['high'] and last['low'] < prev['low'])

        # Directional bar (1)
        is_bullish = (last['close'] > last['open'])
        is_bearish = (last['close'] < last['open'])

        # 2-2 Reversal (inside bar after inside bar with direction change)
        if is_inside:
            prev_inside = (prev['high'] < prev2['high'] and prev['low'] > prev2['low'])
            if prev_inside:
                if is_bullish:
                    return {'name': '2-2 Bullish Reversal', 'direction': 'bullish', 'strength': 85}
                elif is_bearish:
                    return {'name': '2-2 Bearish Reversal', 'direction': 'bearish', 'strength': 85}

        # 3-2-2 Pattern (outside bar followed by inside bars)
        prev_outside = (prev['high'] > prev2['high'] and prev['low'] < prev2['low'])
        if is_inside and prev_outside:
            if is_bullish:
                return {'name': '3-2-2 Bullish', 'direction': 'bullish', 'strength': 90}
            elif is_bearish:
                return {'name': '3-2-2 Bearish', 'direction': 'bearish', 'strength': 90}

        # Simple directional continuation
        if is_bullish and prev['close'] > prev['open']:
            return {'name': 'Bullish Continuation', 'direction': 'bullish', 'strength': 70}
        elif is_bearish and prev['close'] < prev['open']:
            return {'name': 'Bearish Continuation', 'direction': 'bearish', 'strength': 70}

        return None
    
    def _identify_advanced_patterns(self, candles: List[Dict]) -> Dict:
        """Identify advanced trading patterns"""
        if len(candles) < 5:
            return None
        
        # Volume breakout pattern
        volume_breakout = self._is_volume_breakout(candles)
        if volume_breakout:
            return volume_breakout
        
        # Gap patterns
        gap_pattern = self._check_gap_pattern(candles)
        if gap_pattern:
            return gap_pattern
        
        # Support/Resistance bounce
        sr_bounce = self._check_sr_bounce(candles)
        if sr_bounce:
            return sr_bounce
        
        # Exhaustion reversal
        exhaustion = self._check_exhaustion(candles)
        if exhaustion:
            return exhaustion
        
        return None
    
    def _is_volume_breakout(self, candles: List[Dict]) -> Dict:
        """Check for volume breakout pattern"""
        try:
            # Get average volume
            volumes = [c.get('volume', 0) for c in candles[:-1]]
            avg_volume = sum(volumes) / len(volumes) if volumes else 0
            
            last = candles[-1]
            last_volume = last.get('volume', 0)
            
            # Volume surge check
            if last_volume > avg_volume * 2:  # 2x average volume
                # Price breakout check
                highs = [c['high'] for c in candles[:-1]]
                lows = [c['low'] for c in candles[:-1]]
                
                if last['close'] > max(highs):
                    return {'name': 'Volume Breakout Up', 'direction': 'bullish', 'strength': 95}
                elif last['close'] < min(lows):
                    return {'name': 'Volume Breakout Down', 'direction': 'bearish', 'strength': 95}
        except Exception:
            pass
        
        return None
    
    def _check_gap_pattern(self, candles: List[Dict]) -> Dict:
        """Check for gap patterns"""
        try:
            last = candles[-1]
            prev = candles[-2]
            
            # Gap up
            if last['low'] > prev['high']:
                gap_size = (last['low'] - prev['high']) / prev['high'] * 100
                if gap_size > 1.0:  # 1% gap
                    return {'name': 'Gap & Go Up', 'direction': 'bullish', 'strength': 88}
            
            # Gap down
            elif last['high'] < prev['low']:
                gap_size = (prev['low'] - last['high']) / prev['low'] * 100
                if gap_size > 1.0:  # 1% gap
                    return {'name': 'Gap & Go Down', 'direction': 'bearish', 'strength': 88}
        except Exception:
            pass
        
        return None
    
    def _check_sr_bounce(self, candles: List[Dict]) -> Dict:
        """Check for support/resistance bounce"""
        try:
            # Calculate recent support/resistance
            recent_highs = [c['high'] for c in candles[-10:-1]]
            recent_lows = [c['low'] for c in candles[-10:-1]]
            
            resistance = max(recent_highs)
            support = min(recent_lows)
            
            last = candles[-1]
            
            # Support bounce
            if last['low'] <= support * 1.005 and last['close'] > last['open']:
                return {'name': 'Support Bounce', 'direction': 'bullish', 'strength': 82}
            
            # Resistance rejection
            elif last['high'] >= resistance * 0.995 and last['close'] < last['open']:
                return {'name': 'Resistance Rejection', 'direction': 'bearish', 'strength': 82}
        except Exception:
            pass
        
        return None
    
    def _check_exhaustion(self, candles: List[Dict]) -> Dict:
        """Check for exhaustion reversal pattern"""
        try:
            # Check for extended move
            closes = [c['close'] for c in candles]
            avg_close = sum(closes[:-1]) / len(closes[:-1])
            
            last = candles[-1]
            extension = (last['close'] - avg_close) / avg_close * 100
            
            # Bullish exhaustion (oversold bounce)
            if extension < -3.0 and last['close'] > last['open']:
                return {'name': 'Exhaustion Reversal Up', 'direction': 'bullish', 'strength': 87}
            
            # Bearish exhaustion (overbought reversal)
            elif extension > 3.0 and last['close'] < last['open']:
                return {'name': 'Exhaustion Reversal Down', 'direction': 'bearish', 'strength': 87}
        except Exception:
            pass
        
        return None

    def _check_rsi_alignment(self, rsi: float, direction: str) -> bool:
        """Check if RSI supports the pattern direction (avoid extremes)"""
        # For bullish patterns: RSI should be 30-70 (avoid overbought)
        if direction == 'bullish':
            return 30 <= rsi <= 70

        # For bearish patterns: RSI should be 30-70 (avoid oversold)
        elif direction == 'bearish':
            return 30 <= rsi <= 70

        return False

    def _calculate_scalp_score(self, pattern: Dict, volume: int,
                              strike_distance: float, dte: int) -> int:
        """Calculate scalp opportunity score using generic scoring"""
        # Pattern strength (40% of score)
        score = int(pattern['strength'] * 0.4)

        # Add remaining metrics via generic scoring
        score += self.calculate_score({
            'volume': (volume, [
                (300, 30),  # 300+ → 30 points (30%)
                (150, 25),  # 150+ → 25 points
                (75, 20),   # 75+ → 20 points
                (0, 15)     # Default → 15 points
            ])
        })

        # Strike proximity (20%)
        if strike_distance <= 0.5:
            score += 20
        elif strike_distance <= 1:
            score += 15
        elif strike_distance <= 2:
            score += 10

        # DTE preference (10%)
        if dte <= 2:
            score += 10
        elif dte <= 5:
            score += 7

        return score

    def apply_quality_filters(self, signal: Dict) -> bool:
        """Apply quality filters to signals"""
        try:
            # Minimum score threshold (50%)
            if signal.get('scalp_score', 0) < 50:
                return False

            # Minimum volume requirement
            if signal.get('volume', 0) < 75:
                return False

            # Minimum premium requirement
            if signal.get('premium', 0) < 5000:
                return False

            # Pattern strength requirement
            if signal.get('pattern_strength', 0) < 70:
                return False

            # DTE range (0-7 days for scalps)
            dte = signal.get('days_to_expiry', 0)
            if dte < 0 or dte > 7:
                return False

            return True
        except Exception as e:
            logger.error(f"Error in quality filter: {e}")
            return False

    def rank_signals(self, signals: List[Dict]) -> List[Dict]:
        """Rank signals by priority and return top 5"""
        try:
            # Calculate priority score for each signal
            for signal in signals:
                priority = 0

                # Scalp score (40%)
                priority += signal.get('scalp_score', 0) * 0.4

                # Pattern strength (30%)
                priority += signal.get('pattern_strength', 0) * 0.3

                # Volume factor (20%)
                volume = signal.get('volume', 0)
                if volume >= 300:
                    priority += 20
                elif volume >= 150:
                    priority += 15
                elif volume >= 75:
                    priority += 10

                # Risk/reward (10%)
                rr1 = signal.get('risk_reward_1', 0)
                if rr1 >= 3.0:
                    priority += 10
                elif rr1 >= 2.0:
                    priority += 7
                elif rr1 >= 1.5:
                    priority += 5

                signal['priority_score'] = priority

            # Sort by priority (descending)
            ranked = sorted(signals, key=lambda x: x.get('priority_score', 0), reverse=True)

            # Return top 5
            return ranked[:5]

        except Exception as e:
            logger.error(f"Error ranking signals: {e}")
            return signals[:5]

    async def _post_signal(self, signal: Dict):
        """Post enhanced Scalps signal to Discord"""
        color = 0x00FF00 if signal['type'] == 'CALL' else 0xFF0000
        
        # Format priority
        priority_level = "HIGH" if signal.get('priority_score', 0) >= 80 else "MEDIUM"
        
        # Get market context
        market = signal.get('market_context', {})
        market_status = f"{market.get('momentum', {}).get('direction', 'neutral').title()}, {market.get('volatility', {}).get('level', 'normal').title()} VIX"

        # Build fields
        fields = [
            {"name": "📊 Contract", "value": f"{signal['type']} ${signal['strike']} {signal['days_to_expiry']}DTE", "inline": True},
            {"name": "⚡ Score", "value": f"**{signal['scalp_score']}/100**", "inline": True},
            {"name": "🎯 Priority", "value": f"{signal.get('priority_score', 0):.0f}", "inline": True},
            {"name": "💵 Entry Zone", "value": f"${signal['exit_strategy']['entry_zone']['lower']:.2f} - ${signal['exit_strategy']['entry_zone']['upper']:.2f}", "inline": True},
            {"name": "🛑 Stop Loss", "value": f"${signal['stop_loss']:.2f} ({signal['exit_strategy']['stop_pct']})", "inline": True},
            {"name": "✅ Target 1", "value": f"${signal['target_1']:.2f} ({signal['exit_strategy']['target1_pct']})", "inline": True},
            {"name": "🎯 Target 2", "value": f"${signal['target_2']:.2f} ({signal['exit_strategy']['target2_pct']})", "inline": True},
            {"name": "📊 R:R Ratios", "value": f"T1: {signal['risk_reward_1']:.1f}:1\nT2: {signal['risk_reward_2']:.1f}:1", "inline": True},
            {"name": "📈 Pattern", "value": f"{signal['pattern']} ({signal['pattern_strength']})", "inline": True},
            {"name": "💰 Volume/Premium", "value": f"{signal['volume']:,} / ${signal['premium']:,.0f}", "inline": True},
            {"name": "📍 Distance", "value": f"{signal['strike_distance']:.1f}%", "inline": True},
            {"name": "🌍 Market", "value": market_status, "inline": True},
            {"name": "📋 Exit Plan", "value": f"• Take {int(signal['exit_strategy']['scale_out']['target_1_size']*100)}% at T1\n• Take {int(signal['exit_strategy']['scale_out']['target_2_size']*100)}% at T2\n• Trail stop: ${signal['exit_strategy']['trail_stop']:.2f}", "inline": False},
            {"name": "⚠️ Management", "value": signal['exit_strategy']['management'], "inline": False}
        ]

        # Create embed with auto-disclaimer
        embed = self.create_signal_embed_with_disclaimer(
            title=f"⚡ Scalp: {signal['ticker']}",
            description=f"{signal['pattern']} | Quick {signal['type']} Setup\n**Priority: {priority_level}**",
            color=color,
            fields=fields,
            footer=f"Scalps Bot | Pattern: {signal['pattern']} | Score: {signal['scalp_score']}"
        )

        await self.post_to_discord(embed)
        logger.info(f"Posted Scalp signal: {signal['ticker']} {signal['type']} ${signal['strike']} Pattern:{signal['pattern']} Priority:{signal.get('priority_score', 0):.0f}")
