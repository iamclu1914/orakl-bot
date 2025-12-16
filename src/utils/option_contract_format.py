"""
Option contract formatting helpers used by Discord alert bots.

Goal: show a human-friendly label (e.g. "TSLA 2026-01-16 500C") while still
preserving the raw Polygon option ticker (e.g. O:TSLA260116C00500000).
"""

from __future__ import annotations

from typing import Optional


def format_option_contract_pretty(
    symbol: str,
    expiration_date: Optional[str],
    strike: Optional[float],
    contract_type: Optional[str],
) -> str:
    """
    Format a nice human-readable contract label.
    """
    sym = (symbol or "").strip().upper() or "UNKNOWN"
    exp = (expiration_date or "").strip()

    cp = (contract_type or "").strip().upper()
    if cp.startswith("C"):
        cp_letter = "C"
    elif cp.startswith("P"):
        cp_letter = "P"
    else:
        cp_letter = "?"

    strike_txt = "?"
    try:
        if strike is not None and float(strike) > 0:
            strike_txt = f"{float(strike):.0f}"
    except Exception:
        strike_txt = "?"

    parts = [sym]
    if exp:
        parts.append(exp)
    parts.append(f"{strike_txt}{cp_letter}")
    return " ".join(parts)


def normalize_option_ticker(raw: Optional[str]) -> str:
    """
    Normalize a Polygon option ticker to include the O: prefix if present.
    """
    if not raw:
        return ""
    if isinstance(raw, dict):
        # Common shapes: {"ticker": "O:TSLA...", ...} or {"contract_ticker": "..."}
        for key in ("contract_ticker", "option_ticker", "ticker", "option_symbol", "contract"):
            val = raw.get(key)
            if isinstance(val, str) and val.strip():
                raw = val
                break
        else:
            return ""

    txt = str(raw).strip()
    if not txt:
        return ""
    return txt if txt.startswith("O:") else f"O:{txt}"


