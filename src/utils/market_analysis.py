"""
Market analysis utilities for ORAKL Bot
Provides market context and advanced analytics
"""

import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass
from enum import Enum
import logging
from scipy import stats
from collections import deque

logger = logging.getLogger(__name__)


class MarketRegime(Enum):
    """Market regime classifications"""
    STRONG_BULL = "strong_bull"
    BULL = "bull"
    NEUTRAL = "neutral"
    BEAR = "bear"
    STRONG_BEAR = "strong_bear"
    HIGH_VOLATILITY = "high_volatility"


class TrendDirection(Enum):
    """Trend direction classifications"""
    STRONG_UP = "strong_up"
    UP = "up"
    SIDEWAYS = "sideways"
    DOWN = "down"
    STRONG_DOWN = "strong_down"


@dataclass
class MarketContext:
    """Market context data"""
    regime: MarketRegime
    trend: TrendDirection
    volatility: float
    vix: Optional[float]
    put_call_ratio: Optional[float]
    market_breadth: Optional[float]
    sector_rotation: Optional[Dict[str, float]]
    fear_greed_index: Optional[int]
    volume_profile: Optional[Dict[str, float]]
    timestamp: datetime


class MarketAnalyzer:
    """Advanced market analysis and context"""
    
    def __init__(self):
        self.market_data_cache = {}
        self.regime_history = deque(maxlen=100)
        self.volatility_history = deque(maxlen=252)  # 1 year of daily data
        
    async def get_market_context(self, symbol: str, prices: pd.DataFrame) -> MarketContext:
        """
        Get comprehensive market context
        
        Args:
            symbol: Stock symbol
            prices: DataFrame with OHLCV data
            
        Returns:
            MarketContext object
        """
        try:
            # Calculate various market indicators
            regime = self._detect_market_regime(prices)
            trend = self._detect_trend(prices)
            volatility = self._calculate_volatility(prices)
            
            # Get additional market data (would need actual API calls)
            vix = await self._get_vix_level()
            pcr = await self._get_put_call_ratio()
            breadth = await self._get_market_breadth()
            
            # Create context
            context = MarketContext(
                regime=regime,
                trend=trend,
                volatility=volatility,
                vix=vix,
                put_call_ratio=pcr,
                market_breadth=breadth,
                sector_rotation=None,  # TODO: Implement
                fear_greed_index=None,  # TODO: Implement
                volume_profile=self._analyze_volume_profile(prices),
                timestamp=datetime.now()
            )
            
            # Store in history
            self.regime_history.append((symbol, context))
            
            return context
            
        except Exception as e:
            logger.error(f"Error getting market context: {e}")
            # Return neutral context on error
            return MarketContext(
                regime=MarketRegime.NEUTRAL,
                trend=TrendDirection.SIDEWAYS,
                volatility=0.2,
                vix=None,
                put_call_ratio=None,
                market_breadth=None,
                sector_rotation=None,
                fear_greed_index=None,
                volume_profile=None,
                timestamp=datetime.now()
            )
    
    def _detect_market_regime(self, prices: pd.DataFrame) -> MarketRegime:
        """Detect current market regime using multiple indicators"""
        if prices.empty or len(prices) < 20:
            return MarketRegime.NEUTRAL
        
        try:
            # Calculate returns
            returns = prices['close'].pct_change().dropna()
            
            # Short-term vs long-term performance
            sma_20 = prices['close'].rolling(20).mean().iloc[-1]
            sma_50 = prices['close'].rolling(50).mean().iloc[-1] if len(prices) >= 50 else sma_20
            sma_200 = prices['close'].rolling(200).mean().iloc[-1] if len(prices) >= 200 else sma_50
            
            current_price = prices['close'].iloc[-1]
            
            # Calculate regime score
            score = 0
            
            # Price vs moving averages
            if current_price > sma_20:
                score += 1
            if current_price > sma_50:
                score += 1
            if current_price > sma_200:
                score += 2
            
            # Moving average alignment
            if sma_20 > sma_50 > sma_200:
                score += 2
            elif sma_20 < sma_50 < sma_200:
                score -= 2
            
            # Recent performance
            week_return = returns.tail(5).sum()
            month_return = returns.tail(20).sum()
            
            if week_return > 0.03:  # 3% weekly gain
                score += 1
            elif week_return < -0.03:
                score -= 1
            
            if month_return > 0.05:  # 5% monthly gain
                score += 1
            elif month_return < -0.05:
                score -= 1
            
            # Volatility check
            volatility = returns.std() * np.sqrt(252)
            if volatility > 0.4:  # High volatility (40%+ annualized)
                return MarketRegime.HIGH_VOLATILITY
            
            # Determine regime based on score
            if score >= 5:
                return MarketRegime.STRONG_BULL
            elif score >= 2:
                return MarketRegime.BULL
            elif score <= -5:
                return MarketRegime.STRONG_BEAR
            elif score <= -2:
                return MarketRegime.BEAR
            else:
                return MarketRegime.NEUTRAL
                
        except Exception as e:
            logger.debug(f"Error detecting market regime: {e}")
            return MarketRegime.NEUTRAL
    
    def _detect_trend(self, prices: pd.DataFrame) -> TrendDirection:
        """Detect price trend using advanced techniques"""
        if prices.empty or len(prices) < 10:
            return TrendDirection.SIDEWAYS
        
        try:
            closes = prices['close'].values
            
            # Linear regression on log prices
            x = np.arange(len(closes))
            log_prices = np.log(closes)
            slope, intercept, r_value, p_value, std_err = stats.linregress(x, log_prices)
            
            # Convert to annualized return
            daily_return = np.exp(slope) - 1
            annual_return = (1 + daily_return) ** 252 - 1
            
            # Trend strength based on R-squared and slope
            r_squared = r_value ** 2
            
            if r_squared < 0.3:  # Weak trend
                return TrendDirection.SIDEWAYS
            
            if annual_return > 0.5:  # 50%+ annual
                return TrendDirection.STRONG_UP
            elif annual_return > 0.15:  # 15%+ annual
                return TrendDirection.UP
            elif annual_return < -0.3:  # -30% annual
                return TrendDirection.STRONG_DOWN
            elif annual_return < -0.1:  # -10% annual
                return TrendDirection.DOWN
            else:
                return TrendDirection.SIDEWAYS
                
        except Exception as e:
            logger.debug(f"Error detecting trend: {e}")
            return TrendDirection.SIDEWAYS
    
    def _calculate_volatility(self, prices: pd.DataFrame) -> float:
        """Calculate various volatility measures"""
        if prices.empty or len(prices) < 2:
            return 0.2  # Default 20% volatility
        
        try:
            returns = prices['close'].pct_change().dropna()
            
            # Standard deviation (historical volatility)
            hist_vol = returns.std() * np.sqrt(252)
            
            # Parkinson volatility (using high-low)
            if 'high' in prices and 'low' in prices:
                hl_ratio = np.log(prices['high'] / prices['low'])
                parkinson_vol = np.sqrt(1 / (4 * np.log(2)) * (hl_ratio ** 2).mean()) * np.sqrt(252)
            else:
                parkinson_vol = hist_vol
            
            # GARCH would go here for more sophisticated modeling
            
            # Use average of methods
            volatility = (hist_vol + parkinson_vol) / 2
            
            # Store in history
            self.volatility_history.append(volatility)
            
            return volatility
            
        except Exception as e:
            logger.debug(f"Error calculating volatility: {e}")
            return 0.2
    
    def _analyze_volume_profile(self, prices: pd.DataFrame) -> Dict[str, float]:
        """Analyze volume distribution"""
        if prices.empty or 'volume' not in prices:
            return {}
        
        try:
            volumes = prices['volume']
            prices_close = prices['close']
            
            # Volume-weighted average price
            vwap = (prices_close * volumes).sum() / volumes.sum()
            
            # Volume concentration
            total_volume = volumes.sum()
            top_20_percent_days = int(len(volumes) * 0.2)
            top_volume = volumes.nlargest(top_20_percent_days).sum()
            volume_concentration = top_volume / total_volume
            
            # Relative volume
            avg_volume = volumes.mean()
            recent_volume = volumes.tail(5).mean()
            relative_volume = recent_volume / avg_volume if avg_volume > 0 else 1
            
            return {
                'vwap': vwap,
                'volume_concentration': volume_concentration,
                'relative_volume': relative_volume,
                'avg_daily_volume': avg_volume,
                'recent_volume': recent_volume
            }
            
        except Exception as e:
            logger.debug(f"Error analyzing volume profile: {e}")
            return {}
    
    async def _get_vix_level(self) -> Optional[float]:
        """Get current VIX level (placeholder)"""
        # TODO: Implement actual VIX fetching
        return None
    
    async def _get_put_call_ratio(self) -> Optional[float]:
        """Get market-wide put/call ratio (placeholder)"""
        # TODO: Implement actual PCR fetching
        return None
    
    async def _get_market_breadth(self) -> Optional[float]:
        """Get market breadth indicators (placeholder)"""
        # TODO: Implement actual breadth calculation
        return None
    
    def calculate_context_score(self, context: MarketContext, signal_type: str) -> float:
        """
        Calculate how favorable the market context is for a signal
        
        Args:
            context: Current market context
            signal_type: Type of signal (CALL/PUT)
            
        Returns:
            Score from 0-100
        """
        score = 50  # Neutral baseline
        
        # Regime alignment
        if signal_type == "CALL":
            if context.regime == MarketRegime.STRONG_BULL:
                score += 20
            elif context.regime == MarketRegime.BULL:
                score += 10
            elif context.regime == MarketRegime.BEAR:
                score -= 10
            elif context.regime == MarketRegime.STRONG_BEAR:
                score -= 20
            elif context.regime == MarketRegime.HIGH_VOLATILITY:
                score += 5  # Options benefit from volatility
        else:  # PUT
            if context.regime == MarketRegime.STRONG_BEAR:
                score += 20
            elif context.regime == MarketRegime.BEAR:
                score += 10
            elif context.regime == MarketRegime.BULL:
                score -= 10
            elif context.regime == MarketRegime.STRONG_BULL:
                score -= 20
            elif context.regime == MarketRegime.HIGH_VOLATILITY:
                score += 5
        
        # Trend alignment
        if signal_type == "CALL":
            if context.trend == TrendDirection.STRONG_UP:
                score += 15
            elif context.trend == TrendDirection.UP:
                score += 7
            elif context.trend == TrendDirection.DOWN:
                score -= 7
            elif context.trend == TrendDirection.STRONG_DOWN:
                score -= 15
        else:  # PUT
            if context.trend == TrendDirection.STRONG_DOWN:
                score += 15
            elif context.trend == TrendDirection.DOWN:
                score += 7
            elif context.trend == TrendDirection.UP:
                score -= 7
            elif context.trend == TrendDirection.STRONG_UP:
                score -= 15
        
        # Volatility impact
        if context.volatility > 0.3:  # High volatility
            score += 5  # Good for options premium
        elif context.volatility < 0.1:  # Very low volatility
            score -= 10  # Poor for options
        
        # VIX impact
        if context.vix:
            if context.vix > 30:  # High fear
                if signal_type == "PUT":
                    score += 10
                else:
                    score -= 5
            elif context.vix < 15:  # Low fear/complacency
                if signal_type == "CALL":
                    score += 5
                else:
                    score -= 5
        
        # Put/Call ratio impact
        if context.put_call_ratio:
            if context.put_call_ratio > 1.2:  # Bearish sentiment
                if signal_type == "CALL":
                    score += 5  # Contrarian
                else:
                    score -= 5
            elif context.put_call_ratio < 0.8:  # Bullish sentiment
                if signal_type == "PUT":
                    score += 5  # Contrarian
                else:
                    score -= 5
        
        # Ensure score is within bounds
        return max(0, min(100, score))


