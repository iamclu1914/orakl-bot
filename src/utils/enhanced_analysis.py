"""
Enhanced Analysis Utilities
Critical features for high-probability signal detection
"""
import logging
from datetime import datetime, timedelta
from typing import Dict, Optional
import pandas as pd

logger = logging.getLogger(__name__)


class EnhancedAnalyzer:
    """Enhanced analysis utilities for all bots"""

    def __init__(self, fetcher):
        self.fetcher = fetcher
        self.volume_cache = {}  # Cache 30-day averages

    async def calculate_volume_ratio(self, symbol: str, current_volume: int) -> float:
        """
        Calculate volume ratio vs 30-day average

        Returns:
            float: Ratio (3.0 = 3x average volume)
        """
        try:
            # Check cache first (refresh every hour)
            cache_key = f"{symbol}_{datetime.now().strftime('%Y%m%d%H')}"
            if cache_key in self.volume_cache:
                avg_volume = self.volume_cache[cache_key]
            else:
                # Get historical volume
                from_date = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
                historical = await self.fetcher.get_aggregates(
                    symbol,
                    timespan='day',
                    multiplier=1,
                    from_date=from_date
                )

                if historical.empty:
                    return 1.0

                avg_volume = historical['volume'].mean()
                self.volume_cache[cache_key] = avg_volume

            # Calculate ratio
            ratio = current_volume / avg_volume if avg_volume > 0 else 1.0
            return round(ratio, 2)

        except Exception as e:
            logger.error(f"Error calculating volume ratio for {symbol}: {e}")
            return 1.0

    async def check_price_action_alignment(self, symbol: str, opt_type: str) -> Optional[Dict]:
        """
        Verify options flow matches stock price movement across multiple timeframes

        Returns:
            Dict with alignment info or None if data unavailable
        """
        try:
            from_date = (datetime.now() - timedelta(hours=2)).strftime('%Y-%m-%d')

            # Get 5-minute bars
            bars_5m = await self.fetcher.get_aggregates(
                symbol,
                timespan='minute',
                multiplier=5,
                from_date=from_date,
                limit=6
            )

            # Get 15-minute bars
            bars_15m = await self.fetcher.get_aggregates(
                symbol,
                timespan='minute',
                multiplier=15,
                from_date=from_date,
                limit=4
            )

            if bars_5m.empty or bars_15m.empty:
                return None

            # Calculate momentum across timeframes
            momentum_5m = ((bars_5m.iloc[-1]['close'] - bars_5m.iloc[0]['close']) /
                           bars_5m.iloc[0]['close']) * 100

            momentum_15m = ((bars_15m.iloc[-1]['close'] - bars_15m.iloc[0]['close']) /
                            bars_15m.iloc[0]['close']) * 100

            # Volume confirmation
            avg_volume_5m = bars_5m['volume'].mean()
            current_volume = bars_5m.iloc[-1]['volume']
            volume_ratio = current_volume / avg_volume_5m if avg_volume_5m > 0 else 1.0

            # Check alignment
            if opt_type == 'CALL':
                aligned_5m = momentum_5m > 0
                aligned_15m = momentum_15m > 0
                strength = (momentum_5m + momentum_15m) / 2
            else:  # PUT
                aligned_5m = momentum_5m < 0
                aligned_15m = momentum_15m < 0
                strength = abs((momentum_5m + momentum_15m) / 2)

            aligned = aligned_5m and aligned_15m
            volume_confirmed = volume_ratio >= 1.5  # 50% above average

            return {
                'aligned': aligned,
                'strength': strength,
                'momentum_5m': momentum_5m,
                'momentum_15m': momentum_15m,
                'volume_ratio': volume_ratio,
                'volume_confirmed': volume_confirmed,
                'confidence': self._calculate_alignment_confidence(
                    aligned, strength, volume_confirmed
                )
            }

        except Exception as e:
            logger.error(f"Error checking price action for {symbol}: {e}")
            return None

    def _calculate_alignment_confidence(self, aligned: bool, strength: float,
                                       volume_confirmed: bool) -> int:
        """Calculate confidence score for price action alignment (0-100)"""
        if not aligned:
            return 0

        score = 50  # Base for alignment

        # Add for strength
        if strength >= 2.0:
            score += 30
        elif strength >= 1.0:
            score += 20
        elif strength >= 0.5:
            score += 10

        # Add for volume
        if volume_confirmed:
            score += 20

        return min(score, 100)

    def calculate_implied_move(self, current_price: float, strike: float,
                               premium_per_contract: float, days_to_expiry: int,
                               opt_type: str) -> Dict:
        """
        Calculate break-even and probability metrics

        Returns:
            Dict with breakeven, needed move %, probability estimates
        """
        try:
            # Break-even calculation
            if opt_type == 'CALL':
                breakeven = strike + premium_per_contract
                needed_move = ((breakeven - current_price) / current_price) * 100
            else:  # PUT
                breakeven = strike - premium_per_contract
                needed_move = ((current_price - breakeven) / current_price) * 100

            # Annualize the move
            annual_move = needed_move * (365 / max(days_to_expiry, 1))

            # Probability estimate (simplified Black-Scholes approximation)
            abs_move = abs(needed_move)
            if abs_move < 2:
                prob_profit = 65
            elif abs_move < 5:
                prob_profit = 45
            elif abs_move < 10:
                prob_profit = 30
            elif abs_move < 20:
                prob_profit = 15
            else:
                prob_profit = 5

            # Risk/reward ratio
            risk_reward = abs_move / max(days_to_expiry, 1)

            return {
                'breakeven': round(breakeven, 2),
                'needed_move_pct': round(needed_move, 2),
                'annual_move_pct': round(annual_move, 2),
                'prob_profit': prob_profit,
                'risk_reward_ratio': round(risk_reward, 3),
                'grade': self._grade_implied_move(abs_move, days_to_expiry)
            }

        except Exception as e:
            logger.error(f"Error calculating implied move: {e}")
            return {
                'breakeven': strike,
                'needed_move_pct': 0,
                'annual_move_pct': 0,
                'prob_profit': 50,
                'risk_reward_ratio': 1.0,
                'grade': 'UNKNOWN'
            }

    def _grade_implied_move(self, abs_move: float, dte: int) -> str:
        """Grade the risk/reward of the implied move"""
        # Daily move needed
        daily_move = abs_move / max(dte, 1)

        if daily_move < 0.5:
            return 'EXCELLENT'  # Easy target
        elif daily_move < 1.0:
            return 'GOOD'  # Reasonable
        elif daily_move < 2.0:
            return 'FAIR'  # Moderate risk
        elif daily_move < 5.0:
            return 'RISKY'  # High risk
        else:
            return 'EXTREME'  # Very high risk


