"""
Enhanced Analysis Utilities
Critical features for high-probability signal detection

Includes the Four Axes Framework:
- P (Price Trend): Volatility-adjusted price trend (-1 to +1)
- V (Volatility Trend): Realized volatility expansion/contraction
- G (Gamma Ratio): Call/put gamma positioning (0 to 1)
"""
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, Optional, Sequence, Tuple
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# =============================================================================
# Four Axes Framework: MarketContext
# =============================================================================

@dataclass
class MarketContext:
    """
    Complete market context for a symbol using the Four Axes framework.
    
    P (Price Trend): Volatility-adjusted trend indicator (-1 to +1)
        +1 = Strong uptrend (nearly every day up)
        -1 = Strong downtrend (nearly every day down)
        0  = Choppy/neutral
    
    V (Volatility Trend): Realized volatility expansion/contraction
        Positive = Volatility expanding (larger moves)
        Negative = Volatility contracting (smaller moves)
    
    G (Gamma Ratio): Options market positioning (0 to 1)
        1.0 = All call gamma (call-driven)
        0.5 = Balanced
        0.0 = All put gamma (put-driven)
    """
    symbol: str
    P: float  # Price trend (-1 to +1)
    V: float  # Volatility trend
    G: float  # Gamma ratio (0 to 1)
    timestamp: datetime = None
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.utcnow()
    
    @property
    def regime(self) -> str:
        """
        Classify overall market regime based on P and G alignment.
        
        Returns one of:
        - BULLISH_CALL_DRIVEN: Price up + call gamma dominant
        - BEARISH_PUT_DRIVEN: Price down + put gamma dominant
        - BULLISH_PUT_HEDGED: Price up but put gamma dominant (reversal risk)
        - BEARISH_CALL_HEDGED: Price down but call gamma dominant (bounce potential)
        - VOLATILITY_EXPANSION: Neutral trend but vol expanding
        - VOLATILITY_CONTRACTION: Neutral trend but vol contracting
        - NEUTRAL: No clear regime
        """
        # Strong alignment regimes
        if self.P > 0.3 and self.G > 0.6:
            return "BULLISH_CALL_DRIVEN"
        elif self.P < -0.3 and self.G < 0.4:
            return "BEARISH_PUT_DRIVEN"
        
        # Misaligned regimes (potential reversals)
        elif self.P > 0.3 and self.G < 0.4:
            return "BULLISH_PUT_HEDGED"  # Uptrend but puts dominating - caution
        elif self.P < -0.3 and self.G > 0.6:
            return "BEARISH_CALL_HEDGED"  # Downtrend but calls dominating - bounce?
        
        # Volatility regimes
        elif abs(self.V) > 0.015:
            return "VOLATILITY_EXPANSION" if self.V > 0 else "VOLATILITY_CONTRACTION"
        
        return "NEUTRAL"
    
    @property
    def conviction_multiplier(self) -> float:
        """
        Score multiplier based on alignment of P and G axes.
        
        Returns:
        - 1.0 to 1.3: Aligned (boost conviction)
        - 1.0: Neutral
        - 0.7 to 1.0: Misaligned (reduce conviction)
        """
        # Bullish alignment: P positive + G call-driven
        if self.P > 0 and self.G > 0.5:
            alignment = min(self.P, (self.G - 0.5) * 2)  # 0 to 1
            return 1.0 + (alignment * 0.3)  # Up to 30% boost
        
        # Bearish alignment: P negative + G put-driven
        if self.P < 0 and self.G < 0.5:
            alignment = min(abs(self.P), (0.5 - self.G) * 2)
            return 1.0 + (alignment * 0.3)  # Up to 30% boost
        
        # Misaligned = lower conviction (fighting gamma)
        if (self.P > 0.2 and self.G < 0.4) or (self.P < -0.2 and self.G > 0.6):
            return 0.7  # 30% penalty for fighting gamma
        
        return 1.0
    
    @property
    def regime_emoji(self) -> str:
        """Get emoji representation for the regime."""
        emojis = {
            "BULLISH_CALL_DRIVEN": "🟢📈",
            "BEARISH_PUT_DRIVEN": "🔴📉",
            "BULLISH_PUT_HEDGED": "🟡⚠️",
            "BEARISH_CALL_HEDGED": "🟡🔄",
            "VOLATILITY_EXPANSION": "📊⬆️",
            "VOLATILITY_CONTRACTION": "📊⬇️",
            "NEUTRAL": "⚪",
        }
        return emojis.get(self.regime, "⚪")
    
    def format_summary(self) -> str:
        """Format a brief summary string for Discord embeds."""
        return f"P={self.P:+.2f} | V={self.V:+.3f} | G={self.G:.2f}"
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for serialization."""
        return {
            "symbol": self.symbol,
            "P": round(self.P, 4),
            "V": round(self.V, 4),
            "G": round(self.G, 4),
            "regime": self.regime,
            "conviction_multiplier": round(self.conviction_multiplier, 2),
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
        }


def should_take_signal(
    signal_type: str,
    context: MarketContext,
    strict: bool = False
) -> Tuple[bool, str]:
    """
    Determine if a signal aligns with market context.
    
    Args:
        signal_type: "CALL" or "PUT"
        context: MarketContext object
        strict: If True, require strong alignment; if False, allow neutral
    
    Returns:
        Tuple of (should_take, reason)
    """
    signal_type = signal_type.upper()
    
    if signal_type == "CALL":
        # CALL signals: Want P positive or G call-driven
        if context.P < -0.3 and context.G < 0.4:
            return False, f"Fighting bearish trend (P={context.P:.2f}, G={context.G:.2f})"
        
        if context.P > 0.2 and context.G > 0.5:
            return True, f"Aligned bullish (P={context.P:.2f}, G={context.G:.2f})"
        
        if context.G > 0.65:
            return True, f"Strong call gamma (G={context.G:.2f})"
        
        if strict and context.P < 0:
            return False, f"Strict mode: P negative (P={context.P:.2f})"
            
    elif signal_type == "PUT":
        # PUT signals: Want P negative or G put-driven
        if context.P > 0.3 and context.G > 0.6:
            return False, f"Fighting bullish trend (P={context.P:.2f}, G={context.G:.2f})"
        
        if context.P < -0.2 and context.G < 0.5:
            return True, f"Aligned bearish (P={context.P:.2f}, G={context.G:.2f})"
        
        if context.G < 0.35:
            return True, f"Strong put gamma (G={context.G:.2f})"
        
        if strict and context.P > 0:
            return False, f"Strict mode: P positive (P={context.P:.2f})"
    
    # Neutral - allow but don't boost
    return True, "Neutral context"


class EnhancedAnalyzer:
    """Enhanced analysis utilities for all bots"""

    def __init__(self, fetcher):
        self.fetcher = fetcher
        self.volume_cache = {}  # Cache 30-day averages
        self.price_action_cache = {}  # Cache intraday price data for alignment checks
        self.trend_cache: Dict[Tuple[str, str], Dict[str, object]] = {}
        self.market_context_cache: Dict[str, Dict] = {}  # Cache for Four Axes context
        self.daily_closes_cache: Dict[str, Dict] = {}  # Cache for daily close prices

    # =========================================================================
    # Four Axes Framework: P (Price Trend) and V (Volatility Trend)
    # =========================================================================

    async def _get_daily_closes(self, symbol: str, days: int = 42) -> Optional[np.ndarray]:
        """
        Fetch daily closing prices with caching.
        
        Args:
            symbol: Stock symbol
            days: Number of days to fetch
            
        Returns:
            numpy array of closing prices or None if unavailable
        """
        try:
            # Check cache (refresh every 5 minutes during market hours)
            cache_key = f"{symbol}_{days}"
            now = datetime.utcnow()
            
            if cache_key in self.daily_closes_cache:
                cached = self.daily_closes_cache[cache_key]
                age_sec = (now - cached["timestamp"]).total_seconds()
                if age_sec < 300:  # 5-minute TTL
                    return cached["closes"]
            
            # Fetch from API
            from_date = (now - timedelta(days=days + 10)).strftime('%Y-%m-%d')  # Extra buffer
            to_date = now.strftime('%Y-%m-%d')
            
            bars = await self.fetcher.get_aggregates(
                symbol,
                timespan='day',
                multiplier=1,
                from_date=from_date,
                to_date=to_date
            )
            
            if bars.empty or len(bars) < days // 2:
                logger.debug(f"Insufficient daily data for {symbol}: {len(bars)} bars")
                return None
            
            closes = bars['close'].to_numpy(dtype=float)
            
            # Cache the result
            self.daily_closes_cache[cache_key] = {
                "timestamp": now,
                "closes": closes
            }
            
            # Cleanup old cache entries
            if len(self.daily_closes_cache) > 200:
                cutoff = now - timedelta(minutes=10)
                self.daily_closes_cache = {
                    k: v for k, v in self.daily_closes_cache.items()
                    if v["timestamp"] > cutoff
                }
            
            return closes
            
        except Exception as e:
            logger.error(f"Error fetching daily closes for {symbol}: {e}")
            return None

    async def compute_price_trend(self, symbol: str, period: int = 21) -> Optional[float]:
        """
        Compute volatility-adjusted price trend (P) from the Four Axes framework.
        
        Formula: P = mean(daily_returns) / mean(abs(daily_returns))
        
        This normalizes trend by realized volatility, making it comparable across
        time periods and assets. The result oscillates between -1 and +1.
        
        Args:
            symbol: Stock symbol
            period: Lookback period in trading days (default 21 = ~1 month)
            
        Returns:
            P value between -1 and +1, or None if data unavailable
            +1 = Nearly every day was up (strong uptrend)
            -1 = Nearly every day was down (strong downtrend)
             0 = Choppy/neutral
        """
        try:
            # Need period + 1 days for returns calculation
            closes = await self._get_daily_closes(symbol, period + 5)
            
            if closes is None or len(closes) < period + 1:
                return None
            
            # Calculate daily percentage returns
            # ccr = (close[t] - close[t-1]) / close[t-1]
            ccr = np.diff(closes) / closes[:-1]
            
            if len(ccr) < period:
                return None
            
            # Use only the most recent 'period' returns
            ccr_window = ccr[-period:]
            
            # Absolute returns (volatility proxy)
            ccv = np.abs(ccr_window)
            
            # Moving averages
            ma = np.mean(ccr_window)   # Average return
            mad = np.mean(ccv)          # Average absolute return (mean absolute deviation)
            
            if mad == 0 or np.isnan(mad):
                return 0.0
            
            # P = trend / volatility
            P = ma / mad
            
            # Clip to [-1, 1] range
            return float(np.clip(P, -1.0, 1.0))
            
        except Exception as e:
            logger.error(f"Error computing price trend for {symbol}: {e}")
            return None

    async def compute_volatility_trend(self, symbol: str, period: int = 21) -> Optional[float]:
        """
        Compute volatility trend (V) from the Four Axes framework.
        
        Formula: V = mad_recent - mad_prior
        
        Where mad = mean absolute deviation of daily returns.
        Positive V means volatility is expanding, negative means contracting.
        
        Args:
            symbol: Stock symbol
            period: Lookback period for each window (default 21 = ~1 month)
            
        Returns:
            V value (typically -0.05 to +0.05), or None if data unavailable
            Positive = Volatility expanding (larger daily moves)
            Negative = Volatility contracting (smaller daily moves)
        """
        try:
            # Need period * 2 + 1 days for two windows
            closes = await self._get_daily_closes(symbol, period * 2 + 5)
            
            if closes is None or len(closes) < period * 2 + 1:
                return None
            
            # Calculate daily percentage returns
            ccr = np.diff(closes) / closes[:-1]
            ccv = np.abs(ccr)
            
            if len(ccv) < period * 2:
                return None
            
            # Recent volatility (last 'period' days)
            mad_recent = np.mean(ccv[-period:])
            
            # Prior volatility (previous 'period' days)
            mad_prior = np.mean(ccv[-period*2:-period])
            
            # V = recent - prior
            V = mad_recent - mad_prior
            
            return float(V)
            
        except Exception as e:
            logger.error(f"Error computing volatility trend for {symbol}: {e}")
            return None

    async def get_market_context(
        self,
        symbol: str,
        G: Optional[float] = None,
        period: int = 21
    ) -> Optional[MarketContext]:
        """
        Get complete market context for a symbol using the Four Axes framework.
        
        Computes P (price trend) and V (volatility trend), and combines with
        G (gamma ratio) if provided or defaults to 0.5 (neutral).
        
        Results are cached with a 5-minute TTL.
        
        Args:
            symbol: Stock symbol
            G: Gamma ratio if already computed (0 to 1), or None to use 0.5
            period: Lookback period for P and V calculations
            
        Returns:
            MarketContext object or None if data unavailable
        """
        try:
            now = datetime.utcnow()
            cache_key = symbol
            
            # Check cache
            if cache_key in self.market_context_cache:
                cached = self.market_context_cache[cache_key]
                age_sec = (now - cached["timestamp"]).total_seconds()
                if age_sec < 300:  # 5-minute TTL
                    # Update G if provided (gamma may be fresher)
                    ctx = cached["context"]
                    if G is not None and G != ctx.G:
                        ctx = MarketContext(
                            symbol=ctx.symbol,
                            P=ctx.P,
                            V=ctx.V,
                            G=G,
                            timestamp=now
                        )
                    return ctx
            
            # Compute P and V
            P = await self.compute_price_trend(symbol, period)
            V = await self.compute_volatility_trend(symbol, period)
            
            if P is None:
                logger.debug(f"Could not compute P for {symbol}")
                return None
            
            if V is None:
                V = 0.0  # Default to neutral if V unavailable
            
            # Use provided G or default to neutral
            G_value = G if G is not None else 0.5
            
            context = MarketContext(
                symbol=symbol,
                P=P,
                V=V,
                G=G_value,
                timestamp=now
            )
            
            # Cache the result
            self.market_context_cache[cache_key] = {
                "timestamp": now,
                "context": context
            }
            
            # Cleanup old cache entries
            if len(self.market_context_cache) > 200:
                cutoff = now - timedelta(minutes=10)
                self.market_context_cache = {
                    k: v for k, v in self.market_context_cache.items()
                    if v["timestamp"] > cutoff
                }
            
            logger.debug(
                f"MarketContext for {symbol}: P={P:.3f}, V={V:.4f}, G={G_value:.3f}, "
                f"regime={context.regime}, mult={context.conviction_multiplier:.2f}"
            )
            
            return context
            
        except Exception as e:
            logger.error(f"Error getting market context for {symbol}: {e}")
            return None

    def clear_context_cache(self, symbol: Optional[str] = None):
        """Clear market context cache for a symbol or all symbols."""
        if symbol:
            self.market_context_cache.pop(symbol, None)
            for key in list(self.daily_closes_cache.keys()):
                if key.startswith(symbol):
                    del self.daily_closes_cache[key]
        else:
            self.market_context_cache.clear()
            self.daily_closes_cache.clear()

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
        Verify options flow matches stock price movement across multiple timeframes.
        Uses caching to prevent redundant API calls for the same symbol in short succession.
        
        Returns:
            Dict with alignment info or None if data unavailable
        """
        try:
            now = datetime.now()
            cache_key = f"{symbol}_pa_{now.strftime('%Y%m%d%H%M')}" # Cache per minute
            
            if cache_key in self.price_action_cache:
                data = self.price_action_cache[cache_key]
            else:
                # Clear old cache entries randomly (simple cleanup)
                if len(self.price_action_cache) > 500:
                    self.price_action_cache = {}
                    
                # Fetch 1-minute bars for the last hour (covers both 5m and 15m needs)
                from_date = now.strftime('%Y-%m-%d') # Intraday
                to_date = from_date
                
                # We need at least 60 minutes of data to calculate 5m and 15m momentum reliably
                # Polygon's range is inclusive
                bars_1m = await self.fetcher.get_aggregates(
                    symbol,
                    timespan='minute',
                    multiplier=1,
                    from_date=from_date,
                    to_date=to_date
                )
                
                if bars_1m.empty or len(bars_1m) < 15:
                    return None
                
                # Resample for 5m and 15m analysis
                # We just need the last few closes and volume
                # Use simple sampling for efficiency since we just want momentum direction
                
                # 5-minute momentum (approx last 5 bars vs 5 bars ago)
                last_price = bars_1m.iloc[-1]['close']
                price_5m_ago = bars_1m.iloc[-min(6, len(bars_1m))]['open']
                momentum_5m = ((last_price - price_5m_ago) / price_5m_ago) * 100
                
                # 15-minute momentum
                price_15m_ago = bars_1m.iloc[-min(16, len(bars_1m))]['open']
                momentum_15m = ((last_price - price_15m_ago) / price_15m_ago) * 100
                
                # Volume analysis (avg of last 30 1m bars)
                recent_bars = bars_1m.tail(30)
                avg_vol_1m = recent_bars['volume'].mean()
                current_vol_1m = bars_1m.iloc[-1]['volume']
                volume_ratio = current_vol_1m / avg_vol_1m if avg_vol_1m > 0 else 1.0
                
                data = {
                    'momentum_5m': momentum_5m,
                    'momentum_15m': momentum_15m,
                    'volume_ratio': volume_ratio
                }
                self.price_action_cache[cache_key] = data

            momentum_5m = data['momentum_5m']
            momentum_15m = data['momentum_15m']
            volume_ratio = data['volume_ratio']

            # Check alignment
            if opt_type == 'CALL':
                aligned_5m = momentum_5m > -0.05 # Allow slight noise
                aligned_15m = momentum_15m > -0.05
                strength = (momentum_5m + momentum_15m) / 2
            else:  # PUT
                aligned_5m = momentum_5m < 0.05
                aligned_15m = momentum_15m < 0.05
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

    async def get_trend_alignment(
        self,
        symbol: str,
        timeframes: Sequence[str] = ("1h", "4h", "1d"),
    ) -> Optional[Dict[str, Dict[str, object]]]:
        """
        Determine bullish/bearish trend state across multiple timeframes using EMA clouds.

        Returns dict mapping timeframe -> {trend, ema values}. Returns None if data unavailable.
        """
        try:
            results: Dict[str, Dict[str, object]] = {}
            for tf in timeframes:
                cache_key = (symbol, tf)
                cached = self.trend_cache.get(cache_key)
                if cached:
                    age_sec = (datetime.utcnow() - cached["timestamp"]).total_seconds()
                    if age_sec < 300:
                        results[tf] = cached["data"]
                        continue

                tf_map = {"1h": ("hour", 1), "4h": ("hour", 4), "1d": ("day", 1)}
                if tf not in tf_map:
                    continue
                timespan, multiplier = tf_map[tf]

                from_date = (datetime.utcnow() - timedelta(days=60)).strftime("%Y-%m-%d")
                bars = await self.fetcher.get_aggregates(
                    symbol,
                    timespan=timespan,
                    multiplier=multiplier,
                    from_date=from_date,
                )

                if bars.empty or len(bars) < 60:
                    return None

                closes = bars["close"].to_numpy(dtype=float)
                ema5 = self._ema(closes, 5)
                ema12 = self._ema(closes, 12)
                ema34 = self._ema(closes, 34)
                ema50 = self._ema(closes, 50)
                close = closes[-1]

                bullish_price = close > ema50[-1]
                bullish_cloud_3450 = ema34[-1] > ema50[-1]
                bullish_cloud_512 = ema5[-1] > ema12[-1]

                bearish_price = close < ema50[-1]
                bearish_cloud_3450 = ema34[-1] < ema50[-1]
                bearish_cloud_512 = ema5[-1] < ema12[-1]

                if bullish_price and bullish_cloud_3450 and bullish_cloud_512:
                    trend = "BULLISH"
                elif bearish_price and bearish_cloud_3450 and bearish_cloud_512:
                    trend = "BEARISH"
                else:
                    trend = "NEUTRAL"

                data = {
                    "trend": trend,
                    "close": close,
                    "ema5": ema5[-1],
                    "ema12": ema12[-1],
                    "ema34": ema34[-1],
                    "ema50": ema50[-1],
                }
                self.trend_cache[cache_key] = {
                    "timestamp": datetime.utcnow(),
                    "data": data,
                }
                results[tf] = data

            return results if results else None
        except Exception as exc:
            logger.error("Error computing trend alignment for %s: %s", symbol, exc)
            return None

    @staticmethod
    def _ema(values: np.ndarray, period: int) -> np.ndarray:
        if len(values) < period:
            return np.full_like(values[-1:], values[-1], dtype=float)
        return pd.Series(values).ewm(span=period, adjust=False).mean().to_numpy()

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