class AdvancedScoring:
    """Advanced scoring algorithms for signals"""
    
    @staticmethod
    def calculate_signal_score(
        base_score: float,
        market_context: MarketContext,
        signal_metrics: Dict[str, Any],
        signal_type: str
    ) -> Dict[str, float]:
        """
        Calculate comprehensive signal score with market context
        
        Args:
            base_score: Base score from bot logic
            market_context: Current market context
            signal_metrics: Signal-specific metrics
            signal_type: Type of signal
            
        Returns:
            Dictionary with various score components
        """
        # Get market context score
        analyzer = MarketAnalyzer()
        context_score = analyzer.calculate_context_score(market_context, signal_type)
        
        # Calculate components
        volume_score = AdvancedScoring._calculate_volume_score(signal_metrics)
        momentum_score = AdvancedScoring._calculate_momentum_score(signal_metrics)
        probability_score = AdvancedScoring._calculate_probability_score(signal_metrics)
        flow_score = AdvancedScoring._calculate_flow_score(signal_metrics)
        
        # Weighted average
        weights = {
            'base': 0.25,
            'context': 0.20,
            'volume': 0.15,
            'momentum': 0.15,
            'probability': 0.15,
            'flow': 0.10
        }
        
        scores = {
            'base': base_score,
            'context': context_score,
            'volume': volume_score,
            'momentum': momentum_score,
            'probability': probability_score,
            'flow': flow_score
        }
        
        # Calculate weighted total
        total_score = sum(scores[k] * weights[k] for k in scores)
        
        return {
            **scores,
            'total': total_score,
            'confidence': AdvancedScoring._calculate_confidence(scores)
        }
    
    @staticmethod
    def _calculate_volume_score(metrics: Dict[str, Any]) -> float:
        """Calculate volume-based score"""
        score = 50
        
        # Volume vs average
        if 'volume_ratio' in metrics:
            ratio = metrics['volume_ratio']
            if ratio >= 5:
                score = 90
            elif ratio >= 3:
                score = 75
            elif ratio >= 2:
                score = 65
            elif ratio >= 1.5:
                score = 55
        
        # Volume vs open interest
        if 'vol_oi_ratio' in metrics:
            vol_oi = metrics['vol_oi_ratio']
            if vol_oi >= 2:
                score = min(100, score + 20)
            elif vol_oi >= 1:
                score = min(100, score + 10)
        
        return score
    
    @staticmethod
    def _calculate_momentum_score(metrics: Dict[str, Any]) -> float:
        """Calculate momentum-based score"""
        score = 50
        
        # Price momentum
        if 'price_change_pct' in metrics:
            change = abs(metrics['price_change_pct'])
            if change >= 5:
                score = 85
            elif change >= 3:
                score = 70
            elif change >= 2:
                score = 60
            elif change >= 1:
                score = 55
        
        # RSI if available
        if 'rsi' in metrics:
            rsi = metrics['rsi']
            if 30 <= rsi <= 70:
                score = min(100, score + 10)
            elif rsi < 20 or rsi > 80:
                score = min(100, score + 20)
        
        return score
    
    @staticmethod
    def _calculate_probability_score(metrics: Dict[str, Any]) -> float:
        """Calculate probability-based score"""
        if 'probability_itm' not in metrics:
            return 50
        
        prob = metrics['probability_itm']
        
        # Optimal probability range (not too high, not too low)
        if 40 <= prob <= 60:
            return 85  # Sweet spot
        elif 30 <= prob <= 70:
            return 70
        elif 20 <= prob <= 80:
            return 55
        elif prob > 80:
            return 40  # Too safe, low reward
        else:
            return 30  # Too risky
    
    @staticmethod
    def _calculate_flow_score(metrics: Dict[str, Any]) -> float:
        """Calculate options flow score"""
        score = 50
        
        # Premium size
        if 'premium' in metrics:
            premium = metrics['premium']
            if premium >= 1000000:
                score = 95
            elif premium >= 500000:
                score = 80
            elif premium >= 100000:
                score = 65
            elif premium >= 50000:
                score = 55
        
        # Repeat signals
        if 'repeat_count' in metrics:
            repeats = metrics['repeat_count']
            if repeats >= 5:
                score = min(100, score + 20)
            elif repeats >= 3:
                score = min(100, score + 10)
        
        return score
    
    @staticmethod
    def _calculate_confidence(scores: Dict[str, float]) -> float:
        """Calculate overall confidence based on score consistency"""
        values = [v for k, v in scores.items() if k not in ['total', 'confidence']]
        
        if not values:
            return 50
        
        # High confidence if all scores are aligned
        std_dev = np.std(values)
        mean_score = np.mean(values)
        
        if std_dev < 10 and mean_score > 70:
            return 90  # High confidence, good scores
        elif std_dev < 15 and mean_score > 60:
            return 75  # Good confidence
        elif std_dev < 20:
            return 60  # Moderate confidence
        else:
            return 40  # Low confidence due to mixed signals
