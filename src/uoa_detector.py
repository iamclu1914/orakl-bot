"""
Unusual Options Activity (UOA) Detector

Analyzes trade events from Kafka stream to identify unusual flow patterns.
No watchlist required - reacts to ANY ticker showing anomalous characteristics.

Detection Rules:
1. Volume vs Open Interest: Vol >= 2-3x OI indicates fresh positioning
2. Premium Size: Tiered thresholds ($100K, $250K, $500K+)
3. Trade Size: Single-print size above minimums
4. DTE/OTM Filters: Focus on actionable near-term contracts

Output:
{
    symbol, side, premium, size, dte, strike, otm_pct,
    vol, oi, is_unusual: bool, reasons: [...]
}
"""

import logging
from datetime import datetime
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field

from src.config import Config

logger = logging.getLogger(__name__)


@dataclass
class UOASignal:
    """Represents an unusual options activity detection result"""
    # NOTE: Python 3.13 dataclasses are strict about field ordering:
    # non-default fields may not follow default fields. To make this dataclass
    # order-proof (and avoid startup crashes on deploy), we provide defaults
    # for all fields. Call sites set explicit values anyway.
    symbol: str = ""
    side: str = ""  # 'call' or 'put'
    contract_ticker: str = ""
    expiration_date: str = ""
    premium: float = 0.0
    size: int = 0
    dte: int = 0
    strike: float = 0.0
    otm_pct: float = 0.0
    vol: int = 0
    oi: int = 0
    vol_oi_ratio: float = 0.0
    underlying_price: float = 0.0
    contract_price: float = 0.0
    is_unusual: bool = False
    reasons: List[str] = field(default_factory=list)
    severity: str = 'normal'  # 'normal', 'notable', 'significant', 'whale'
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        return {
            'symbol': self.symbol,
            'side': self.side,
            'contract_ticker': self.contract_ticker,
            'expiration_date': self.expiration_date,
            'premium': self.premium,
            'size': self.size,
            'dte': self.dte,
            'strike': self.strike,
            'otm_pct': self.otm_pct,
            'vol': self.vol,
            'oi': self.oi,
            'vol_oi_ratio': self.vol_oi_ratio,
            'underlying_price': self.underlying_price,
            'contract_price': self.contract_price,
            'is_unusual': self.is_unusual,
            'reasons': self.reasons,
            'severity': self.severity,
            'timestamp': self.timestamp,
        }


