"""
ORAKL Bot Options Analyzer
Core analysis engine for options flow calculations and signal detection
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
from scipy.stats import norm
import logging
from collections import defaultdict
import math

from src.utils.validation import DataValidator, SafeCalculations
from src.utils.market_analysis import MarketAnalyzer, AdvancedScoring, MarketContext
from src.config import Config

logger = logging.getLogger(__name__)

class OptionsAnalyzer:
    """Enhanced options flow analysis with advanced scoring"""
    
    def __init__(self):
        self.signal_history = defaultdict(list)  # Track repeat signals
        self.success_tracking = defaultdict(dict)  # Track signal success rates
        self.market_analyzer = MarketAnalyzer()  # Market context analyzer
        self._price_cache = {}  # Cache for price data
        
    def analyze_flow(self, trades_df: pd.DataFrame) -> Dict:
        """Analyze options flow for a symbol"""
        if trades_df.empty:
            return {
                'total_premium': 0,
                'call_premium': 0,
                'put_premium': 0,
                'largest_trade': 0,
                'avg_trade_size': 0,
                'dominant_side': 'NEUTRAL',
                'unusual_trades': 0,
                'signal_strength': 'WEAK'
            }
            
        # Calculate metrics
        total_premium = trades_df['premium'].sum()
        call_trades = trades_df[trades_df['type'] == 'CALL']
        put_trades = trades_df[trades_df['type'] == 'PUT']
        
        call_premium = call_trades['premium'].sum()
        put_premium = put_trades['premium'].sum()
        
        # Find largest trade
        largest_trade = trades_df.loc[trades_df['premium'].idxmax()] if not trades_df.empty else None
        
        # Calculate averages
        avg_trade_size = trades_df['premium'].mean()
        
        # Determine dominant side
        if call_premium > put_premium * 1.5:
            dominant_side = 'BULLISH'
        elif put_premium > call_premium * 1.5:
            dominant_side = 'BEARISH'
        else:
            dominant_side = 'NEUTRAL'
            
        # Count unusual trades (>3x average)
        unusual_trades = len(trades_df[trades_df['premium'] > avg_trade_size * 3])
        
        # Determine signal strength
        if total_premium > 1000000 and unusual_trades > 5:
            signal_strength = 'STRONG'
        elif total_premium > 500000 and unusual_trades > 2:
            signal_strength = 'MODERATE'
        else:
            signal_strength = 'WEAK'
            
        return {
            'total_premium': total_premium,
            'call_premium': call_premium,
            'put_premium': put_premium,
            'largest_trade': largest_trade.to_dict() if largest_trade is not None else None,
            'avg_trade_size': avg_trade_size,
            'dominant_side': dominant_side,
            'unusual_trades': unusual_trades,
            'signal_strength': signal_strength,
            'trade_count': len(trades_df),
            'call_count': len(call_trades),
            'put_count': len(put_trades)
        }
        
    def calculate_flow_sentiment(self, symbol: str, trades_df: pd.DataFrame) -> Dict:
        """Calculate sentiment score based on options flow"""
        if trades_df.empty:
            return {
                'sentiment': 'NEUTRAL',
                'score': 0,
                'confidence': 0,
                'call_premium': 0,
                'put_premium': 0
            }
            
        # Group by type and calculate premiums
        flow_summary = trades_df.groupby('type')['premium'].agg(['sum', 'count', 'mean'])
        
        call_premium = flow_summary.loc['CALL', 'sum'] if 'CALL' in flow_summary.index else 0
        put_premium = flow_summary.loc['PUT', 'sum'] if 'PUT' in flow_summary.index else 0
        
        # Calculate sentiment score (-100 to +100)
        total_premium = call_premium + put_premium
        if total_premium > 0:
            # Weighted score based on premium imbalance
            score = ((call_premium - put_premium) / total_premium) * 100
            
            # Adjust for volume
            call_count = flow_summary.loc['CALL', 'count'] if 'CALL' in flow_summary.index else 0
            put_count = flow_summary.loc['PUT', 'count'] if 'PUT' in flow_summary.index else 0
            volume_factor = (call_count - put_count) / max(call_count + put_count, 1)
            
            # Combine premium and volume factors
            score = score * 0.7 + volume_factor * 30
            
            # Calculate confidence based on total activity
            confidence = min(100, (total_premium / 100000) * 20)  # Max confidence at $500k
        else:
            score = 0
            confidence = 0
            
        # Determine sentiment
        if score > 20:
            sentiment = 'BULLISH'
        elif score < -20:
            sentiment = 'BEARISH'
        else:
            sentiment = 'NEUTRAL'
            
        return {
            'sentiment': sentiment,
            'score': round(score, 1),
            'confidence': round(confidence, 1),
            'call_premium': call_premium,
            'put_premium': put_premium,
            'total_premium': total_premium
        }
        
    def calculate_probability_itm(self, option_type: str, strike: float, current_price: float,
                                 days_to_expiry: int, implied_volatility: float = 0.3) -> float:
        """Calculate probability of option finishing in-the-money using Black-Scholes"""
        if days_to_expiry <= 0:
            if option_type == 'CALL':
                return 100.0 if current_price > strike else 0.0
            else:
                return 100.0 if current_price < strike else 0.0

        # Black-Scholes formula for probability
        time_to_expiry_years = days_to_expiry / 365.25
        d2 = (np.log(current_price / strike) + (0.01 - 0.5 * implied_volatility ** 2) * time_to_expiry_years) / (implied_volatility * np.sqrt(time_to_expiry_years))
        
        if option_type == 'CALL':
            probability = norm.cdf(d2) * 100
        else:
            probability = (1 - norm.cdf(d2)) * 100
            
        return round(probability, 1)
        
    def identify_repeat_signals(self, symbol: str, strike: float, option_type: str,
                              expiration: str, premium: float) -> int:
        """Track and identify repeat signals"""
        signal_key = f"{symbol}_{option_type}_{strike}_{expiration}"
        
        # Add to history
        self.signal_history[signal_key].append({
            'timestamp': datetime.now(),
            'premium': premium
        })
        
        # Clean old signals (>1 hour)
        cutoff_time = datetime.now() - timedelta(hours=1)
        self.signal_history[signal_key] = [
            s for s in self.signal_history[signal_key]
            if s['timestamp'] > cutoff_time
        ]
        
        return len(self.signal_history[signal_key])
        
    def calculate_success_rate(self, symbol: str) -> float:
        """Calculate historical success rate for signals"""
        if symbol not in self.success_tracking:
            return 0.65  # Default success rate
            
        tracking = self.success_tracking[symbol]
        if not tracking:
            return 0.65
            
        successful = sum(1 for result in tracking.values() if result.get('success', False))
        total = len(tracking)
        
        if total < 5:  # Not enough data
            return 0.65
            
        return successful / total
        
    def update_success_tracking(self, symbol: str, signal_id: str, success: bool):
        """Update success tracking for signals"""
        if symbol not in self.success_tracking:
            self.success_tracking[symbol] = {}
            
        self.success_tracking[symbol][signal_id] = {
            'timestamp': datetime.now(),
            'success': success
        }
        
        # Clean old tracking data (>30 days)
        cutoff = datetime.now() - timedelta(days=30)
        self.success_tracking[symbol] = {
            k: v for k, v in self.success_tracking[symbol].items()
            if v['timestamp'] > cutoff
        }
        
    def calculate_greeks_estimate(self, option_type: str, strike: float, current_price: float,
                                days_to_expiry: int, volatility: float = 0.3) -> Dict:
        """Estimate option Greeks (simplified)"""
        if days_to_expiry <= 0:
            return {
                'delta': 1.0 if (option_type == 'CALL' and current_price > strike) or 
                              (option_type == 'PUT' and current_price < strike) else 0.0,
                'gamma': 0.0,
                'theta': 0.0,
                'vega': 0.0
            }
            
        time_to_expiry = days_to_expiry / 365.0
        sqrt_time = np.sqrt(time_to_expiry)
        
        # Calculate d1 and d2
        d1 = (np.log(current_price / strike) + 0.5 * volatility ** 2 * time_to_expiry) / \
             (volatility * sqrt_time)
        d2 = d1 - volatility * sqrt_time
        
        # Calculate Greeks
        if option_type == 'CALL':
            delta = norm.cdf(d1)
            theta = -(current_price * norm.pdf(d1) * volatility) / (2 * sqrt_time) / 365
        else:
            delta = norm.cdf(d1) - 1
            theta = -(current_price * norm.pdf(d1) * volatility) / (2 * sqrt_time) / 365
            
        gamma = norm.pdf(d1) / (current_price * volatility * sqrt_time)
        vega = current_price * norm.pdf(d1) * sqrt_time / 100
        
        return {
            'delta': round(delta, 4),
            'gamma': round(gamma, 4),
            'theta': round(theta, 4),
            'vega': round(vega, 4)
        }
        
    def rank_signals(self, signals: List[Dict]) -> List[Dict]:
        """Rank signals by importance and probability"""
        for signal in signals:
            # Calculate composite score
            score = 0
            
            # Premium weight (40%)
            premium_score = min(100, signal['total_premium'] / 10000)
            score += premium_score * 0.4
            
            # Probability weight (30%)
            prob_score = signal.get('probability_itm', 50)
            score += prob_score * 0.3
            
            # Repeat signal weight (20%)
            repeat_score = min(100, signal.get('repeat_count', 1) * 20)
            score += repeat_score * 0.2
            
            # Volume/OI ratio weight (10%)
            vol_oi_score = min(100, signal.get('vol_oi_ratio', 1) * 10)
            score += vol_oi_score * 0.1
            
            signal['rank_score'] = round(score, 1)
            
        # Sort by rank score
        return sorted(signals, key=lambda x: x['rank_score'], reverse=True)
        
    def detect_unusual_activity(self, trades_df: pd.DataFrame, historical_avg: Dict) -> List[Dict]:
        """Detect unusual options activity compared to historical averages"""
        unusual_activities = []
        
        if trades_df.empty:
            return unusual_activities
            
        # Group by strike and type
        grouped = trades_df.groupby(['strike', 'type'])
        
        for (strike, option_type), group in grouped:
            volume = group['volume'].sum()
            premium = group['premium'].sum()
            avg_price = group['price'].mean()
            
            # Compare to historical average
            hist_key = f"{strike}_{option_type}"
            hist_vol = historical_avg.get(f"{hist_key}_volume", 100)
            hist_prem = historical_avg.get(f"{hist_key}_premium", 10000)
            
            # Check for unusual activity
            if volume > hist_vol * 3 or premium > hist_prem * 3:
                unusual_activities.append({
                    'strike': strike,
                    'type': option_type,
                    'volume': volume,
                    'premium': premium,
                    'avg_price': avg_price,
                    'volume_ratio': volume / max(hist_vol, 1),
                    'premium_ratio': premium / max(hist_prem, 1),
                    'timestamp': group['timestamp'].max()
                })
                
        return sorted(unusual_activities, key=lambda x: x['premium'], reverse=True)
    
    async def analyze_signal_with_context(
        self,
        signal: Dict[str, Any],
        price_data: pd.DataFrame,
        base_score: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Analyze signal with full market context
        
        Args:
            signal: Signal data including symbol, type, strike, etc.
            price_data: Historical price data for context
            base_score: Optional base score from bot logic
            
        Returns:
            Enhanced signal with comprehensive scoring
        """
        try:
            # Get market context
            market_context = await self.market_analyzer.get_market_context(
                signal['symbol'],
                price_data
            )
            
            # Prepare signal metrics
            signal_metrics = {
                'premium': signal.get('premium', 0),
                'volume': signal.get('volume', 0),
                'probability_itm': signal.get('probability_itm', 50),
                'repeat_count': signal.get('repeat_count', 1),
                'price_change_pct': self._calculate_price_change(price_data),
                'volume_ratio': signal.get('volume_ratio', 1),
                'vol_oi_ratio': signal.get('vol_oi_ratio', 0)
            }
            
            # Add technical indicators if available
            if not price_data.empty and len(price_data) >= 14:
                signal_metrics['rsi'] = self._calculate_rsi(price_data['close'])
            
            # Calculate comprehensive score
            scores = AdvancedScoring.calculate_signal_score(
                base_score or signal.get('score', 50),
                market_context,
                signal_metrics,
                signal['type']
            )
            
            # Enhance signal with context
            enhanced_signal = {
                **signal,
                'market_context': {
                    'regime': market_context.regime.value,
                    'trend': market_context.trend.value,
                    'volatility': market_context.volatility,
                    'vix': market_context.vix,
                    'put_call_ratio': market_context.put_call_ratio
                },
                'scores': scores,
                'final_score': scores['total'],
                'confidence': scores['confidence'],
                'analysis_timestamp': datetime.now()
            }
            
            # Add trading suggestions based on analysis
            enhanced_signal['suggestions'] = self._generate_suggestions(
                enhanced_signal,
                market_context
            )
            
            return enhanced_signal
            
        except Exception as e:
            logger.error(f"Error analyzing signal with context: {e}")
            # Return original signal with error flag
            return {
                **signal,
                'analysis_error': str(e),
                'final_score': signal.get('score', 50)
            }
    
    def _calculate_price_change(self, price_data: pd.DataFrame) -> float:
        """Calculate recent price change percentage"""
        if price_data.empty or len(price_data) < 2:
            return 0.0
        
        try:
            recent_close = price_data['close'].iloc[-1]
            prev_close = price_data['close'].iloc[-2]
            return SafeCalculations.safe_percentage(
                recent_close - prev_close,
                prev_close
            )
        except Exception:
            return 0.0
    
    def _calculate_rsi(self, prices: pd.Series, period: int = 14) -> float:
        """Calculate RSI (Relative Strength Index)"""
        if len(prices) < period + 1:
            return 50.0  # Neutral
        
        try:
            # Calculate price changes
            delta = prices.diff()
            
            # Separate gains and losses
            gains = delta.where(delta > 0, 0)
            losses = -delta.where(delta < 0, 0)
            
            # Calculate average gains and losses
            avg_gains = gains.rolling(window=period).mean()
            avg_losses = losses.rolling(window=period).mean()
            
            # Calculate RS and RSI
            rs = avg_gains / avg_losses
            rsi = 100 - (100 / (1 + rs))
            
            return float(rsi.iloc[-1])
            
        except Exception:
            return 50.0
    
    def _generate_suggestions(
        self,
        signal: Dict[str, Any],
        context: MarketContext
    ) -> Dict[str, Any]:
        """Generate trading suggestions based on analysis"""
        suggestions = {
            'action': 'MONITOR',
            'confidence': 'MEDIUM',
            'notes': []
        }
        
        final_score = signal.get('final_score', 50)
        confidence = signal.get('confidence', 50)
        
        # Determine action
        if final_score >= 80 and confidence >= 70:
            suggestions['action'] = 'STRONG_BUY'
            suggestions['confidence'] = 'HIGH'
        elif final_score >= 70 and confidence >= 60:
            suggestions['action'] = 'BUY'
            suggestions['confidence'] = 'HIGH' if confidence >= 75 else 'MEDIUM'
        elif final_score >= 60:
            suggestions['action'] = 'CONSIDER'
            suggestions['confidence'] = 'MEDIUM'
        else:
            suggestions['action'] = 'MONITOR'
            suggestions['confidence'] = 'LOW'
        
        # Add specific notes
        if context.regime.value == 'high_volatility':
            suggestions['notes'].append("High volatility - consider smaller position size")
        
        if signal.get('probability_itm', 0) < 30:
            suggestions['notes'].append("Low probability - high risk/reward")
        elif signal.get('probability_itm', 0) > 80:
            suggestions['notes'].append("High probability - lower potential return")
        
        if signal.get('repeat_count', 0) >= 5:
            suggestions['notes'].append("Strong repeat signal - institutional interest")
        
        # Risk management
        suggestions['risk_management'] = {
            'position_size': self._suggest_position_size(final_score, confidence),
            'stop_loss': self._suggest_stop_loss(signal),
            'take_profit': self._suggest_take_profit(signal)
        }
        
        return suggestions
    
    def _suggest_position_size(self, score: float, confidence: float) -> str:
        """Suggest position size based on score and confidence"""
        combined = (score + confidence) / 2
        
        if combined >= 80:
            return "FULL"
        elif combined >= 70:
            return "3/4"
        elif combined >= 60:
            return "1/2"
        elif combined >= 50:
            return "1/4"
        else:
            return "MINIMUM"
    
    def _suggest_stop_loss(self, signal: Dict[str, Any]) -> float:
        """Suggest stop loss percentage"""
        # Base on probability and premium
        prob = signal.get('probability_itm', 50)
        
        if prob >= 70:
            return 0.25  # 25% stop loss for high probability
        elif prob >= 50:
            return 0.35  # 35% stop loss
        else:
            return 0.50  # 50% stop loss for low probability
    
    def _suggest_take_profit(self, signal: Dict[str, Any]) -> float:
        """Suggest take profit percentage"""
        # Base on probability and premium
        prob = signal.get('probability_itm', 50)
        
        if prob >= 70:
            return 0.50  # 50% profit target for high probability
        elif prob >= 50:
            return 1.00  # 100% profit target
        else:
            return 2.00  # 200% profit target for low probability
