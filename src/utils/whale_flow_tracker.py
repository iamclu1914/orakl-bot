"""
Stateful analyzer for detecting whale option flow patterns.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Deque, Dict, Optional, Tuple

from .flow_metrics import OptionTradeMetrics


@dataclass
class _FlowEvent:
    ticker: str
    timestamp: datetime
    direction: int  # +1 for calls, -1 for puts
    percent_otm: float
    premium: float


@dataclass
class WhaleFlowSignal:
    """Classification for an analyzed whale flow trade."""

    label: str
    streak: int
    direction: str
    notes: Tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> Dict[str, object]:
        return {
            "label": self.label,
            "streak": self.streak,
            "direction": self.direction,
            "notes": list(self.notes),
        }


class WhaleFlowTracker:
    """
    Maintains rolling history of option trades to detect whale flow patterns.
    """

    def __init__(self, window_seconds: int = 240):
        self.window = timedelta(seconds=window_seconds)
        self._history: Dict[str, Deque[_FlowEvent]] = defaultdict(deque)

    def _purge_stale(self, symbol: str, as_of: datetime) -> None:
        history = self._history[symbol]
        cutoff = as_of - self.window
        while history and history[0].timestamp < cutoff:
            history.popleft()

    @staticmethod
    def _direction(option_type: str) -> int:
        return 1 if option_type == "CALL" else -1

    def _streak(self, history: Deque[_FlowEvent], direction: int) -> int:
        streak = 0
        for event in reversed(history):
            if event.direction == direction:
                streak += 1
            else:
                break
        return streak

    @staticmethod
    def _direction_label(direction: int) -> str:
        return "CALL PRESSURE" if direction == 1 else "PUT PRESSURE"

    def _laddering(self, history: Deque[_FlowEvent], direction: int, current_otm: float) -> bool:
        same_dir = [event.percent_otm for event in history if event.direction == direction]
        if len(same_dir) < 2:
            return False
        recent = same_dir[-2:] + [current_otm]
        return recent[0] < recent[1] < recent[2]

    def _alternating(self, history: Deque[_FlowEvent], direction: int) -> bool:
        if len(history) < 2:
            return False
        last = history[-1].direction
        prev = history[-2].direction if len(history) >= 2 else None
        return prev is not None and last != prev and direction != last

    def _repeat_contract(self, history: Deque[_FlowEvent], ticker: str) -> bool:
        if not history:
            return False
        return history[-1].ticker == ticker

    def process_trade(
        self,
        metrics: OptionTradeMetrics,
        price_change_pct: Optional[float] = None,
    ) -> WhaleFlowSignal:
        """
        Ingest a trade and return the detected flow classification.

        Args:
            metrics: Computed trade metrics.
            price_change_pct: Underlying price change (percentage) over the lookback window.
        """

        symbol = metrics.underlying
        history = self._history[symbol]
        self._purge_stale(symbol, metrics.timestamp)

        direction = self._direction(metrics.option_type)
        streak = self._streak(history, direction) + 1  # include current trade

        notes = []
        label = "FLOW"
        
        # Track if we have a strong prior streak before flip
        prior_streak = self._streak(history, -direction) if history else 0

        # Priority 1: DIVERGENCE (flow vs price) - highest signal
        if price_change_pct is not None:
            if direction == 1 and price_change_pct < -0.1:
                label = "DIVERGENCE"
                notes.append("Bullish flow vs falling spot (divergence)")
            elif direction == -1 and price_change_pct > 0.1:
                label = "DIVERGENCE"
                notes.append("Bearish flow vs rising spot (divergence)")

        # Priority 2: FLIP with strong prior streak - very significant
        if history and history[-1].direction != direction:
            if prior_streak >= 3:
                label = "STRONG_FLIP"
                notes.append(f"Direction flip after {prior_streak} consecutive bursts")
            else:
                label = "FLIP"
                notes.append("Direction reversed")
        
        # Priority 3: LADDER - progressive strikes
        elif self._laddering(history, direction, metrics.percent_otm):
            label = "LADDER"
            notes.append("Progressively further OTM strikes")
        
        # Priority 4: CONTINUATION - sustained pressure
        elif streak >= 4:  # Increased from 3 to 4 for higher conviction
            label = "CONTINUATION"
            # Note: streak count intentionally not displayed in card

        # Priority 5: CHOP - indecision
        if self._alternating(history, direction):
            if label == "FLOW":  # Only apply if no stronger pattern
                label = "CHOP"
            notes.append("Alternating flow detected")

        # Additional context
        if self._repeat_contract(history, metrics.ticker):
            notes.append("Repeated hits on same contract")

        event = _FlowEvent(
            ticker=metrics.ticker,
            timestamp=metrics.timestamp,
            direction=direction,
            percent_otm=metrics.percent_otm,
            premium=metrics.premium,
        )
        history.append(event)

        return WhaleFlowSignal(
            label=label,
            streak=streak,
            direction=self._direction_label(direction),
            notes=tuple(notes),
        )

