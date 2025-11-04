"""Utility helpers for computing option gamma exposure profiles."""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime
from typing import Dict, Iterable, List, Optional, Tuple


def _detect_contract_type(contract: Dict) -> Optional[str]:
    """Best-effort detection of contract type from snapshot payload."""

    details = contract.get("details") or {}
    ctype = details.get("contract_type")
    if isinstance(ctype, str):
        lowered = ctype.lower()
        if lowered in {"call", "put"}:
            return lowered

    ticker = contract.get("ticker") or ""
    if isinstance(ticker, str):
        if "C" in ticker and "P" not in ticker:
            return "call"
        if "P" in ticker and "C" not in ticker:
            return "put"

    return None


def _safe_number(value, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _parse_expiration(details: Dict) -> Optional[datetime]:
    expiration = details.get("expiration_date")
    if not expiration:
        return None
    try:
        return datetime.fromisoformat(expiration)
    except ValueError:
        return None


def compute_gamma_profile(
    contracts: Iterable[Dict],
    spot_price: float,
    *,
    contract_multiplier: int = 100,
) -> Optional[Dict]:
    """Compute aggregated gamma exposure statistics for an option chain.

    Args:
        contracts: Polygon snapshot contracts for a single underlying.
        spot_price: Latest underlying price (used for dollar gamma computation).
        contract_multiplier: Contract multiplier (defaults to standard equity options).

    Returns:
        Dictionary containing total call/put gamma, net gamma, dominant walls and
        strike-level breakdown; ``None`` when insufficient data is available.
    """

    spot_price = _safe_number(spot_price, default=0.0)
    if spot_price <= 0:
        return None

    call_gamma_by_strike: defaultdict[float, float] = defaultdict(float)
    put_gamma_by_strike: defaultdict[float, float] = defaultdict(float)
    call_oi_by_strike: defaultdict[float, float] = defaultdict(float)
    put_oi_by_strike: defaultdict[float, float] = defaultdict(float)

    total_call_gamma = 0.0
    total_put_gamma = 0.0

    atm_candidate: Optional[Tuple[float, float, datetime]] = None  # (iv, abs_diff, expiry)

    now = datetime.now()

    for contract in contracts:
        contract_type = _detect_contract_type(contract)
        if contract_type not in {"call", "put"}:
            continue

        details = contract.get("details") or {}
        strike = _safe_number(details.get("strike_price"))
        if strike <= 0:
            continue

        open_interest = _safe_number(contract.get("open_interest"))
        if open_interest <= 0:
            continue

        greeks = contract.get("greeks") or {}
        gamma = _safe_number(greeks.get("gamma"))
        if gamma == 0:
            continue

        underlying_asset = contract.get("underlying_asset") or {}
        contract_spot = _safe_number(underlying_asset.get("price"), default=spot_price)

        dollar_gamma = gamma * open_interest * contract_multiplier * (contract_spot ** 2)

        if contract_type == "call":
            call_gamma_by_strike[strike] += dollar_gamma
            call_oi_by_strike[strike] += open_interest
            total_call_gamma += dollar_gamma
        else:
            # Represent put gamma as negative exposure for dealer positioning view
            put_gamma = -dollar_gamma
            put_gamma_by_strike[strike] += put_gamma
            put_oi_by_strike[strike] += open_interest
            total_put_gamma += put_gamma

        # Track near-the-money, short-dated contract for expected move estimation
        iv = _safe_number(contract.get("implied_volatility"))
        expiration_dt = _parse_expiration(details)
        if iv > 0 and expiration_dt and expiration_dt > now:
            days_to_expiry = (expiration_dt - now).days or 1
            moneyness = abs(strike - spot_price)
            candidate_key = (abs(days_to_expiry), moneyness)

            if atm_candidate is None:
                atm_candidate = (iv, moneyness, expiration_dt)
            else:
                best_iv, best_moneyness, best_expiry = atm_candidate
                best_key = (abs((best_expiry - now).days) or 1, best_moneyness)
                if candidate_key < best_key:
                    atm_candidate = (iv, moneyness, expiration_dt)

    if not call_gamma_by_strike and not put_gamma_by_strike:
        return None

    strikes = set(call_gamma_by_strike.keys()) | set(put_gamma_by_strike.keys())
    strike_breakdown: List[Dict[str, float]] = []

    call_wall = None
    put_wall = None

    for strike in sorted(strikes):
        call_gamma = call_gamma_by_strike.get(strike, 0.0)
        put_gamma = put_gamma_by_strike.get(strike, 0.0)
        net_gamma = call_gamma + put_gamma
        strike_breakdown.append(
            {
                "strike": strike,
                "call_gamma": call_gamma,
                "put_gamma": put_gamma,
                "net_gamma": net_gamma,
                "call_oi": call_oi_by_strike.get(strike, 0.0),
                "put_oi": put_oi_by_strike.get(strike, 0.0),
            }
        )

        if call_gamma > 0 and (call_wall is None or call_gamma > call_wall["gamma"]):
            call_wall = {"strike": strike, "gamma": call_gamma, "oi": call_oi_by_strike.get(strike, 0.0)}

        if put_gamma < 0 and (put_wall is None or put_gamma < put_wall["gamma"]):
            put_wall = {"strike": strike, "gamma": put_gamma, "oi": put_oi_by_strike.get(strike, 0.0)}

    net_gamma_total = total_call_gamma + total_put_gamma

    expected_move = None
    expected_move_pct = None
    if atm_candidate is not None:
        atm_iv, _, expiry_dt = atm_candidate
        days = max((expiry_dt - now).days, 1)
        expected_move = spot_price * atm_iv * math.sqrt(1 / 365)
        if expected_move > 0:
            expected_move_pct = expected_move / spot_price

    return {
        "spot_price": spot_price,
        "call_gamma_total": total_call_gamma,
        "put_gamma_total": total_put_gamma,
        "net_gamma_total": net_gamma_total,
        "call_wall": call_wall,
        "put_wall": put_wall,
        "strike_breakdown": strike_breakdown,
        "expected_move": expected_move,
        "expected_move_pct": expected_move_pct,
        "total_call_oi": sum(call_oi_by_strike.values()),
        "total_put_oi": sum(put_oi_by_strike.values()),
        "contract_multiplier": contract_multiplier,
    }


