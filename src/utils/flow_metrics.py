"""
Helpers for computing option flow metrics derived from Polygon data.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from .options_parser import OptionTickerComponents, try_parse_option_ticker


@dataclass
class OptionTradeMetrics:
    """Computed metrics for an options trade."""

    ticker: str
    underlying: str
    option_type: str
    strike: float
    expiration: datetime
    timestamp: datetime
    price: float
    size: float
    dte: float
    percent_otm: float
    premium: float
    volume_over_oi: float
    iv_change: Optional[float]
    is_ask_side: bool
    is_single_leg: bool
    multi_leg_ratio: Optional[float] = None

    @property
    def is_otm(self) -> bool:
        return self.percent_otm > 0


def _coerce_timestamp_ns(timestamp_ns: Optional[int]) -> datetime:
    """Convert Polygon nanosecond timestamps into timezone-aware datetimes."""
    if not timestamp_ns:
        return datetime.now(timezone.utc)

    return datetime.fromtimestamp(timestamp_ns / 1_000_000_000, tz=timezone.utc)


def _calculate_dte(expiration: datetime, as_of: datetime) -> float:
    return max((expiration - as_of).total_seconds() / 86400.0, 0.0)


def _percent_otm(
    option_type: str, strike: float, underlying_price: Optional[float]
) -> float:
    if not underlying_price or underlying_price <= 0:
        return 0.0

    if option_type == "CALL":
        return max((strike - underlying_price) / underlying_price, 0.0)

    # Puts are OTM when strike < spot; percent expressed as positive
    return max((underlying_price - strike) / underlying_price, 0.0)


def _volume_over_oi(volume: Optional[float], open_interest: Optional[float]) -> float:
    if volume is None or volume <= 0:
        return 0.0
    if open_interest in (None, 0):
        return float("inf")
    return float(volume) / float(open_interest)


def _is_ask_side(
    trade_price: Optional[float],
    ask_price: Optional[float],
    bid_price: Optional[float] = None,
    midpoint: Optional[float] = None,
) -> bool:
    """
    Determine whether a trade executed at the ask (or higher).

    Falls back to midpoint / bid comparisons when ask quotes are missing (0.0)
    which happens frequently in Polygon snapshots for highly active contracts.
    """
    if trade_price is None:
        return False

    if ask_price is not None and ask_price > 0:
        # Allow small rounding differences
        return trade_price >= ask_price * 0.995

    # Fall back to midpoint if available
    if midpoint is not None and midpoint > 0:
        return trade_price >= midpoint * 1.005

    # Final fallback: require price to exceed bid by a small margin
    if bid_price is not None and bid_price > 0:
        return trade_price >= bid_price * 1.01

    # With no quote context, assume ask-side (better to include than miss)
    return True


def _extract_multi_leg_ratio(data: Dict[str, Any]) -> Optional[float]:
    multi_leg = data.get("multi_leg_ratio")
    if multi_leg is None:
        multi_leg = data.get("multi_leg_count")
    if multi_leg is None:
        return None
    try:
        return float(multi_leg)
    except (TypeError, ValueError):
        return None


def _is_single_leg(multi_leg_ratio: Optional[float]) -> bool:
    if multi_leg_ratio is None:
        return True
    return multi_leg_ratio <= 0.0


def calculate_option_trade_metrics(
    trade: Dict[str, Any],
    contract_snapshot: Dict[str, Any],
    underlying_price: Optional[float],
    previous_iv: Optional[float] = None,
) -> Optional[OptionTradeMetrics]:
    """
    Compute metrics for a single option trade event.

    Args:
        trade: Polygon options trade payload (from websocket or REST).
        contract_snapshot: Snapshot data for the same contract.
        underlying_price: Current underlying stock price.
        previous_iv: Optional IV baseline for delta calculation.

    Returns:
        OptionTradeMetrics or None if data is insufficient.
    """

    ticker = trade.get("ticker") or contract_snapshot.get("ticker")
    if not ticker:
        return None

    components = try_parse_option_ticker(ticker)
    if not components:
        return None

    expiry_str = contract_snapshot.get("details", {}).get("expiration_date")
    if expiry_str:
        try:
            expiration_dt = datetime.fromisoformat(expiry_str)
            if expiration_dt.tzinfo is None:
                expiration_dt = expiration_dt.replace(tzinfo=timezone.utc)
        except ValueError:
            expiration_dt = datetime.combine(
                components.expiration, datetime.min.time()
            ).replace(tzinfo=timezone.utc)
    else:
        expiration_dt = datetime.combine(
            components.expiration, datetime.min.time()
        ).replace(tzinfo=timezone.utc)

    trade_time = _coerce_timestamp_ns(
        trade.get("sip_timestamp") or trade.get("participant_timestamp")
    )

    option_type = components.option_type
    strike = components.strike

    price = trade.get("price")
    if price is None:
        price = trade.get("p")  # Some Polygon payloads use shorthand keys
    size = trade.get("size") or trade.get("s")

    if price is None or size is None:
        return None

    price = float(price)
    size = float(size)
    premium = price * size * 100.0  # Options contract multiplier

    day_data = contract_snapshot.get("day", {}) or {}
    volume = day_data.get("volume") or trade.get("volume")
    open_interest = contract_snapshot.get("open_interest")

    last_quote = contract_snapshot.get("last_quote") or {}
    if not isinstance(last_quote, dict):
        last_quote = {}
    ask_price = last_quote.get("ask")
    if isinstance(ask_price, dict):
        ask_price = ask_price.get("price") or ask_price.get("p") or ask_price.get("midpoint")
    bid_price = last_quote.get("bid")
    if isinstance(bid_price, dict):
        bid_price = bid_price.get("price") or bid_price.get("p") or bid_price.get("midpoint")
    midpoint = last_quote.get("midpoint")

    iv_now = contract_snapshot.get("implied_volatility")
    iv_change = None
    if iv_now is not None and previous_iv is not None:
        iv_change = float(iv_now) - float(previous_iv)

    dte = _calculate_dte(expiration_dt, trade_time)
    multi_leg_ratio = _extract_multi_leg_ratio(trade)

    return OptionTradeMetrics(
        ticker=ticker,
        underlying=components.underlying,
        option_type=option_type,
        strike=strike,
        expiration=expiration_dt,
        timestamp=trade_time,
        price=price,
        size=size,
        dte=dte,
        percent_otm=_percent_otm(option_type, strike, underlying_price),
        premium=premium,
        volume_over_oi=_volume_over_oi(volume, open_interest),
        iv_change=iv_change,
        is_ask_side=_is_ask_side(price, ask_price, bid_price=bid_price, midpoint=midpoint),
        is_single_leg=_is_single_leg(multi_leg_ratio),
        multi_leg_ratio=multi_leg_ratio,
    )


def build_metrics_from_flow(flow: Dict[str, Any]) -> Optional[OptionTradeMetrics]:
    """
    Build OptionTradeMetrics from aggregated flow dictionaries returned by detect_unusual_flow().
    """

    ticker = flow.get("ticker")
    option_type = flow.get("type")
    strike = flow.get("strike")
    expiration_str = flow.get("expiration")
    underlying_price = flow.get("underlying_price")

    if not ticker or not option_type or strike is None or not expiration_str:
        return None

    try:
        strike = float(strike)
    except (TypeError, ValueError):
        return None

    try:
        expiration_dt = datetime.fromisoformat(expiration_str)
        if expiration_dt.tzinfo is None:
            expiration_dt = expiration_dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None

    timestamp = flow.get("timestamp")
    if isinstance(timestamp, datetime):
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
    else:
        timestamp = datetime.now(timezone.utc)

    price = flow.get("last_price") or flow.get("price")
    ask_price = flow.get("ask")
    bid_price = flow.get("bid")
    midpoint = flow.get("midpoint")
    total_volume = flow.get("total_volume")
    open_interest = flow.get("open_interest")
    volume_delta = flow.get("volume_delta")
    premium = flow.get("premium")

    try:
        price = float(price)
    except (TypeError, ValueError):
        return None

    try:
        size = float(volume_delta) if volume_delta is not None else 0.0
    except (TypeError, ValueError):
        size = 0.0

    if premium is None:
        premium = price * size * 100.0

    percent_otm = _percent_otm(option_type, strike, underlying_price)
    dte = _calculate_dte(expiration_dt, timestamp)
    multi_leg_ratio = _extract_multi_leg_ratio(flow)

    return OptionTradeMetrics(
        ticker=ticker,
        underlying=flow.get("underlying", ""),
        option_type=option_type,
        strike=strike,
        expiration=expiration_dt,
        timestamp=timestamp,
        price=price,
        size=size,
        dte=dte,
        percent_otm=percent_otm,
        premium=float(premium),
        volume_over_oi=_volume_over_oi(total_volume, open_interest),
        iv_change=None,
        is_ask_side=_is_ask_side(price, ask_price, bid_price=bid_price, midpoint=midpoint),
        is_single_leg=_is_single_leg(multi_leg_ratio),
        multi_leg_ratio=multi_leg_ratio,
    )

