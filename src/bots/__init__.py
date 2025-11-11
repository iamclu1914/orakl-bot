"""Auto-posting bot modules"""
from .base_bot import BaseAutoBot
from .orakl_flow_bot import TradyFlowBot
from .bullseye_bot import BullseyeBot
from .sweeps_bot import SweepsBot
from .golden_sweeps_bot import GoldenSweepsBot
from .index_whale_bot import IndexWhaleBot

__all__ = [
    'BaseAutoBot',
    'TradyFlowBot',
    'BullseyeBot',
    'SweepsBot',
    'GoldenSweepsBot',
    'IndexWhaleBot'
]
