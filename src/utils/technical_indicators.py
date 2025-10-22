"""
Technical Indicators for ORAKL Bot
Centralized technical analysis calculations used across multiple bots
"""

from typing import List


class TechnicalIndicators:
    """Collection of technical analysis indicators"""

    @staticmethod
    def calculate_rsi(closes: List[float], period: int = 14) -> float:
        """
        Calculate Relative Strength Index (RSI)

        Args:
            closes: List of closing prices (oldest to newest)
            period: RSI period (default 14)

        Returns:
            RSI value (0-100), or 50.0 if insufficient data
        """
        if len(closes) < period + 1:
            return 50.0  # Neutral if not enough data

        # Calculate price changes
        deltas = [closes[i] - closes[i-1] for i in range(1, len(closes))]

        # Separate gains and losses
        gains = [d if d > 0 else 0 for d in deltas[-period:]]
        losses = [-d if d < 0 else 0 for d in deltas[-period:]]

        # Calculate average gain and loss
        avg_gain = sum(gains) / period
        avg_loss = sum(losses) / period

        if avg_loss == 0:
            return 100.0  # All gains = overbought

        # Calculate RS and RSI
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))

        return rsi

    @staticmethod
    def calculate_sma(values: List[float], period: int) -> float:
        """
        Calculate Simple Moving Average (SMA)

        Args:
            values: List of values
            period: Number of periods for averaging

        Returns:
            SMA value, or last value if insufficient data
        """
        if not values:
            return 0.0

        if len(values) < period:
            return sum(values) / len(values)

        return sum(values[-period:]) / period

    @staticmethod
    def calculate_ema(values: List[float], period: int) -> float:
        """
        Calculate Exponential Moving Average (EMA)

        Args:
            values: List of values (oldest to newest)
            period: Number of periods

        Returns:
            EMA value, or SMA if insufficient data
        """
        if not values:
            return 0.0

        if len(values) < period:
            return TechnicalIndicators.calculate_sma(values, len(values))

        # Calculate initial SMA as starting point
        sma = sum(values[:period]) / period

        # Calculate multiplier
        multiplier = 2 / (period + 1)

        # Calculate EMA
        ema = sma
        for value in values[period:]:
            ema = (value - ema) * multiplier + ema

        return ema
