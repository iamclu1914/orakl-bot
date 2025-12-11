"""
Gamma Ratio (G) Calculation Utilities

G = Γ_call / (Γ_call + |Γ_put|)

Measures whether options market is call-driven or put-driven:
- G → 1.0: Call-driven, upside convexity dominates
- G ≈ 0.5: Balanced/neutral
- G → 0.0: Put-driven, downside convexity dominates
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import numpy as np
from scipy.stats import norm


def bs_delta(
    cp_flag: str,
    S: float,
    K: float,
    T: float,
    r: float = 0.0,
    v: float = 0.20
) -> float:
    """
    Black-Scholes delta with constant volatility.
    
    Args:
        cp_flag: 'C' for call, 'P' for put
        S: Spot price
        K: Strike price
        T: Time to expiration in years
        r: Risk-free rate (default 0)
        v: Constant volatility (default 20%)
    
    Returns:
        Delta value
    """
    if T <= 0:
        # Expired option
        if cp_flag.upper() == 'C':
            return 1.0 if S > K else 0.0
        else:
            return -1.0 if S < K else 0.0
    
    if S <= 0 or K <= 0 or v <= 0:
        return 0.0
    
    d1 = (np.log(S / K) + (r + v * v / 2.0) * T) / (v * np.sqrt(T))
    
    if cp_flag.upper() == 'C':
        return float(norm.cdf(d1))
    else:
        return float(-norm.cdf(-d1))


def percent_gamma(
    cp_flag: str,
    S: float,
    K: float,
    T: float,
    r: float = 0.0,
    v: float = 0.20
) -> float:
    """
    Percent gamma: absolute change in delta for a 1% move in spot.
    
    For calls: delta(S * 1.01) - delta(S)
    For puts: |delta(S * 0.99) - delta(S)|
    
    Args:
        cp_flag: 'C' for call, 'P' for put
        S: Spot price
        K: Strike price
        T: Time to expiration in years
        r: Risk-free rate
        v: Constant volatility
    
    Returns:
        Percent gamma (always positive)
    """
    if T <= 0 or S <= 0 or K <= 0:
        return 0.0
    
    delta_base = bs_delta(cp_flag, S, K, T, r, v)
    
    if cp_flag.upper() == 'C':
        delta_shifted = bs_delta('C', S * 1.01, K, T, r, v)
        return abs(delta_shifted - delta_base)
    else:
        delta_shifted = bs_delta('P', S * 0.99, K, T, r, v)
        return abs(delta_shifted - delta_base)


def filter_options(
    options: List[Dict],
    spot: float,
    min_open_interest: int = 100,
    max_otm_pct: float = 0.20
) -> List[Dict]:
    """
    Filter to liquid, relevant strikes.
    
    Args:
        options: List of option contract dictionaries
        spot: Current underlying price
        min_open_interest: Minimum OI to include (default: 100)
        max_otm_pct: Maximum distance from spot as percentage (default: 20%)
    
    Returns:
        Filtered list of options
    """
    if spot <= 0:
        return []
    
    filtered = []
    
    for opt in options:
        # Skip if OI too low
        oi = opt.get('open_interest', 0)
        if oi is None or oi < min_open_interest:
            continue
        
        # Get strike price
        strike = opt.get('strike')
        if strike is None or strike <= 0:
            continue
        
        # Skip if strike too far OTM
        if abs(strike - spot) / spot > max_otm_pct:
            continue
        
        filtered.append(opt)
    
    return filtered


def _parse_expiration(expiration_value) -> Optional[datetime]:
    """Parse expiration date from various formats."""
    if expiration_value is None:
        return None
    
    if isinstance(expiration_value, datetime):
        return expiration_value
    
    if isinstance(expiration_value, (int, float)):
        # Already in years, convert to datetime
        days = int(expiration_value * 365.25)
        return datetime.now().replace(hour=16, minute=0, second=0, microsecond=0)
    
    if isinstance(expiration_value, str):
        try:
            return datetime.fromisoformat(expiration_value.replace('Z', '+00:00').split('+')[0])
        except ValueError:
            try:
                return datetime.strptime(expiration_value, '%Y-%m-%d')
            except ValueError:
                return None
    
    return None


def _get_time_to_expiry(expiration, now: Optional[datetime] = None) -> float:
    """Get time to expiration in years."""
    if now is None:
        now = datetime.now()
    
    exp_dt = _parse_expiration(expiration)
    if exp_dt is None:
        return 0.0
    
    # If expiration is already a float (years), return it directly
    if isinstance(expiration, (int, float)) and not isinstance(expiration, bool):
        return float(expiration)
    
    # Calculate T in years
    delta = exp_dt - now
    T = delta.total_seconds() / (365.25 * 24 * 3600)
    
    return max(T, 0.0)


def compute_gamma_ratio(
    options_chain: List[Dict],
    spot: float,
    r: float = 0.0,
    v: float = 0.20,
    min_open_interest: int = 100,
    max_otm_pct: float = 0.20
) -> Dict:
    """
    Compute gamma ratio from options chain.
    
    Args:
        options_chain: List of option contracts with structure:
            {
                'type': 'call' | 'put' (or 'contract_type'),
                'strike': float (or 'strike_price'),
                'expiration': datetime or string (or 'expiration_date'),
                'open_interest': int
            }
        spot: Current underlying price
        r: Risk-free rate
        v: Constant volatility assumption
        min_open_interest: Minimum OI filter
        max_otm_pct: Maximum OTM distance filter
    
    Returns:
        {
            'G': float,              # Gamma ratio (0-1)
            'call_gamma': float,     # Total call-side gamma
            'put_gamma': float,      # Total put-side gamma
            'total_gamma': float,    # Sum of both
            'bias': str,             # 'CALL_DRIVEN' | 'PUT_DRIVEN' | 'NEUTRAL'
            'contracts_analyzed': int
        }
    """
    if spot <= 0:
        return {
            'G': 0.5,
            'call_gamma': 0.0,
            'put_gamma': 0.0,
            'total_gamma': 0.0,
            'bias': 'NEUTRAL',
            'contracts_analyzed': 0
        }
    
    # Filter options
    filtered = filter_options(options_chain, spot, min_open_interest, max_otm_pct)
    # #region agent log
    import logging; logging.getLogger(__name__).info(f"[DEBUG_GAMMA] Contract_Filtering | Total={len(options_chain)} | Filtered={len(filtered)} | MinOI={min_open_interest} | MaxOTM={max_otm_pct*100:.0f}% | Spot={spot:.2f}")
    # #endregion
    
    call_gamma = 0.0
    put_gamma = 0.0
    now = datetime.now()
    contracts_analyzed = 0
    
    for opt in filtered:
        # Get contract type - handle various field names
        contract_type = (
            opt.get('type') or 
            opt.get('contract_type') or 
            opt.get('option_type', '')
        )
        if isinstance(contract_type, str):
            contract_type = contract_type.lower()
        else:
            continue
        
        # Get strike - handle various field names
        K = opt.get('strike') or opt.get('strike_price', 0)
        if not K or K <= 0:
            continue
        
        # Get expiration - handle various field names
        expiration = (
            opt.get('expiration') or 
            opt.get('expiration_date') or
            opt.get('exp')
        )
        T = _get_time_to_expiry(expiration, now)
        
        if T <= 0:
            continue  # Skip expired
        
        # Get open interest
        oi = opt.get('open_interest', 0)
        if oi is None or oi <= 0:
            continue
        
        # Calculate percent gamma
        if contract_type in ('call', 'c'):
            pg = percent_gamma('C', spot, K, T, r, v)
            call_gamma += pg * oi
        elif contract_type in ('put', 'p'):
            pg = percent_gamma('P', spot, K, T, r, v)
            put_gamma += pg * oi
        else:
            continue
        
        contracts_analyzed += 1
    
    total_gamma = call_gamma + put_gamma
    
    # Calculate G ratio
    if total_gamma == 0:
        G = 0.5
    else:
        G = call_gamma / total_gamma
    
    # Determine bias based on thresholds
    if G >= 0.65:
        bias = 'CALL_DRIVEN'
    elif G <= 0.35:
        bias = 'PUT_DRIVEN'
    else:
        bias = 'NEUTRAL'
    
    return {
        'G': round(G, 4),
        'call_gamma': round(call_gamma, 2),
        'put_gamma': round(put_gamma, 2),
        'total_gamma': round(total_gamma, 2),
        'bias': bias,
        'contracts_analyzed': contracts_analyzed
    }


def transform_polygon_snapshot(contracts: List[Dict]) -> List[Dict]:
    """
    Transform Polygon options snapshot format to standard format for compute_gamma_ratio.
    
    Polygon snapshot structure:
        {
            'details': {
                'contract_type': 'call' | 'put',
                'strike_price': float,
                'expiration_date': 'YYYY-MM-DD'
            },
            'open_interest': int,
            ...
        }
    
    Args:
        contracts: List of Polygon snapshot contracts
    
    Returns:
        List of standardized option dictionaries
    """
    standardized = []
    
    for contract in contracts:
        details = contract.get('details', {}) or {}
        
        # Extract contract type
        contract_type = details.get('contract_type', '')
        if not contract_type:
            # Try to infer from ticker
            ticker = contract.get('ticker', '')
            if 'C' in str(ticker).upper() and 'P' not in str(ticker).upper():
                contract_type = 'call'
            elif 'P' in str(ticker).upper():
                contract_type = 'put'
            else:
                continue
        
        # Extract other fields
        strike = details.get('strike_price', 0)
        expiration = details.get('expiration_date', '')
        oi = contract.get('open_interest', 0)
        
        if not strike or not expiration:
            continue
        
        standardized.append({
            'type': contract_type.lower(),
            'strike': float(strike),
            'expiration': expiration,
            'open_interest': int(oi) if oi else 0
        })
    
    return standardized


# Alert threshold constants
GAMMA_THRESHOLDS = {
    'extreme_put': 0.25,    # G < 0.25 = extreme put-driven
    'put_driven': 0.35,     # G < 0.35 = put-driven
    'call_driven': 0.65,    # G > 0.65 = call-driven
    'extreme_call': 0.75,   # G > 0.75 = extreme call-driven
}


def classify_gamma_regime(G: float) -> Tuple[str, str]:
    """
    Classify gamma ratio into regime and priority.
    
    Args:
        G: Gamma ratio (0-1)
    
    Returns:
        Tuple of (regime_name, priority)
    """
    if G < GAMMA_THRESHOLDS['extreme_put']:
        return ('EXTREME_PUT', 'high')
    elif G < GAMMA_THRESHOLDS['put_driven']:
        return ('PUT_DRIVEN', 'medium')
    elif G > GAMMA_THRESHOLDS['extreme_call']:
        return ('EXTREME_CALL', 'high')
    elif G > GAMMA_THRESHOLDS['call_driven']:
        return ('CALL_DRIVEN', 'medium')
    else:
        return ('NEUTRAL', 'low')


def get_regime_color(regime: str) -> int:
    """Get Discord embed color for regime."""
    colors = {
        'ULTRA_EXTREME_PUT': 0x8B0000,  # Dark Red
        'EXTREME_PUT': 0xFF0000,         # Red
        'PUT_DRIVEN': 0xFF8C00,          # Orange
        'NEUTRAL': 0x808080,             # Gray
        'CALL_DRIVEN': 0x0066FF,         # Blue
        'EXTREME_CALL': 0x00FF00,        # Green
        'ULTRA_EXTREME_CALL': 0x00FF7F,  # Spring Green (brighter)
    }
    return colors.get(regime, 0x808080)


def get_regime_emoji(regime: str) -> str:
    """Get emoji for regime."""
    emojis = {
        'ULTRA_EXTREME_PUT': '🔴🔴',
        'EXTREME_PUT': '🔴',
        'PUT_DRIVEN': '🟠',
        'NEUTRAL': '⚪',
        'CALL_DRIVEN': '🔵',
        'EXTREME_CALL': '🟢',
        'ULTRA_EXTREME_CALL': '🟢🟢',
    }
    return emojis.get(regime, '⚪')

