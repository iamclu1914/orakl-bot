"""
Utilities for decoding Polygon option ticker symbols.

Polygon option tickers follow the format:
    O:{UNDERLYING}{YY}{MM}{DD}{TYPE}{STRIKE}

Example:
    O:SPY251115P00677000  → SPY 2025-11-15 Put 677.00 strike
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import re
from typing import Optional


OPTION_TICKER_REGEX = re.compile(
    r"""
    ^(?:O:)?                # Optional Polygon prefix
    (?P<root>[A-Z.\-]{1,6})  # Underlying root symbol
    (?P<expiry>\d{6})        # Expiration YYMMDD
    (?P<type>[CP])           # Option type
    (?P<strike>\d{8})$       # Strike * 1000 (eight digits)
    """,
    re.VERBOSE,
)


@dataclass(frozen=True)
class OptionTickerComponents:
    """Structured representation of a Polygon option ticker."""

    underlying: str
    expiration: date
    option_type: str
    strike: float

    @classmethod
    def parse(cls, ticker: str) -> "OptionTickerComponents":
        """
        Parse a Polygon option ticker string.

        Args:
            ticker: Ticker string (with or without the leading 'O:' prefix)

        Returns:
            OptionTickerComponents with decoded fields.

        Raises:
            ValueError: If the ticker cannot be parsed.
        """

        if not ticker:
            raise ValueError("Ticker cannot be empty")

        ticker = ticker.strip().upper()
        match = OPTION_TICKER_REGEX.match(ticker)
        if not match:
            raise ValueError(f"Invalid Polygon option ticker format: {ticker}")

        groups = match.groupdict()
        root = groups["root"]
        expiry_raw = groups["expiry"]
        option_type = groups["type"]
        strike_raw = groups["strike"]

        # Convert expiration YYMMDD → YYYY-MM-DD
        year = int(expiry_raw[:2])
        year += 2000 if year < 70 else 1900  # Support far-dated expirations
        month = int(expiry_raw[2:4])
        day = int(expiry_raw[4:6])

        expiration = date(year, month, day)
        strike = int(strike_raw) / 1000.0

        return cls(
            underlying=root.replace("-", "."),
            expiration=expiration,
            option_type="CALL" if option_type == "C" else "PUT",
            strike=strike,
        )


def try_parse_option_ticker(ticker: str) -> Optional[OptionTickerComponents]:
    """
    Gracefully parse a Polygon option ticker.

    Returns the decoded components or None if parsing fails.
    """

    try:
        return OptionTickerComponents.parse(ticker)
    except ValueError:
        return None