class SmartDeduplicator:
    """Smart deduplication to catch accumulation patterns"""

    def __init__(self):
        self.signal_history = {}

    def should_alert(self, signal_key: str, new_premium: float,
                    current_time: datetime = None) -> Dict:
        """
        Determine if signal should be alerted based on accumulation logic

        Returns:
            Dict: {'should_alert': bool, 'reason': str, 'type': str}
        """
        if current_time is None:
            current_time = datetime.now()

        if signal_key not in self.signal_history:
            # First time seeing this signal
            self.signal_history[signal_key] = {
                'first_seen': current_time,
                'total_premium': new_premium,
                'alert_count': 1,
                'last_alert': current_time
            }
            return {
                'should_alert': True,
                'reason': 'Initial signal',
                'type': 'NEW'
            }

        history = self.signal_history[signal_key]
        time_since_first = (current_time - history['first_seen']).total_seconds() / 60
        time_since_last = (current_time - history['last_alert']).total_seconds() / 60

        # Accumulation detection:
        # If premium has doubled AND at least 15 min since last alert AND not already spammed
        if (new_premium >= history['total_premium'] * 2 and
            time_since_last >= 15 and
            history['alert_count'] < 3):

            # Update history
            history['total_premium'] += new_premium
            history['alert_count'] += 1
            history['last_alert'] = current_time

            return {
                'should_alert': True,
                'reason': f'Accumulation detected (2x premium, {history["alert_count"]} total alerts)',
                'type': 'ACCUMULATION'
            }

        # Re-alert after 4 hours for very large premiums
        if (new_premium >= 500000 and  # $500K+
            time_since_last >= 240):  # 4 hours

            history['last_alert'] = current_time
            history['alert_count'] += 1

            return {
                'should_alert': True,
                'reason': 'Large premium refresh (4hr)',
                'type': 'REFRESH'
            }

        return {
            'should_alert': False,
            'reason': f'Already alerted ({history["alert_count"]} times, last {time_since_last:.0f}m ago)',
            'type': 'DUPLICATE'
        }

    def cleanup_old_signals(self, max_age_hours: int = 24):
        """Remove signals older than max_age_hours"""
        cutoff = datetime.now() - timedelta(hours=max_age_hours)
        self.signal_history = {
            k: v for k, v in self.signal_history.items()
            if v['first_seen'] > cutoff
        }
