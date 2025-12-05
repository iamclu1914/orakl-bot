"""Auto-posting bot modules"""
from .base_bot import BaseAutoBot
from .bullseye_bot import BullseyeBot
from .sweeps_bot import SweepsBot
from .golden_sweeps_bot import GoldenSweepsBot
from .spread_bot import SpreadBot
from .gamma_ratio_bot import GammaRatioBot
from .rolling_thunder_bot import RollingThunderBot
from .walls_bot import WallsBot
from .lotto_bot import LottoBot

__all__ = [
    'BaseAutoBot',
    'BullseyeBot',
    'SweepsBot',
    'GoldenSweepsBot',
    'SpreadBot',
    'GammaRatioBot',
    'RollingThunderBot',
    'WallsBot',
    'LottoBot'
]
