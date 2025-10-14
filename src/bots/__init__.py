"""Auto-posting bot modules"""
from .base_bot import BaseAutoBot
from .orakl_flow_bot import TradyFlowBot
from .bullseye_bot import BullseyeBot
from .scalps_bot import ScalpsBot
from .sweeps_bot import SweepsBot
from .golden_sweeps_bot import GoldenSweepsBot
from .darkpool_bot import DarkpoolBot
from .breakouts_bot import BreakoutsBot
from .unusual_volume_bot import UnusualVolumeBot

__all__ = [
    'BaseAutoBot',
    'TradyFlowBot',
    'BullseyeBot',
    'ScalpsBot',
    'SweepsBot',
    'GoldenSweepsBot',
    'DarkpoolBot',
    'BreakoutsBot',
    'UnusualVolumeBot'
]
