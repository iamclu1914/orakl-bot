"""
ORAKL Core Module - The "Brain" of the State-Aware Market Engine

This module contains the validation sidecars that run alongside the bots:
- HedgeHunter: Detects synthetic hedging (stock traded against options)
- ContextManager: Maintains live market state (GEX regimes)
"""

from src.core.hedge_hunter import HedgeHunter
from src.core.market_state import ContextManager

__all__ = ['HedgeHunter', 'ContextManager']

