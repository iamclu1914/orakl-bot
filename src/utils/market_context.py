"""
Market Context Analysis Utility
Provides market regime classification and volatility analysis
"""
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import numpy as np

logger = logging.getLogger(__name__)

class MarketContext:
    """Analyze and classify market conditions"""
    
    # Market regime thresholds
    VIX_HIGH_THRESHOLD = 20
    VIX_EXTREME_THRESHOLD = 30
    MOMENTUM_STRONG_THRESHOLD = 1.0
    MOMENTUM_WEAK_THRESHOLD = 0.3
    
    # Sector ETFs for rotation analysis
    SECTOR_ETFS = {
        'XLK': 'Technology',
        'XLF': 'Financials',
        'XLE': 'Energy',
        'XLV': 'Healthcare',
        'XLI': 'Industrials',
        'XLY': 'Consumer Discretionary',
        'XLP': 'Consumer Staples',
        'XLU': 'Utilities',
        'XLRE': 'Real Estate',
        'XLB': 'Materials',
        'XLC': 'Communication Services'
    }
    
    @staticmethod
    async def get_market_context(fetcher) -> Dict:
        """
        Analyze current market conditions
        Returns comprehensive market analysis
        """
        try:
            context = {
                'timestamp': datetime.now(),
                'volatility': await MarketContext._get_volatility_regime(fetcher),
                'trend': await MarketContext._get_market_trend(fetcher),
                'momentum': await MarketContext._get_market_momentum(fetcher),
                'sectors': await MarketContext._get_sector_strength(fetcher),
                'regime': 'normal',  # Will be calculated
                'trading_bias': 'neutral',  # Will be calculated
                'risk_level': 'medium'  # Will be calculated
            }
            
            # Classify overall market regime
            context['regime'] = MarketContext._classify_regime(context)
            context['trading_bias'] = MarketContext._determine_trading_bias(context)
            context['risk_level'] = MarketContext._assess_risk_level(context)
            
            return context
            
        except Exception as e:
            logger.error(f"Error analyzing market context: {e}")
            return MarketContext._get_default_context()
    
    @staticmethod
    async def _get_volatility_regime(fetcher) -> Dict:
        """Analyze volatility using VIX"""
        try:
            # Get VIX current level
            vix_price = await fetcher.get_stock_price('VIX')
            if not vix_price:
                return {'level': 'unknown', 'vix': None}
            
            # Get VIX 20-day average
            vix_bars = await fetcher.get_aggregates(
                'VIX', 'day', 1,
                (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d'),
                datetime.now().strftime('%Y-%m-%d')
            )
            
            vix_avg = vix_bars['close'].mean() if not vix_bars.empty else vix_price
            
            # Classify volatility
            if vix_price >= MarketContext.VIX_EXTREME_THRESHOLD:
                level = 'extreme'
            elif vix_price >= MarketContext.VIX_HIGH_THRESHOLD:
                level = 'high'
            elif vix_price < 15:
                level = 'low'
            else:
                level = 'normal'
            
            return {
                'level': level,
                'vix': vix_price,
                'vix_avg': vix_avg,
                'vix_trend': 'rising' if vix_price > vix_avg else 'falling'
            }
            
        except Exception as e:
            logger.error(f"Error getting volatility regime: {e}")
            return {'level': 'unknown', 'vix': None}
    
    @staticmethod
    async def _get_market_trend(fetcher) -> Dict:
        """Analyze SPY trend across multiple timeframes"""
        try:
            # Get SPY data
            spy_bars = await fetcher.get_aggregates(
                'SPY', 'day', 1,
                (datetime.now() - timedelta(days=50)).strftime('%Y-%m-%d'),
                datetime.now().strftime('%Y-%m-%d')
            )
            
            if spy_bars.empty:
                return {'direction': 'unknown', 'strength': 0}
            
            # Calculate moving averages
            spy_bars['sma_20'] = spy_bars['close'].rolling(20).mean()
            spy_bars['sma_50'] = spy_bars['close'].rolling(50).mean()
            
            current_price = spy_bars.iloc[-1]['close']
            sma_20 = spy_bars.iloc[-1]['sma_20']
            sma_50 = spy_bars.iloc[-1]['sma_50'] if len(spy_bars) >= 50 else sma_20
            
            # Determine trend
            if current_price > sma_20 > sma_50:
                direction = 'bullish'
                strength = ((current_price - sma_50) / sma_50) * 100
            elif current_price < sma_20 < sma_50:
                direction = 'bearish'
                strength = ((sma_50 - current_price) / sma_50) * 100
            else:
                direction = 'choppy'
                strength = abs((current_price - sma_20) / sma_20) * 100
            
            return {
                'direction': direction,
                'strength': min(strength, 10),  # Cap at 10%
                'above_20ma': current_price > sma_20,
                'above_50ma': current_price > sma_50
            }
            
        except Exception as e:
            logger.error(f"Error analyzing market trend: {e}")
            return {'direction': 'unknown', 'strength': 0}
    
    @staticmethod
    async def _get_market_momentum(fetcher) -> Dict:
        """Calculate SPY momentum across timeframes"""
        try:
            # Get intraday data
            spy_bars = await fetcher.get_aggregates(
                'SPY', 'minute', 5,
                datetime.now().strftime('%Y-%m-%d'),
                datetime.now().strftime('%Y-%m-%d')
            )
            
            if spy_bars.empty or len(spy_bars) < 10:
                return {'intraday': 0, 'direction': 'neutral'}
            
            # Calculate momentum
            momentum_5m = ((spy_bars.iloc[-1]['close'] - spy_bars.iloc[-6]['close']) / 
                          spy_bars.iloc[-6]['close']) * 100
            
            momentum_30m = ((spy_bars.iloc[-1]['close'] - spy_bars.iloc[0]['close']) / 
                           spy_bars.iloc[0]['close']) * 100
            
            # Volume analysis
            avg_volume = spy_bars['volume'].mean()
            recent_volume = spy_bars.iloc[-3:]['volume'].mean()
            volume_surge = recent_volume / avg_volume if avg_volume > 0 else 1
            
            return {
                'intraday': momentum_30m,
                'momentum_5m': momentum_5m,
                'direction': 'bullish' if momentum_30m > 0.2 else 'bearish' if momentum_30m < -0.2 else 'neutral',
                'strength': abs(momentum_30m),
                'volume_surge': volume_surge > 1.5,
                'accelerating': abs(momentum_5m) > abs(momentum_30m)
            }
            
        except Exception as e:
            logger.error(f"Error calculating market momentum: {e}")
            return {'intraday': 0, 'direction': 'neutral'}
    
    @staticmethod
    async def _get_sector_strength(fetcher) -> Dict:
        """Analyze sector rotation and strength"""
        try:
            sector_performance = {}
            
            for etf, sector in MarketContext.SECTOR_ETFS.items():
                try:
                    # Get today's performance
                    bars = await fetcher.get_aggregates(
                        etf, 'day', 1,
                        datetime.now().strftime('%Y-%m-%d'),
                        datetime.now().strftime('%Y-%m-%d')
                    )
                    
                    if not bars.empty:
                        daily_change = ((bars.iloc[-1]['close'] - bars.iloc[-1]['open']) / 
                                      bars.iloc[-1]['open']) * 100
                        sector_performance[sector] = daily_change
                        
                except Exception:
                    continue
            
            if not sector_performance:
                return {'leaders': [], 'laggards': [], 'rotation': 'unknown'}
            
            # Sort sectors by performance
            sorted_sectors = sorted(sector_performance.items(), key=lambda x: x[1], reverse=True)
            
            return {
                'leaders': [s[0] for s in sorted_sectors[:3]],
                'laggards': [s[0] for s in sorted_sectors[-3:]],
                'rotation': 'risk-on' if sorted_sectors[0][0] in ['Technology', 'Consumer Discretionary'] else 'risk-off',
                'performance': dict(sorted_sectors[:5])  # Top 5 sectors
            }
            
        except Exception as e:
            logger.error(f"Error analyzing sector strength: {e}")
            return {'leaders': [], 'laggards': [], 'rotation': 'unknown'}
    
    @staticmethod
    def _classify_regime(context: Dict) -> str:
        """Classify overall market regime based on multiple factors"""
        volatility = context['volatility']['level']
        trend = context['trend']['direction']
        momentum = context['momentum']['direction']
        
        # Extreme volatility overrides everything
        if volatility == 'extreme':
            return 'crisis'
        
        # High volatility scenarios
        if volatility == 'high':
            if trend == 'bearish':
                return 'correction'
            else:
                return 'volatile'
        
        # Normal volatility scenarios
        if trend == 'bullish' and momentum == 'bullish':
            return 'trending_up'
        elif trend == 'bearish' and momentum == 'bearish':
            return 'trending_down'
        elif trend == 'choppy':
            return 'range_bound'
        else:
            return 'transitional'
    
    @staticmethod
    def _determine_trading_bias(context: Dict) -> str:
        """Determine optimal trading bias based on market conditions"""
        regime = context['regime']
        momentum_strength = context['momentum']['strength']
        
        bias_map = {
            'trending_up': 'bullish' if momentum_strength > 0.5 else 'neutral_bullish',
            'trending_down': 'bearish' if momentum_strength > 0.5 else 'neutral_bearish',
            'range_bound': 'neutral',
            'volatile': 'cautious',
            'correction': 'bearish',
            'crisis': 'defensive',
            'transitional': 'neutral'
        }
        
        return bias_map.get(regime, 'neutral')
    
    @staticmethod
    def _assess_risk_level(context: Dict) -> str:
        """Assess overall market risk level"""
        vix = context['volatility']['vix'] or 20
        regime = context['regime']
        
        if regime in ['crisis', 'correction'] or vix > 30:
            return 'high'
        elif regime in ['volatile', 'transitional'] or vix > 20:
            return 'medium'
        else:
            return 'low'
    
    @staticmethod
    def _get_default_context() -> Dict:
        """Return default context when analysis fails"""
        return {
            'timestamp': datetime.now(),
            'volatility': {'level': 'unknown', 'vix': None},
            'trend': {'direction': 'unknown', 'strength': 0},
            'momentum': {'intraday': 0, 'direction': 'neutral'},
            'sectors': {'leaders': [], 'laggards': [], 'rotation': 'unknown'},
            'regime': 'unknown',
            'trading_bias': 'neutral',
            'risk_level': 'medium'
        }
    
    @staticmethod
    def adjust_signal_threshold(base_threshold: int, market_context: Dict) -> int:
        """Adjust signal threshold based on market conditions"""
        threshold = base_threshold
        
        # Increase threshold in high-risk environments
        if market_context['risk_level'] == 'high':
            threshold += 10
        elif market_context['risk_level'] == 'medium':
            threshold += 5
        
        # Adjust for market regime
        regime_adjustments = {
            'trending_up': -5,    # Lower threshold in strong trends
            'trending_down': -5,
            'volatile': +5,       # Higher threshold in volatile markets
            'correction': +10,
            'crisis': +15,
            'range_bound': 0,
            'transitional': +5
        }
        
        threshold += regime_adjustments.get(market_context['regime'], 0)
        
        # Ensure threshold stays within reasonable bounds
        return max(60, min(90, threshold))
