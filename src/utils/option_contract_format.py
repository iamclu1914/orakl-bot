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

def _format_strike_currency(strike: Optional[float]) -> str:
    try:
        if strike is None:
            return "$?"
        val = float(strike)
        if val <= 0:
            return "$?"
        # Prefer clean formatting like $192.5, $670, $92.50
        if abs(val - round(val)) < 1e-9:
            return f"${val:.0f}"
        if abs(val * 10 - round(val * 10)) < 1e-9:
            return f"${val:.1f}"
        return f"${val:.2f}"
    except Exception:
        return "$?"


def format_option_contract_sentence(
    strike: Optional[float],
    contract_type: Optional[str],
    expiration_date: Optional[str],
    dte: Optional[int],
) -> str:
    """
    Sentence-style contract string used in Discord alerts.
    Example: "$192.5 CALL expiring 2025-11-07 (10 days)"
    """
    cp = (contract_type or "").strip().upper()
    if cp.startswith("C"):
        cp_word = "CALL"
    elif cp.startswith("P"):
        cp_word = "PUT"
    else:
        cp_word = "UNKNOWN"

    exp = (expiration_date or "").strip() or "unknown"
    try:
        dte_int = int(dte) if dte is not None else None
    except Exception:
        dte_int = None
    dte_txt = f"{dte_int} days" if dte_int is not None else "n/a"
    return f"{_format_strike_currency(strike)} {cp_word} expiring {exp} ({dte_txt})"


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