class UnusualActivityDetector:
    """
    Detects unusual options activity from enriched trade events.
    
    This detector operates on the Kafka stream without a watchlist,
    analyzing every trade that passes the initial premium filter.
    
    Detection factors:
    - Volume vs Open Interest ratio (fresh positioning)
    - Premium size tiers (institutional vs retail)
    - Trade size (block vs small lot)
    - DTE range (near-term focus)
    - OTM percentage (actionable strikes)
    
    Usage:
        detector = UnusualActivityDetector()
        signal = detector.analyze(enriched_trade)
        if signal.is_unusual:
            # Post to Discord
    """
    
    def __init__(self):
        # Premium thresholds
        self.min_premium = Config.UOA_MIN_PREMIUM
        self.significant_premium = Config.UOA_SIGNIFICANT_PREMIUM
        self.whale_premium = Config.UOA_WHALE_PREMIUM
        
        # Volume/OI thresholds
        self.min_vol_oi = Config.UOA_MIN_VOL_OI_RATIO
        self.high_vol_oi = Config.UOA_HIGH_VOL_OI_RATIO
        self.extreme_vol_oi = Config.UOA_EXTREME_VOL_OI_RATIO
        
        # Volume thresholds
        self.min_volume = Config.UOA_MIN_VOLUME
        self.min_trade_size = Config.UOA_MIN_TRADE_SIZE
        
        # DTE/OTM filters
        self.max_dte = Config.UOA_MAX_DTE
        self.min_otm_pct = Config.UOA_MIN_OTM_PCT
        self.max_otm_pct = Config.UOA_MAX_OTM_PCT
        
        # Minimum reasons to trigger
        self.min_reasons = Config.UOA_MIN_REASONS
        
        # Stats
        self.total_analyzed = 0
        self.total_unusual = 0
        
        logger.info(
            f"UOA Detector initialized: "
            f"min_premium=${self.min_premium:,.0f}, "
            f"min_vol_oi={self.min_vol_oi}x, "
            f"max_dte={self.max_dte}"
        )
    
    def analyze(self, enriched_trade: Dict) -> UOASignal:
        """
        Analyze an enriched trade event for unusual activity.
        
        Args:
            enriched_trade: Trade data enriched with Greeks, OI, Bid/Ask
            
        Returns:
            UOASignal with is_unusual flag and reasons list
        """
        self.total_analyzed += 1
        
        # Extract fields
        symbol = enriched_trade.get('symbol', 'UNKNOWN')
        premium = float(enriched_trade.get('premium', 0))
        side = enriched_trade.get('contract_type', '').lower()
        if side not in ['call', 'put']:
            side = 'call'  # Default
        
        strike = float(enriched_trade.get('strike_price', 0))
        underlying_price = float(enriched_trade.get('underlying_price', 0))
        contract_ticker = str(
            enriched_trade.get('contract_ticker')
            or enriched_trade.get('option_ticker')
            or enriched_trade.get('option_symbol')
            or enriched_trade.get('contract')
            or ""
        )
        expiration_date = str(enriched_trade.get('expiration_date') or "")
        dte = int(enriched_trade.get('dte', 0))
        vol = int(enriched_trade.get('day_volume', 0))
        oi = int(enriched_trade.get('open_interest', 0))
        trade_size = int(enriched_trade.get('trade_size', 0))
        contract_price = float(enriched_trade.get('trade_price', 0))
        
        # Calculate OTM percentage
        if underlying_price > 0 and strike > 0:
            if side == 'call':
                otm_pct = max(0, (strike - underlying_price) / underlying_price)
            else:
                otm_pct = max(0, (underlying_price - strike) / underlying_price)
        else:
            otm_pct = 0
        
        # Calculate Vol/OI ratio
        if oi > 0:
            vol_oi_ratio = vol / oi
        else:
            vol_oi_ratio = float(vol) if vol > 0 else 0  # No OI = potentially new contract
        
        # Initialize signal
        signal = UOASignal(
            symbol=symbol,
            side=side,
            contract_ticker=contract_ticker,
            expiration_date=expiration_date,
            premium=premium,
            size=trade_size,
            dte=dte,
            strike=strike,
            otm_pct=otm_pct,
            vol=vol,
            oi=oi,
            vol_oi_ratio=vol_oi_ratio,
            underlying_price=underlying_price,
            contract_price=contract_price,
            is_unusual=False,
            reasons=[],
            severity='normal'
        )
        
        # Apply filters first (must pass these to be considered)
        if not self._passes_filters(signal):
            return signal
        
        # Check for unusual characteristics
        reasons = []
        
        # 1. Volume vs Open Interest (core UOA signal)
        if vol_oi_ratio >= self.extreme_vol_oi:
            reasons.append(f"EXTREME Vol/OI: {vol_oi_ratio:.1f}x (>={self.extreme_vol_oi}x)")
        elif vol_oi_ratio >= self.high_vol_oi:
            reasons.append(f"HIGH Vol/OI: {vol_oi_ratio:.1f}x (>={self.high_vol_oi}x)")
        elif vol_oi_ratio >= self.min_vol_oi:
            reasons.append(f"Elevated Vol/OI: {vol_oi_ratio:.1f}x (>={self.min_vol_oi}x)")
        
        # 2. Premium size tiers
        if premium >= self.whale_premium:
            reasons.append(f"WHALE Premium: ${premium:,.0f} (>=${self.whale_premium:,.0f})")
            signal.severity = 'whale'
        elif premium >= self.significant_premium:
            reasons.append(f"Significant Premium: ${premium:,.0f} (>=${self.significant_premium:,.0f})")
            signal.severity = 'significant'
        elif premium >= self.min_premium:
            reasons.append(f"Notable Premium: ${premium:,.0f}")
            signal.severity = 'notable'
        
        # 3. Fresh positioning (no prior OI)
        if oi == 0 and vol > self.min_volume:
            reasons.append(f"NEW CONTRACT: Zero OI, {vol:,} volume")
        
        # 4. Large single-print size
        if trade_size >= 500:
            reasons.append(f"BLOCK Trade: {trade_size:,} contracts")
        elif trade_size >= 250:
            reasons.append(f"Large Print: {trade_size:,} contracts")
        
        # 5. Short DTE (higher gamma, more speculative)
        if dte <= 7 and premium >= self.min_premium:
            reasons.append(f"Short DTE: {dte} days (weekly)")
        elif dte == 0:
            reasons.append("0DTE Expiry")
        
        # 6. Far OTM with significant size (lotto-style)
        if otm_pct >= 0.15 and vol_oi_ratio >= self.min_vol_oi:
            reasons.append(f"Far OTM: {otm_pct*100:.1f}% with elevated Vol/OI")
        
        # Determine if unusual (need minimum reasons)
        signal.reasons = reasons
        signal.is_unusual = len(reasons) >= self.min_reasons

        # Anti-spam: "notable" should not fire on premium + short DTE alone.
        # Require at least one *structural* unusual signal for notable tier.
        # (High Vol/OI, big print, or brand-new contract). Significant/whale always allowed.
        if signal.is_unusual and signal.severity == 'notable':
            has_structural = (
                vol_oi_ratio >= self.min_vol_oi
                or trade_size >= 250
                or (oi == 0 and vol > self.min_volume)
            )
            if not has_structural:
                signal.is_unusual = False
        
        if signal.is_unusual:
            self.total_unusual += 1
            logger.info(
                f"UOA DETECTED: {symbol} {side.upper()} ${strike:.0f} "
                f"premium=${premium:,.0f} vol/OI={vol_oi_ratio:.1f}x "
                f"[{len(reasons)} reasons]"
            )
        
        return signal
    
    def _passes_filters(self, signal: UOASignal) -> bool:
        """
        Check if signal passes basic filters before analysis.
        
        Returns False to skip analysis if filters not met.
        """
        # Premium floor
        if signal.premium < self.min_premium:
            return False
        
        # DTE filter
        if signal.dte > self.max_dte:
            return False
        
        # OTM range filter
        if signal.otm_pct < self.min_otm_pct:
            return False
        if signal.otm_pct > self.max_otm_pct:
            return False
        
        # Minimum volume
        if signal.vol < self.min_volume:
            return False
        
        # Minimum trade size
        if signal.size < self.min_trade_size:
            return False
        
        return True
    
    def get_stats(self) -> Dict[str, Any]:
        """Get detector statistics"""
        return {
            'total_analyzed': self.total_analyzed,
            'total_unusual': self.total_unusual,
            'unusual_rate': self.total_unusual / max(1, self.total_analyzed),
            'config': {
                'min_premium': self.min_premium,
                'min_vol_oi': self.min_vol_oi,
                'max_dte': self.max_dte,
                'min_reasons': self.min_reasons,
            }
        }

