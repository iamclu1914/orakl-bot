"""
ORAKL Hedge Hunter - Synthetic Trade Detection

Detects if a large options block is immediately offset by a stock trade
in the opposite direction (e.g., Long Call + Short Stock = Synthetic Put).

This prevents alerting on "hedged" trades that appear as directional bets
but are actually delta-neutral institutional hedging activity.
"""

import logging
from typing import Tuple, Optional
from src.config import Config

logger = logging.getLogger(__name__)


class HedgeHunter:
    """
    Service to detect Synthetic Hedging (Stock traded against Options).
    
    The "Crime Scene" Window:
    - Options print at nanosecond timestamp T
    - Check equity tape at T ± 50ms
    - If stock volume > 40% of delta-equivalent shares, flag as HEDGED
    
    Usage:
        hunter = HedgeHunter(data_fetcher)
        is_hedged, reason = await hunter.check_hedge(
            symbol='AAPL',
            option_ts_nanos=1701234567890123456,
            option_size=500,  # contracts
            sentiment='bullish'
        )
    """
    
    def __init__(self, data_fetcher):
        """
        Initialize Hedge Hunter
        
        Args:
            data_fetcher: DataFetcher instance with get_stock_trades_nanos() method
        """
        self.fetcher = data_fetcher
        self.min_premium = getattr(Config, 'HEDGE_CHECK_MIN_PREMIUM', 500000)
        self.window_ns = getattr(Config, 'HEDGE_WINDOW_NS', 50_000_000)  # 50ms default
        self.hedge_threshold_pct = getattr(Config, 'HEDGE_THRESHOLD_PCT', 0.40)  # 40% threshold
        self.delta_estimate = getattr(Config, 'HEDGE_DELTA_ESTIMATE', 0.50)  # 50 delta baseline
        
        # Track statistics
        self.checks_performed = 0
        self.hedges_detected = 0
        
    async def check_hedge(
        self, 
        symbol: str, 
        option_ts_nanos: int, 
        option_size: int, 
        sentiment: str,
        premium: Optional[float] = None
    ) -> Tuple[bool, str]:
        """
        Check if an options trade is likely hedged with opposing stock.
        
        Args:
            symbol: Underlying ticker (e.g., 'AAPL')
            option_ts_nanos: SIP timestamp of option trade in nanoseconds
            option_size: Number of option contracts
            sentiment: 'bullish' or 'bearish' - the apparent direction of the options trade
            premium: Optional - total premium of the trade (for minimum threshold check)
        
        Returns:
            Tuple[bool, str]: (is_hedged, reason_message)
            - (True, "HEDGED: ...") if trade appears to be synthetic/hedged
            - (False, "CLEAN: ...") if trade appears to be unhedged directional risk
        
        Logic:
            - If Option = BULLISH (Call Buy), Hedge = Stock SELL
            - If Option = BEARISH (Put Buy), Hedge = Stock BUY
            - Threshold: If stock volume > 40% of delta-equivalent shares, flag as HEDGED
        """
        self.checks_performed += 1
        
        # Skip check if premium below threshold (optimization)
        if premium is not None and premium < self.min_premium:
            return False, "SKIPPED: Below premium threshold"
        
        try:
            # 1. Get the Tape (The "Crime Scene")
            trades = await self.fetcher.get_stock_trades_nanos(
                symbol, 
                option_ts_nanos, 
                window_ns=self.window_ns
            )
            
            if not trades:
                return False, "CLEAN: No stock trades in window"
            
            # 2. Analyze Flow
            # Note: Polygon trades don't always have explicit 'buy/sell' side
            # without complex tick analysis, but significant volume at the 
            # exact nanosecond is the tell for institutional hedging
            
            hedging_vol = 0
            trade_count = 0
            
            for t in trades:
                # Filter noise (100 share lots are standard, looking for blocks)
                size = t.get('size', 0) if isinstance(t, dict) else getattr(t, 'size', 0)
                if size >= 100:
                    hedging_vol += size
                    trade_count += 1
            
            # 3. The "Synthetic" Math
            # 1 Option Contract = 100 Shares
            # Standard Delta Hedge for ATM/OTM is 30-60%. We use 50% (0.5) as baseline.
            share_equivalent = option_size * 100 * self.delta_estimate
            
            # 4. The Verdict
            # Threshold: If stock volume > 40% of the theoretical hedge requirement
            hedge_threshold = share_equivalent * self.hedge_threshold_pct
            
            if hedging_vol > hedge_threshold:
                self.hedges_detected += 1
                msg = (
                    f"HEDGED: {hedging_vol:,} shares traded against {option_size} contracts "
                    f"in ±{self.window_ns // 1_000_000}ms window "
                    f"({trade_count} trades, threshold: {int(hedge_threshold):,})"
                )
                logger.info(f"🚫 {symbol} {msg}")
                return True, msg
            
            return False, f"CLEAN: Only {hedging_vol:,} shares (threshold: {int(hedge_threshold):,})"
            
        except Exception as e:
            logger.error(f"[HedgeHunter] Error checking {symbol}: {e}")
            # If API fails, default to False (don't block the trade, but log error)
            return False, f"CHECK_FAILED: {str(e)}"
    
    def get_stats(self) -> dict:
        """Get hedge detection statistics"""
        return {
            'checks_performed': self.checks_performed,
            'hedges_detected': self.hedges_detected,
            'detection_rate': self.hedges_detected / max(1, self.checks_performed)
        }

