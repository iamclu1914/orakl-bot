"""
ORAKL Bot Configuration Module
Handles environment variables and configuration validation
"""

import os
from pathlib import Path
from dotenv import load_dotenv
import logging

logger = logging.getLogger(__name__)

# Load environment variables
env_path = Path(__file__).parent.parent / '.env'
if not env_path.exists():
    # Try the env.example file if .env doesn't exist
    env_path = Path(__file__).parent.parent / 'env.example'
    
load_dotenv(env_path)

class Config:
    """Central configuration for ORAKL Bot with validation"""
    
    # Bot Info
    BOT_NAME = os.getenv('BOT_NAME', 'ORAKL')
    
    # API Keys - Using provided credentials
    POLYGON_API_KEY = os.getenv('POLYGON_API_KEY')
    DISCORD_BOT_TOKEN = os.getenv('DISCORD_BOT_TOKEN', '')
    DISCORD_WEBHOOK_URL = os.getenv('DISCORD_WEBHOOK_URL')
    
    # Individual Bot Webhooks (Each bot posts to its own dedicated channel)
    SWEEPS_WEBHOOK = os.getenv(
        'SWEEPS_WEBHOOK',
        'https://discord.com/api/webhooks/1427361658761777287/vloziMHuypGrjwv8vxd72ySfzTblc9Nf1OHkkKAkUI81IqNPRym0FgjPDQGzYfwiNyC8'
    )
    GOLDEN_SWEEPS_WEBHOOK = os.getenv(
        'GOLDEN_SWEEPS_WEBHOOK',
        'https://discord.com/api/webhooks/1427361801443741788/hXDZQd4hce8-Ph_GKKxFGTzE8EHzSZP0S-xTjxa5lXAc2LoqofGebkk924PbKKXw4FBN'
    )
    BULLSEYE_WEBHOOK = os.getenv(
        'BULLSEYE_WEBHOOK',
        'https://discord.com/api/webhooks/1427362052753850549/NJBVniyzWQHrc_M6mZ2_19fQjNn_iVEpaMNDjhbYsGuqP6dlElDU58QH-MgfpJ7UE6ip'
    )
    SPREAD_WEBHOOK = os.getenv(
        'SPREAD_WEBHOOK',
        'https://discord.com/api/webhooks/1437936756644122624/CPQjKuRYQsW6wzU1MtuEJx5QrKGaPhU3anZH886MGNLv-DtsLhu3PKSv_YTRIGckkIGV'
    )
    INDEX_WHALE_WEBHOOK = os.getenv('INDEX_WHALE_WEBHOOK', DISCORD_WEBHOOK_URL)
    GAMMA_RATIO_WEBHOOK = os.getenv(
        'GAMMA_RATIO_WEBHOOK',
        'https://discord.com/api/webhooks/1445287562066526269/HZxWUHNlM8lbl1_02qOlnYxCfZ4vXvzb5ixMLUeMmA3x2Cq-QO2Y3_iv5db3skqCi923'
    )
    
    # Discord Settings
    DISCORD_COMMAND_PREFIX = os.getenv('DISCORD_COMMAND_PREFIX', 'ok-')
    DISCORD_CHANNEL_ID = int(os.getenv('DISCORD_CHANNEL_ID', '1427156934582079588'))
    ALERT_CHANNEL_ID = int(os.getenv('ALERT_CHANNEL_ID', '1427156934582079588'))
    
    # Bot Scan Intervals (seconds) - All aligned to 5 minutes for shared FlowCache efficiency
    # The FlowCache prefetches data once per 5-minute cycle, shared by all bots
    BULLSEYE_INTERVAL = int(os.getenv('BULLSEYE_INTERVAL', '600'))  # 10 minutes - full scan
    SWEEPS_INTERVAL = int(os.getenv('SWEEPS_INTERVAL', '600'))  # 10 minutes - full scan
    GOLDEN_SWEEPS_INTERVAL = int(os.getenv('GOLDEN_SWEEPS_INTERVAL', '600'))  # 10 minutes - full scan
    INDEX_WHALE_INTERVAL = int(os.getenv('INDEX_WHALE_INTERVAL', '300'))  # 5 minutes (aligned with FlowCache)
    SPREAD_INTERVAL = int(os.getenv('SPREAD_INTERVAL', '600'))  # 10 minutes - full scan
    GAMMA_RATIO_INTERVAL = int(os.getenv('GAMMA_RATIO_INTERVAL', '300'))  # 5 minutes
    
    # Batch sizes for scan workload management (prevents timeouts)
    SPREAD_SCAN_BATCH_SIZE = int(os.getenv('SPREAD_SCAN_BATCH_SIZE', '100'))
    
    # Index Whale Bot Thresholds (for intraday 1-3 DTE reversals)
    INDEX_WHALE_MIN_PREMIUM = float(os.getenv('INDEX_WHALE_MIN_PREMIUM', '30000'))  # Allow smaller intraday sweeps
    INDEX_WHALE_MIN_VOLUME_DELTA = int(os.getenv('INDEX_WHALE_MIN_VOLUME_DELTA', '20'))  # Slightly smaller prints
    INDEX_WHALE_MAX_PERCENT_OTM = float(os.getenv('INDEX_WHALE_MAX_PERCENT_OTM', '0.06'))  # Allow up to 6% OTM
    INDEX_WHALE_MIN_DTE = float(os.getenv('INDEX_WHALE_MIN_DTE', '0.0'))  # Allow same-day contracts
    INDEX_WHALE_MAX_DTE = float(os.getenv('INDEX_WHALE_MAX_DTE', '4.0'))  # 4 day maximum for intraday plays
    INDEX_WHALE_MAX_MULTI_LEG_RATIO = float(os.getenv('INDEX_WHALE_MAX_MULTI_LEG_RATIO', '0.20'))  # Allow small multi-leg (complex hedges)
    INDEX_WHALE_MIN_SCORE = int(os.getenv('INDEX_WHALE_MIN_SCORE', '85'))
    
    # ORAKL Flow Settings
    SCAN_INTERVAL_MINUTES = int(os.getenv('SCAN_INTERVAL_MINUTES', '5'))
    MIN_PREMIUM = float(os.getenv('MIN_PREMIUM', '10000'))
    MIN_VOLUME = int(os.getenv('MIN_VOLUME', '100'))
    UNUSUAL_VOLUME_MULTIPLIER = float(os.getenv('UNUSUAL_VOLUME_MULTIPLIER', '3'))
    REPEAT_SIGNAL_THRESHOLD = int(os.getenv('REPEAT_SIGNAL_THRESHOLD', '3'))
    SUCCESS_RATE_THRESHOLD = float(os.getenv('SUCCESS_RATE_THRESHOLD', '0.80'))
    
    # Bot-specific Thresholds - OPTIMIZED FOR QUALITY (BALANCED PRESET)
    GOLDEN_MIN_PREMIUM = float(os.getenv('GOLDEN_MIN_PREMIUM', '1000000'))  # Keep Golden high ($1M+)
    SWEEPS_MIN_PREMIUM = float(os.getenv('SWEEPS_MIN_PREMIUM', '250000'))   # Lowered to $250k (Industry Std)
    SWEEPS_MIN_VOLUME_RATIO = float(os.getenv('SWEEPS_MIN_VOLUME_RATIO', '1.25'))  # 1.25x (Balanced)
    SWEEPS_MIN_ALIGNMENT_CONFIDENCE = int(os.getenv('SWEEPS_MIN_ALIGNMENT_CONFIDENCE', '20'))
    SWEEPS_MAX_STRIKE_DISTANCE = float(os.getenv('SWEEPS_MAX_STRIKE_DISTANCE', '0.06'))  # 6% max OTM (new)
    SWEEPS_COOLDOWN_SECONDS = int(os.getenv('SWEEPS_COOLDOWN_SECONDS', '1800'))  # 30 min cooldown (new)
    SWEEPS_MAX_ALERTS_PER_SCAN = int(os.getenv('SWEEPS_MAX_ALERTS_PER_SCAN', '2'))  # Max 2 per scan (new)
    GOLDEN_SWEEPS_MIN_VOLUME_RATIO = float(os.getenv('GOLDEN_SWEEPS_MIN_VOLUME_RATIO', '1.1'))
    GOLDEN_SWEEPS_MIN_ALIGNMENT_CONFIDENCE = int(os.getenv('GOLDEN_SWEEPS_MIN_ALIGNMENT_CONFIDENCE', '15'))
    GOLDEN_MAX_STRIKE_DISTANCE = float(os.getenv('GOLDEN_MAX_STRIKE_DISTANCE', '100.0'))  # percent OTM/ITM allowed for golden sweeps (100 = any strike)
    MIN_VOLUME_RATIO = float(os.getenv('MIN_VOLUME_RATIO', '3.0'))  # 3x volume for unusual
    MIN_ABSOLUTE_VOLUME = int(os.getenv('MIN_ABSOLUTE_VOLUME', '1000000'))  # 1M shares minimum
    
    # Bullseye Bot Thresholds (institutional swing trades - OPTIMIZED FOR QUALITY)
    BULLSEYE_MIN_PREMIUM = float(os.getenv('BULLSEYE_MIN_PREMIUM', '500000'))  # Lowered to $500k to surface more blocks
    BULLSEYE_MIN_VOLUME = int(os.getenv('BULLSEYE_MIN_VOLUME', '2000'))  # Day volume floor for liquidity
    BULLSEYE_MIN_DTE = float(os.getenv('BULLSEYE_MIN_DTE', '1.0'))
    BULLSEYE_MAX_DTE = float(os.getenv('BULLSEYE_MAX_DTE', '30.0'))  # 30 days max (tightened)
    BULLSEYE_MIN_VOLUME_DELTA = int(os.getenv('BULLSEYE_MIN_VOLUME_DELTA', '600'))  # 600+ contracts (raised)
    BULLSEYE_MIN_BLOCK_CONTRACTS = int(os.getenv('BULLSEYE_MIN_BLOCK_CONTRACTS', '400'))  # 400+ block size
    BULLSEYE_MIN_VOI_RATIO = float(os.getenv('BULLSEYE_MIN_VOI_RATIO', '1.0'))  # Fresh positioning
    BULLSEYE_MIN_OPEN_INTEREST = int(os.getenv('BULLSEYE_MIN_OPEN_INTEREST', '500'))
    BULLSEYE_MIN_PRICE = float(os.getenv('BULLSEYE_MIN_PRICE', '0.25'))
    BULLSEYE_MIN_ITM_PROBABILITY = float(os.getenv('BULLSEYE_MIN_ITM_PROBABILITY', '0.35'))  # 35% minimum
    BULLSEYE_DELTA_MIN = float(os.getenv('BULLSEYE_DELTA_MIN', '0.35'))  # ATM range
    BULLSEYE_DELTA_MAX = float(os.getenv('BULLSEYE_DELTA_MAX', '0.65'))
    BULLSEYE_MAX_STRIKE_DISTANCE = float(os.getenv('BULLSEYE_MAX_STRIKE_DISTANCE', '0.12'))  # 12% max OTM (tightened)
    BULLSEYE_MAX_SPREAD_PCT = float(os.getenv('BULLSEYE_MAX_SPREAD_PCT', '8.0'))  # 8% max bid-ask spread
    BULLSEYE_COOLDOWN_SECONDS = int(os.getenv('BULLSEYE_COOLDOWN_SECONDS', '2700'))  # 45 minutes (raised)
    BULLSEYE_MAX_ALERTS_PER_SCAN = int(os.getenv('BULLSEYE_MAX_ALERTS_PER_SCAN', '2'))  # Max 2 per scan (quality)
    BULLSEYE_MIN_SWEEP_SCORE = int(os.getenv('BULLSEYE_MIN_SWEEP_SCORE', '90'))  # Score 90+ (raised)
    # 99 Cent Store Bot Thresholds (sub-$1 swing trades)
    # Defaults tuned to actually fire during normal sessions; env vars can tighten for "ultra quality".
    SPREAD_MIN_PREMIUM = float(os.getenv('SPREAD_MIN_PREMIUM', '100000'))  # Lowered to $100K to increase 99c hits
    SPREAD_MIN_VOLUME = int(os.getenv('SPREAD_MIN_VOLUME', '500'))  # Lower default to avoid starving alerts
    SPREAD_MIN_VOLUME_DELTA = int(os.getenv('SPREAD_MIN_VOLUME_DELTA', '250'))
    SPREAD_MAX_PRICE = float(os.getenv('SPREAD_MAX_PRICE', '1.00'))  # Hard cap: sub-$1.00 contracts only
    SPREAD_MIN_PRICE = float(os.getenv('SPREAD_MIN_PRICE', '0.05'))  # Avoid illiquid penny options
    SPREAD_MIN_VOI_RATIO = float(os.getenv('SPREAD_MIN_VOI_RATIO', '2.0'))  # 2.0x VOI (still "fresh")
    SPREAD_MIN_DTE = float(os.getenv('SPREAD_MIN_DTE', '2.0'))  # 2 days minimum for swing trades
    SPREAD_MAX_DTE = float(os.getenv('SPREAD_MAX_DTE', '30.0'))  # Up to 4 weeks for swing trades
    SPREAD_MAX_PERCENT_OTM = float(os.getenv('SPREAD_MAX_PERCENT_OTM', '0.12'))  # Slightly wider net
    SPREAD_COOLDOWN_SECONDS = int(os.getenv('SPREAD_COOLDOWN_SECONDS', '1800'))  # 30 min cooldown (new)
    SPREAD_MAX_ALERTS_PER_SCAN = int(os.getenv('SPREAD_MAX_ALERTS_PER_SCAN', '2'))  # Max 2 per scan (new)

    # Gamma Ratio Bot Thresholds (G = call_gamma / total_gamma)
    # G → 1.0 = call-driven, G → 0.0 = put-driven, G ≈ 0.5 = balanced
    GAMMA_RATIO_CONSTANT_VOL = float(os.getenv('GAMMA_RATIO_CONSTANT_VOL', '0.20'))  # BSM volatility assumption
    GAMMA_RATIO_RISK_FREE_RATE = float(os.getenv('GAMMA_RATIO_RISK_FREE_RATE', '0.0'))
    GAMMA_RATIO_MIN_OI = int(os.getenv('GAMMA_RATIO_MIN_OI', '100'))  # Minimum OI to include
    GAMMA_RATIO_MAX_OTM_PCT = float(os.getenv('GAMMA_RATIO_MAX_OTM_PCT', '0.20'))  # Max distance from spot
    # Min gamma to filter illiquid names. Lowered default so Gamma Ratio Bot doesn't filter everything on quiet days.
    GAMMA_RATIO_MIN_TOTAL_GAMMA = float(os.getenv('GAMMA_RATIO_MIN_TOTAL_GAMMA', '1000'))
    GAMMA_RATIO_MAX_CONTRACTS = int(os.getenv('GAMMA_RATIO_MAX_CONTRACTS', '300'))  # Max contracts to fetch
    GAMMA_RATIO_EXPIRY_DAYS = int(os.getenv('GAMMA_RATIO_EXPIRY_DAYS', '30'))  # Only near-term contracts
    GAMMA_RATIO_EXTREME_PUT = float(os.getenv('GAMMA_RATIO_EXTREME_PUT', '0.25'))  # G < 0.25 = extreme put
    GAMMA_RATIO_PUT_DRIVEN = float(os.getenv('GAMMA_RATIO_PUT_DRIVEN', '0.35'))  # G < 0.35 = put-driven (not used anymore)
    GAMMA_RATIO_CALL_DRIVEN = float(os.getenv('GAMMA_RATIO_CALL_DRIVEN', '0.65'))  # G > 0.65 = call-driven (not used anymore)
    GAMMA_RATIO_EXTREME_CALL = float(os.getenv('GAMMA_RATIO_EXTREME_CALL', '0.75'))  # G > 0.75 = extreme call
    GAMMA_RATIO_COOLDOWN_MINUTES = int(os.getenv('GAMMA_RATIO_COOLDOWN_MINUTES', '30'))  # Cooldown between alerts

    # Score Thresholds - OPTIMIZED FOR QUALITY
    MIN_GOLDEN_SCORE = int(os.getenv('MIN_GOLDEN_SCORE', '85'))
    MIN_SWEEP_SCORE = int(os.getenv('MIN_SWEEP_SCORE', '85'))
    MIN_BULLSEYE_SCORE = int(os.getenv('MIN_BULLSEYE_SCORE', '90'))  # 90+ for highest conviction only
    
    # Watchlist Mode - Dynamic or Static
    # Default to STATIC with a small, liquid set to ensure scans finish
    WATCHLIST_MODE = os.getenv('WATCHLIST_MODE', 'STATIC')  # ALL_MARKET or STATIC
    WATCHLIST_REFRESH_INTERVAL = int(os.getenv('WATCHLIST_REFRESH_INTERVAL', '86400'))  # 24 hours in seconds

    # Minimum liquidity filters for ALL_MARKET mode
    MIN_MARKET_CAP = float(os.getenv('MIN_MARKET_CAP', '500000000'))  # $500M minimum
    MIN_DAILY_VOLUME = int(os.getenv('MIN_DAILY_VOLUME', '500000'))  # 500K shares minimum
    MIN_STOCK_PRICE = float(os.getenv('MIN_STOCK_PRICE', '5.0'))  # $5 minimum (avoid penny stocks)
    MAX_STOCK_PRICE = float(os.getenv('MAX_STOCK_PRICE', '10000'))  # $10K max (filter out Berkshire)

    # =============================================================================
    # Watchlist Tiers
    # =============================================================================
    
    # Tier 1: Core liquid universe (19 symbols) - indices, mega-caps, sector ETFs
    _TIER1_UNIVERSE = (
        'SPY,QQQ,DIA,IWM,TSLA,AAPL,MSFT,NVDA,AMD,AVGO,GOOGL,META,AMZN,SMH,'
        'XLF,XLE,XLK,XLV,XLY'
    )
    
    # Tier 2: High-value expansion names (30 symbols) - institutionals, growth, beta, high-activity
    _TIER2_UNIVERSE = (
        'NFLX,CRM,COIN,JPM,WMT,SMCI,MRVL,MU,UBER,GLD,PLTR,TSM,BABA,ORCL,COST,'
        'VALE,CVNA,HOOD,IBIT,PYPL,COHR,CRDO,INTC,LIN,MSTR,NOW,AXON,NVO,WDAY,FDX'
    )
    
    # Parse into lists
    _TIER1_LIST = [t.strip().upper() for t in _TIER1_UNIVERSE.split(',') if t.strip()]
    _TIER2_LIST = [t.strip().upper() for t in _TIER2_UNIVERSE.split(',') if t.strip()]
    
    # Legacy aliases
    _UNIFIED_WATCHLIST = _TIER1_UNIVERSE
    _DEFAULT_WATCHLIST = _TIER1_UNIVERSE
    _UNIFIED_LIST = _TIER1_LIST

    STATIC_WATCHLIST = os.getenv('WATCHLIST', _TIER1_UNIVERSE).split(',')

    # =============================================================================
    # Bot-Specific Watchlists (Tier 1 + selective Tier 2 additions)
    # =============================================================================
    
    # Sweeps Bot: Tier 1 + growth/beta names (46 total)
    # Add: NFLX, CRM, COIN, SMCI, MRVL, MU, UBER, PLTR, TSM, BABA, ORCL, COST + high-activity names
    _SWEEPS_TIER2 = [
        'NFLX', 'CRM', 'COIN', 'SMCI', 'MRVL', 'MU', 'UBER', 'PLTR', 'TSM', 'BABA', 'ORCL', 'COST',
        'VALE', 'CVNA', 'HOOD', 'IBIT', 'PYPL', 'COHR', 'CRDO', 'INTC', 'LIN', 'MSTR', 'NOW', 'AXON', 'NVO', 'WDAY', 'FDX'
    ]
    _SWEEPS_DEFAULT = _TIER1_LIST + _SWEEPS_TIER2
    SWEEPS_WATCHLIST = os.getenv(
        'SWEEPS_WATCHLIST',
        ','.join(_SWEEPS_DEFAULT)
    ).split(',')

    # Golden Sweeps Bot: Tier 1 + big-whale magnets (44 total)
    # Add: NFLX, COIN, JPM, WMT, GLD, PLTR, TSM, BABA, ORCL, COST + high-activity names
    _GOLDEN_TIER2 = [
        'NFLX', 'COIN', 'JPM', 'WMT', 'GLD', 'PLTR', 'TSM', 'BABA', 'ORCL', 'COST',
        'VALE', 'CVNA', 'HOOD', 'IBIT', 'PYPL', 'COHR', 'CRDO', 'INTC', 'LIN', 'MSTR', 'NOW', 'AXON', 'NVO', 'WDAY', 'FDX'
    ]
    _GOLDEN_DEFAULT = _TIER1_LIST + _GOLDEN_TIER2
    GOLDEN_SWEEPS_WATCHLIST = os.getenv(
        'GOLDEN_SWEEPS_WATCHLIST',
        ','.join(_GOLDEN_DEFAULT)
    ).split(',')
    
    # Bullseye Bot: Tier 1 + institutionals (43 total)
    # Add: NFLX, JPM, WMT, GLD, PLTR, TSM, BABA, ORCL, COST + high-activity names
    _BULLSEYE_TIER2 = [
        'NFLX', 'JPM', 'WMT', 'GLD', 'PLTR', 'TSM', 'BABA', 'ORCL', 'COST',
        'VALE', 'CVNA', 'HOOD', 'IBIT', 'PYPL', 'COHR', 'CRDO', 'INTC', 'LIN', 'MSTR', 'NOW', 'AXON', 'NVO', 'WDAY', 'FDX'
    ]
    _BULLSEYE_DEFAULT = _TIER1_LIST + _BULLSEYE_TIER2
    BULLSEYE_WATCHLIST = os.getenv(
        'BULLSEYE_WATCHLIST',
        ','.join(_BULLSEYE_DEFAULT)
    ).split(',')
    
    # Rolling Thunder Bot: Tier 1 + roll-prone names (43 total)
    # Add: NFLX, COIN, WMT, SMCI, PLTR, TSM, BABA, ORCL, COST + high-activity names
    _ROLLING_TIER2 = [
        'NFLX', 'COIN', 'WMT', 'SMCI', 'PLTR', 'TSM', 'BABA', 'ORCL', 'COST',
        'VALE', 'CVNA', 'HOOD', 'IBIT', 'PYPL', 'COHR', 'CRDO', 'INTC', 'LIN', 'MSTR', 'NOW', 'AXON', 'NVO', 'WDAY', 'FDX'
    ]
    _ROLLING_DEFAULT = _TIER1_LIST + _ROLLING_TIER2
    ROLLING_WATCHLIST = os.getenv(
        'ROLLING_WATCHLIST',
        ','.join(_ROLLING_DEFAULT)
    ).split(',')
    
    # Lotto Bot: Tier 1 + story/beta names (45 total)
    # Add: NFLX, COIN, UBER, SMCI, MRVL, MU, PLTR, TSM, BABA, ORCL, COST + high-activity names
    _LOTTO_TIER2 = [
        'NFLX', 'COIN', 'UBER', 'SMCI', 'MRVL', 'MU', 'PLTR', 'TSM', 'BABA', 'ORCL', 'COST',
        'VALE', 'CVNA', 'HOOD', 'IBIT', 'PYPL', 'COHR', 'CRDO', 'INTC', 'LIN', 'MSTR', 'NOW', 'AXON', 'NVO', 'WDAY', 'FDX'
    ]
    _LOTTO_DEFAULT = _TIER1_LIST + _LOTTO_TIER2
    LOTTO_WATCHLIST = os.getenv(
        'LOTTO_WATCHLIST',
        ','.join(_LOTTO_DEFAULT)
    ).split(',')
    
    INDEX_WHALE_WATCHLIST = os.getenv(
        'INDEX_WHALE_WATCHLIST',
        'SPY,QQQ,IWM'
    ).split(',')
    
    # 99 Cent Store: expand to Tier1 + Tier2 by default for wider coverage
    SPREAD_WATCHLIST = os.getenv(
        'SPREAD_WATCHLIST',
        ','.join(_TIER1_LIST + _TIER2_LIST)
    ).split(',')
    SPREAD_EXTRA_TICKERS = os.getenv(
        'SPREAD_EXTRA_TICKERS',
        ''
    ).split(',')
    # Gamma Bot default: Focus on very small, liquid set to finish scans
    _GAMMA_DEFAULT = 'SPY,QQQ,DIA,TSLA,AAPL'
    GAMMA_RATIO_WATCHLIST = os.getenv(
        'GAMMA_RATIO_WATCHLIST',
        _GAMMA_DEFAULT
    ).split(',')

    SKIP_TICKERS = os.getenv(
        'SKIP_TICKERS',
        'ABC,ATVI,BRK-A,BRK-B,SPX,DFS'
    ).split(',')

    # =============================================================================
    # Index / cash-settled underlyings (SPX/VIX/NDX/etc) — block posting across ALL bots
    # =============================================================================
    BLOCK_INDEX_SYMBOLS = os.getenv('BLOCK_INDEX_SYMBOLS', 'true').lower() == 'true'
    INDEX_SYMBOLS_BLOCKLIST = os.getenv(
        'INDEX_SYMBOLS_BLOCKLIST',
        # Common index roots + weeklies/families we see in options flow
        'SPX,SPXW,VIX,VIXW,NDX,NDXW,NDXP,NQX,RUT,RUTW,DJX,DJXW,XSP,OEX'
    ).split(',')

    # Initialize WATCHLIST (will be populated dynamically by WatchlistManager)
    # Normalize all watchlists to uppercase
    WATCHLIST = [ticker.strip().upper() for ticker in STATIC_WATCHLIST if ticker.strip()]
    SWEEPS_WATCHLIST = [ticker.strip().upper() for ticker in SWEEPS_WATCHLIST if ticker.strip()]
    GOLDEN_SWEEPS_WATCHLIST = [ticker.strip().upper() for ticker in GOLDEN_SWEEPS_WATCHLIST if ticker.strip()]
    BULLSEYE_WATCHLIST = [ticker.strip().upper() for ticker in BULLSEYE_WATCHLIST if ticker.strip()]
    ROLLING_WATCHLIST = [ticker.strip().upper() for ticker in ROLLING_WATCHLIST if ticker.strip()]
    LOTTO_WATCHLIST = [ticker.strip().upper() for ticker in LOTTO_WATCHLIST if ticker.strip()]
    INDEX_WHALE_WATCHLIST = [ticker.strip().upper() for ticker in INDEX_WHALE_WATCHLIST if ticker.strip()]
    SPREAD_WATCHLIST = [ticker.strip().upper() for ticker in SPREAD_WATCHLIST if ticker.strip()]
    SPREAD_EXTRA_TICKERS = [ticker.strip().upper() for ticker in SPREAD_EXTRA_TICKERS if ticker.strip()]
    GAMMA_RATIO_WATCHLIST = [ticker.strip().upper() for ticker in GAMMA_RATIO_WATCHLIST if ticker.strip()]
    
    # Log watchlist configuration
    logger.info(f"Watchlist Tiers: Tier1={len(_TIER1_LIST)}, Tier2={len(_TIER2_LIST)}")
    logger.info(f"Bot Watchlists:")
    logger.info(f"  - Sweeps: {len(SWEEPS_WATCHLIST)} tickers (Tier1 + growth/beta)")
    logger.info(f"  - Golden Sweeps: {len(GOLDEN_SWEEPS_WATCHLIST)} tickers (Tier1 + whale magnets)")
    logger.info(f"  - Bullseye: {len(BULLSEYE_WATCHLIST)} tickers (Tier1 + institutionals)")
    logger.info(f"  - Rolling Thunder: {len(ROLLING_WATCHLIST)} tickers (Tier1 + roll-prone)")
    logger.info(f"  - Lotto: {len(LOTTO_WATCHLIST)} tickers (Tier1 + story/beta)")
    logger.info(f"  - 99 Cent Store: {len(SPREAD_WATCHLIST)} tickers (Tier1 only, capped)")
    logger.info(f"  - Walls: 10 tickers (GEX Universe)")
    logger.info(f"  - Gamma Ratio: {len(GAMMA_RATIO_WATCHLIST)} tickers")

    # Ensure core index ETFs are always monitored by flow-focused bots
    _REQUIRED_INDEX_ETFS = ['SPY', 'QQQ', 'IWM']
    for _core_symbol in _REQUIRED_INDEX_ETFS:
        if _core_symbol not in SWEEPS_WATCHLIST:
            SWEEPS_WATCHLIST.insert(0, _core_symbol)
        if _core_symbol not in GOLDEN_SWEEPS_WATCHLIST:
            GOLDEN_SWEEPS_WATCHLIST.insert(0, _core_symbol)

    SKIP_TICKERS = [ticker.strip().upper() for ticker in SKIP_TICKERS if ticker.strip()]
    INDEX_SYMBOLS_BLOCKLIST = [ticker.strip().upper() for ticker in INDEX_SYMBOLS_BLOCKLIST if ticker.strip()]
    
    # Auto-start Settings
    AUTO_START = os.getenv('AUTO_START', 'true').lower() == 'true'
    RESTART_ON_ERROR = os.getenv('RESTART_ON_ERROR', 'true').lower() == 'true'
    LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
    
    # Performance Settings
    MAX_CONCURRENT_REQUESTS = int(os.getenv('MAX_CONCURRENT_REQUESTS', '10'))  # Increased for faster scanning
    REQUEST_TIMEOUT = int(os.getenv('REQUEST_TIMEOUT', '60'))  # Increased timeout
    RETRY_ATTEMPTS = int(os.getenv('RETRY_ATTEMPTS', '3'))
    RETRY_DELAY = int(os.getenv('RETRY_DELAY', '5'))
    MAX_CONSECUTIVE_ERRORS = int(os.getenv('MAX_CONSECUTIVE_ERRORS', '10'))
    SYMBOL_SCAN_TIMEOUT = int(os.getenv('SYMBOL_SCAN_TIMEOUT', '60'))  # Per-symbol scan guardrail (seconds)
    
    # Cache Settings
    CACHE_TTL_API = int(os.getenv('CACHE_TTL_API', '60'))  # 1 minute
    CACHE_TTL_MARKET = int(os.getenv('CACHE_TTL_MARKET', '300'))  # 5 minutes
    CACHE_TTL_ANALYSIS = int(os.getenv('CACHE_TTL_ANALYSIS', '900'))  # 15 minutes
    CACHE_TTL_SIGNALS = int(os.getenv('CACHE_TTL_SIGNALS', '3600'))  # 1 hour
    
    # Market Hours (EST)
    MARKET_OPEN_HOUR = int(os.getenv('MARKET_OPEN_HOUR', '9'))
    MARKET_OPEN_MINUTE = int(os.getenv('MARKET_OPEN_MINUTE', '30'))
    MARKET_CLOSE_HOUR = int(os.getenv('MARKET_CLOSE_HOUR', '16'))
    MARKET_CLOSE_MINUTE = int(os.getenv('MARKET_CLOSE_MINUTE', '0'))

    # Persistence & Analytics
    STATE_DB_PATH = os.getenv('STATE_DB_PATH', 'state/bot_state.db')
    PERFORMANCE_SYMBOL_MIN_OBS = int(os.getenv('PERFORMANCE_SYMBOL_MIN_OBS', '20'))
    PERFORMANCE_SYMBOL_MIN_WIN = float(os.getenv('PERFORMANCE_SYMBOL_MIN_WIN', '0.2'))

    # Bullseye Bot Enhancements
    BULLSEYE_EOD_SKIP_HOUR = int(os.getenv('BULLSEYE_EOD_SKIP_HOUR', '15'))
    BULLSEYE_MAX_FLOW_AGE_HOURS = float(os.getenv('BULLSEYE_MAX_FLOW_AGE_HOURS', '2'))
    BULLSEYE_ATR_MULT_SHORT = float(os.getenv('BULLSEYE_ATR_MULT_SHORT', '1.5'))
    BULLSEYE_ATR_MULT_LONG = float(os.getenv('BULLSEYE_ATR_MULT_LONG', '2.0'))
    BULLSEYE_OUTCOME_POLL_SECONDS = int(os.getenv('BULLSEYE_OUTCOME_POLL_SECONDS', '1800'))
    BULLSEYE_WEEKLY_REPORT_DAY = int(os.getenv('BULLSEYE_WEEKLY_REPORT_DAY', '0'))

    # Index Whale Bot session window (09:30 - 16:15 ET by default)
    INDEX_WHALE_OPEN_HOUR = int(os.getenv('INDEX_WHALE_OPEN_HOUR', '9'))
    INDEX_WHALE_OPEN_MINUTE = int(os.getenv('INDEX_WHALE_OPEN_MINUTE', '30'))
    INDEX_WHALE_CLOSE_HOUR = int(os.getenv('INDEX_WHALE_CLOSE_HOUR', '16'))
    INDEX_WHALE_CLOSE_MINUTE = int(os.getenv('INDEX_WHALE_CLOSE_MINUTE', '15'))
    
    # Chart Settings
    CHART_STYLE = os.getenv('CHART_STYLE', 'seaborn-v0_8-darkgrid')
    CHART_DPI = int(os.getenv('CHART_DPI', '100'))
    CHART_WIDTH = int(os.getenv('CHART_WIDTH', '10'))
    CHART_HEIGHT = int(os.getenv('CHART_HEIGHT', '6'))
    CHART_SIZE = (CHART_WIDTH, CHART_HEIGHT)
    
    # Health Check Settings
    HEALTH_CHECK_INTERVAL = int(os.getenv('HEALTH_CHECK_INTERVAL', '60'))  # 1 minute
    HEALTH_CHECK_TIMEOUT = int(os.getenv('HEALTH_CHECK_TIMEOUT', '10'))
    
    # =============================================================================
    # ORAKL v3.0 "Brain" Settings - State-Aware Market Engine
    # =============================================================================
    
    # GEX (Gamma Exposure) Engine Settings
    GEX_UNIVERSE = os.getenv(
        'GEX_UNIVERSE',
        'SPY,QQQ,IWM,AAPL,NVDA,TSLA,MSFT,AMZN,META,GOOGL'
    ).split(',')
    GEX_UPDATE_INTERVAL = int(os.getenv('GEX_UPDATE_INTERVAL', '300'))  # 5 minutes
    GEX_MAX_DTE_DAYS = int(os.getenv('GEX_MAX_DTE_DAYS', '30'))  # Only include < 30 DTE
    
    # Hedge Hunter Settings
    HEDGE_CHECK_ENABLED = os.getenv('HEDGE_CHECK_ENABLED', 'true').lower() == 'true'
    HEDGE_CHECK_MIN_PREMIUM = float(os.getenv('HEDGE_CHECK_MIN_PREMIUM', '500000'))  # Only check trades > $500k
    HEDGE_WINDOW_NS = int(os.getenv('HEDGE_WINDOW_NS', '50000000'))  # +/- 50ms in nanoseconds
    HEDGE_THRESHOLD_PCT = float(os.getenv('HEDGE_THRESHOLD_PCT', '0.40'))  # 40% of delta-equivalent shares
    HEDGE_DELTA_ESTIMATE = float(os.getenv('HEDGE_DELTA_ESTIMATE', '0.50'))  # 50 delta baseline
    
    # =============================================================================
    # Rolling Thunder Bot Settings - Whale Roll Detection
    # =============================================================================
    ROLLING_THUNDER_WEBHOOK = os.getenv(
        'ROLLING_THUNDER_WEBHOOK',
        'https://discord.com/api/webhooks/1446381206055682089/BKzehoGbfRkwXcBNbouRFD-d3h38-scemd8RJBRTcFJNpAe9DXt5gsF5V_AgXcKzcyGf'
    )
    ROLLING_THUNDER_INTERVAL = int(os.getenv('ROLLING_THUNDER_INTERVAL', '60'))  # 60 seconds
    ROLL_LOOKBACK_SECONDS = int(os.getenv('ROLL_LOOKBACK_SECONDS', '60'))  # Look back 60s for trades
    ROLL_MIN_PREMIUM = float(os.getenv('ROLL_MIN_PREMIUM', '150000'))  # $150K min (rolls often split)
    ROLL_MAX_GAP_SECONDS = float(os.getenv('ROLL_MAX_GAP_SECONDS', '5'))  # Max 5s between legs
    ROLL_NEAR_DTE = int(os.getenv('ROLL_NEAR_DTE', '14'))  # "Closing" leg max DTE
    ROLL_FAR_DTE = int(os.getenv('ROLL_FAR_DTE', '21'))  # "Opening" leg min DTE
    ROLL_COOLDOWN_SECONDS = int(os.getenv('ROLL_COOLDOWN_SECONDS', '1800'))  # 30 min cooldown
    ROLLING_MAX_CONTRACTS = int(os.getenv('ROLLING_MAX_CONTRACTS', '400'))  # Limit chain size per symbol
    
    # =============================================================================
    # Walls Bot Settings - Support/Resistance Detection
    # =============================================================================
    WALLS_BOT_WEBHOOK = os.getenv(
        'WALLS_BOT_WEBHOOK',
        'https://discord.com/api/webhooks/1446398067845632010/VdFunNc3ojx2gnj2uJW1cKeJBA5GWyuSwvLq7Uf5_HHBts5AZu4xNqzGO6ObR09SjAeB'
    )
    WALLS_BOT_INTERVAL = int(os.getenv('WALLS_BOT_INTERVAL', '300'))  # 5 minutes
    WALLS_MIN_OI = int(os.getenv('WALLS_MIN_OI', '5000'))  # Min OI to qualify as wall
    WALLS_PROXIMITY_PCT = float(os.getenv('WALLS_PROXIMITY_PCT', '0.005'))  # 0.5% from wall
    WALLS_MAX_DTE_DAYS = int(os.getenv('WALLS_MAX_DTE_DAYS', '30'))  # Only near-term walls
    WALLS_COOLDOWN_SECONDS = int(os.getenv('WALLS_COOLDOWN_SECONDS', '3600'))  # 1 hour per level
    WALLS_MAX_CONTRACTS = int(os.getenv('WALLS_MAX_CONTRACTS', '400'))  # Limit chain size for walls
    
    # =============================================================================
    # Lotto Bot Settings - Unusual OTM Flow Detection
    # =============================================================================
    LOTTO_BOT_WEBHOOK = os.getenv(
        'LOTTO_BOT_WEBHOOK',
        'https://discord.com/api/webhooks/1446398286570459146/_I5D1A3zRou2EfXP1a5ObwkilJB9PdcovGyvZOThg7FP9mW3012TXMDSXtYjCVDAip4g'
    )
    LOTTO_BOT_INTERVAL = int(os.getenv('LOTTO_BOT_INTERVAL', '300'))  # 5 minutes
    # Lotto Bot defaults: still "lotto-y", but not so strict that it never fires.
    LOTTO_MAX_PRICE = float(os.getenv('LOTTO_MAX_PRICE', '0.75'))  # Raised to $0.75 per contract for more lotto candidates
    LOTTO_MIN_VOL_OI_RATIO = float(os.getenv('LOTTO_MIN_VOL_OI_RATIO', '15.0'))  # 15x volume/OI
    LOTTO_MIN_OTM_PCT = float(os.getenv('LOTTO_MIN_OTM_PCT', '0.07'))  # 7% OTM minimum
    LOTTO_MIN_VOLUME = int(os.getenv('LOTTO_MIN_VOLUME', '200'))  # Min 200 contracts
    LOTTO_MIN_PREMIUM = float(os.getenv('LOTTO_MIN_PREMIUM', '5000'))  # Min $5K total
    LOTTO_MIN_VOLUME = int(os.getenv('LOTTO_MIN_VOLUME', '500'))  # Min 500 contracts
    LOTTO_MIN_PREMIUM = float(os.getenv('LOTTO_MIN_PREMIUM', '10000'))  # Min $10K total
    LOTTO_COOLDOWN_SECONDS = int(os.getenv('LOTTO_COOLDOWN_SECONDS', '1800'))  # 30 min cooldown
    LOTTO_MAX_ALERTS_PER_SCAN = int(os.getenv('LOTTO_MAX_ALERTS_PER_SCAN', '3'))  # Max 3 per scan
    LOTTO_MAX_CONTRACTS = int(os.getenv('LOTTO_MAX_CONTRACTS', '400'))  # Limit chain size per symbol
    
    # =============================================================================
    # ORAKL v2.0 Event-Driven Architecture - Kafka Settings
    # =============================================================================
    # Primary Mode: Kafka consumer on 'processed-flows' topic (real-time)
    # Fallback Mode: REST polling (auto-activates after KAFKA_FALLBACK_TIMEOUT)
    
    KAFKA_ENABLED = os.getenv('KAFKA_ENABLED', 'false').lower() == 'true'
    KAFKA_BROKERS = os.getenv('KAFKA_BROKERS', '')  # Confluent Cloud bootstrap servers
    KAFKA_API_KEY = os.getenv('KAFKA_API_KEY', '')  # SASL username
    KAFKA_API_SECRET = os.getenv('KAFKA_API_SECRET', '')  # SASL password
    KAFKA_TOPIC = os.getenv('KAFKA_TOPIC', 'processed-flows')  # Dashboard's processed flow topic
    KAFKA_GROUP_ID = os.getenv('KAFKA_GROUP_ID', 'orakl-bot-v2-logic-engine')  # MUST be unique
    # Kafka pre-filter threshold (saves CPU + Polygon calls). If this is too high,
    # flow bots may appear "silent" because they never receive events.
    KAFKA_MIN_PREMIUM_FILTER = float(os.getenv('KAFKA_MIN_PREMIUM_FILTER', '50000'))

    # Periodic filter telemetry interval (seconds) for bots (see BaseAutoBot).
    FILTER_REPORT_INTERVAL_SECONDS = int(os.getenv('FILTER_REPORT_INTERVAL_SECONDS', '60'))
    KAFKA_FALLBACK_TIMEOUT = int(os.getenv('KAFKA_FALLBACK_TIMEOUT', '120'))  # 2 min before REST fallback
    KAFKA_ENRICHMENT_TIMEOUT = float(os.getenv('KAFKA_ENRICHMENT_TIMEOUT', '5.0'))  # Polygon fetch timeout
    
    # =============================================================================
    # Unusual Options Activity (UOA) Bot - Stream Filter on Kafka
    # =============================================================================
    # Detects unusual flow patterns on ANY ticker from the stream (no watchlist)
    # Fires when trades show anomalous volume, Vol/OI, or premium characteristics
    
    UOA_ENABLED = os.getenv('UOA_ENABLED', 'true').lower() == 'true'
    UOA_WEBHOOK = os.getenv(
        'UOA_WEBHOOK',
        'https://discord.com/api/webhooks/1446739441572905085/nlp-a8_UZ_UO83drsD-qvCMelK1qVltCwGGUYf4Bc8q5DiKFbp_Hzv_tj89HimslOw8b'
    )
    
    # Premium thresholds (tiered)
    UOA_MIN_PREMIUM = float(os.getenv('UOA_MIN_PREMIUM', '250000'))  # $250K floor
    UOA_SIGNIFICANT_PREMIUM = float(os.getenv('UOA_SIGNIFICANT_PREMIUM', '400000'))  # $400K = notable
    UOA_WHALE_PREMIUM = float(os.getenv('UOA_WHALE_PREMIUM', '500000'))  # $500K = whale
    
    # Volume vs Open Interest (core UOA signal)
    UOA_MIN_VOL_OI_RATIO = float(os.getenv('UOA_MIN_VOL_OI_RATIO', '2.0'))  # Vol >= 2x OI
    UOA_HIGH_VOL_OI_RATIO = float(os.getenv('UOA_HIGH_VOL_OI_RATIO', '5.0'))  # Vol >= 5x OI = very unusual
    UOA_EXTREME_VOL_OI_RATIO = float(os.getenv('UOA_EXTREME_VOL_OI_RATIO', '10.0'))  # Vol >= 10x OI = extreme
    # Optional: require Volume > Open Interest (fresh positioning) to alert at all.
    # This dramatically reduces spam from liquid chains where OI dwarfs daily volume.
    UOA_REQUIRE_VOL_GT_OI = os.getenv('UOA_REQUIRE_VOL_GT_OI', 'true').lower() == 'true'
    
    # Volume thresholds
    UOA_MIN_VOLUME = int(os.getenv('UOA_MIN_VOLUME', '500'))  # Min 500 contracts
    UOA_MIN_TRADE_SIZE = int(os.getenv('UOA_MIN_TRADE_SIZE', '250'))  # Min single print size
    
    # DTE and OTM filters
    UOA_MAX_DTE = int(os.getenv('UOA_MAX_DTE', '45'))  # Max 45 DTE (focus on near-term)
    UOA_MIN_OTM_PCT = float(os.getenv('UOA_MIN_OTM_PCT', '0.0'))  # 0% = include ATM/ITM
    UOA_MAX_OTM_PCT = float(os.getenv('UOA_MAX_OTM_PCT', '0.30'))  # 30% max OTM
    
    # Spam prevention
    UOA_COOLDOWN_SECONDS = int(os.getenv('UOA_COOLDOWN_SECONDS', '600'))  # 10 min per symbol
    # Contract-level dedupe prevents floods when the same strike/exp prints repeatedly.
    UOA_CONTRACT_COOLDOWN_SECONDS = int(os.getenv('UOA_CONTRACT_COOLDOWN_SECONDS', '900'))  # 15 min per contract
    # Global throttle (protect Discord + sanity)
    UOA_MAX_ALERTS_PER_MINUTE = int(os.getenv('UOA_MAX_ALERTS_PER_MINUTE', '20'))
    UOA_MAX_ALERTS_PER_SYMBOL = int(os.getenv('UOA_MAX_ALERTS_PER_SYMBOL', '2'))  # Max 2 per symbol per hour
    UOA_ALERT_WINDOW_SECONDS = int(os.getenv('UOA_ALERT_WINDOW_SECONDS', '3600'))  # 1 hour window
    
    # Minimum reasons required to trigger (prevents weak signals)
    UOA_MIN_REASONS = int(os.getenv('UOA_MIN_REASONS', '3'))  # Need at least 3 unusual factors
    
    @classmethod
    def validate(cls):
        """Validate required configuration with comprehensive checks"""
        errors = []
        warnings = []
        
        # API Key validation
        if not cls.POLYGON_API_KEY or cls.POLYGON_API_KEY == 'your_polygon_key_here':
            errors.append("POLYGON_API_KEY is not set")
            
        if not cls.DISCORD_BOT_TOKEN or cls.DISCORD_BOT_TOKEN == 'your_discord_bot_token_here':
            warnings.append("DISCORD_BOT_TOKEN is not set (required for bot commands)")
            
        if not cls.DISCORD_WEBHOOK_URL or 'your_webhook_here' in cls.DISCORD_WEBHOOK_URL:
            errors.append("DISCORD_WEBHOOK_URL is not set")
        
        # Kafka validation (only when enabled)
        if cls.KAFKA_ENABLED:
            if not cls.KAFKA_BROKERS:
                errors.append("KAFKA_BROKERS is required when KAFKA_ENABLED=true")
            if not cls.KAFKA_API_KEY:
                errors.append("KAFKA_API_KEY is required when KAFKA_ENABLED=true")
            if not cls.KAFKA_API_SECRET:
                errors.append("KAFKA_API_SECRET is required when KAFKA_ENABLED=true")
            logger.info("Kafka Mode: ENABLED (real-time event-driven)")
            logger.info(f"  Topic: {cls.KAFKA_TOPIC}")
            logger.info(f"  Group ID: {cls.KAFKA_GROUP_ID}")
            logger.info(f"  Min Premium Filter: ${cls.KAFKA_MIN_PREMIUM_FILTER:,.0f}")
        else:
            logger.info("Kafka Mode: DISABLED (using REST polling fallback)")
            
        # Watchlist validation
        if not cls.WATCHLIST:
            errors.append("WATCHLIST is empty")
        elif len(cls.WATCHLIST) > 50:
            warnings.append(f"WATCHLIST has {len(cls.WATCHLIST)} symbols, which may impact performance")
            
        # Threshold validation
        if cls.MIN_PREMIUM <= 0:
            errors.append("MIN_PREMIUM must be positive")
        elif cls.MIN_PREMIUM < 1000:
            warnings.append(f"MIN_PREMIUM (${cls.MIN_PREMIUM}) is very low, may generate noise")
            
        if cls.MIN_VOLUME <= 0:
            errors.append("MIN_VOLUME must be positive")
            
        # Interval validation
        min_interval = 60  # 1 minute minimum
        for attr_name in dir(cls):
            if attr_name.endswith('_INTERVAL') and not attr_name.startswith('_'):
                interval = getattr(cls, attr_name)
                if isinstance(interval, int) and interval < min_interval:
                    errors.append(f"{attr_name} must be at least {min_interval} seconds")
                    
        # Score threshold validation
        for attr_name in dir(cls):
            if '_SCORE' in attr_name and not attr_name.startswith('_'):
                score = getattr(cls, attr_name)
                if isinstance(score, int) and not 0 <= score <= 100:
                    errors.append(f"{attr_name} must be between 0 and 100")
                    
        # Performance settings validation
        if cls.MAX_CONCURRENT_REQUESTS < 1:
            errors.append("MAX_CONCURRENT_REQUESTS must be at least 1")
        elif cls.MAX_CONCURRENT_REQUESTS > 10:
            warnings.append("MAX_CONCURRENT_REQUESTS > 10 may hit rate limits")
            
        if cls.REQUEST_TIMEOUT < 5:
            errors.append("REQUEST_TIMEOUT must be at least 5 seconds")
            
        if cls.RETRY_ATTEMPTS < 0:
            errors.append("RETRY_ATTEMPTS cannot be negative")
            
        # Market hours validation
        if not (0 <= cls.MARKET_OPEN_HOUR <= 23):
            errors.append("MARKET_OPEN_HOUR must be between 0 and 23")
        if not (0 <= cls.MARKET_OPEN_MINUTE <= 59):
            errors.append("MARKET_OPEN_MINUTE must be between 0 and 59")
        if not (0 <= cls.MARKET_CLOSE_HOUR <= 23):
            errors.append("MARKET_CLOSE_HOUR must be between 0 and 23")
        if not (0 <= cls.MARKET_CLOSE_MINUTE <= 59):
            errors.append("MARKET_CLOSE_MINUTE must be between 0 and 59")
            
        # Success rate threshold validation
        if not 0 <= cls.SUCCESS_RATE_THRESHOLD <= 1:
            errors.append("SUCCESS_RATE_THRESHOLD must be between 0 and 1")
            
        # Log level validation
        valid_log_levels = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']
        if cls.LOG_LEVEL not in valid_log_levels:
            errors.append(f"LOG_LEVEL must be one of {valid_log_levels}")
            
        # Print warnings
        for warning in warnings:
            logger.warning(f"Configuration warning: {warning}")
            
        # Raise error if any critical issues
        if errors:
            raise ValueError(f"Configuration errors:\n" + "\n".join(f"  - {e}" for e in errors))
            
        # Log successful validation
        logger.info("=" * 60)
        logger.info("Configuration validated successfully")
        logger.info("=" * 60)
        logger.info(f"Bot Name: {cls.BOT_NAME}")
        logger.info(f"Watchlist: {len(cls.WATCHLIST)} symbols")
        logger.info(f"Log Level: {cls.LOG_LEVEL}")
        logger.info(f"Auto Start: {cls.AUTO_START}")
        logger.info("-" * 60)
        logger.info("Thresholds:")
        logger.info(f"  Min Premium: ${cls.MIN_PREMIUM:,.0f}")
        logger.info(f"  Min Volume: {cls.MIN_VOLUME:,}")
        logger.info(f"  Success Rate: {cls.SUCCESS_RATE_THRESHOLD:.0%}")
        logger.info(f"  Repeat Signals: {cls.REPEAT_SIGNAL_THRESHOLD}")
        logger.info("-" * 60)
        logger.info("Bot-specific Settings:")
        logger.info(f"  Golden Sweeps: ${cls.GOLDEN_MIN_PREMIUM:,.0f} (Score: {cls.MIN_GOLDEN_SCORE})")
        logger.info(f"  Sweeps: ${cls.SWEEPS_MIN_PREMIUM:,.0f} (Score: {cls.MIN_SWEEP_SCORE})")
        logger.info(f"  Bullseye (Institutional): ${cls.BULLSEYE_MIN_PREMIUM:,.0f} (Score: {cls.MIN_BULLSEYE_SCORE})")
        logger.info("=" * 60)
        
        return True
    
    @classmethod
    def get_config_dict(cls):
        """Get configuration as dictionary"""
        return {
            'bot_name': cls.BOT_NAME,
            'scan_interval': cls.SCAN_INTERVAL_MINUTES,
            'min_premium': cls.MIN_PREMIUM,
            'min_volume': cls.MIN_VOLUME,
            'unusual_volume_multiplier': cls.UNUSUAL_VOLUME_MULTIPLIER,
            'repeat_signal_threshold': cls.REPEAT_SIGNAL_THRESHOLD,
            'success_rate_threshold': cls.SUCCESS_RATE_THRESHOLD,
            'watchlist_count': len(cls.WATCHLIST),
            'auto_start': cls.AUTO_START,
            'log_level': cls.LOG_LEVEL
        }
    
    @classmethod
    def print_config(cls):
        """Print current configuration"""
        print("\n" + "="*50)
        print("ORAKL Bot Configuration")
        print("="*50)
        config = cls.get_config_dict()
        for key, value in config.items():
            print(f"{key.replace('_', ' ').title()}: {value}")
        print("="*50 + "\n")

# Set logging level based on config
logging.getLogger().setLevel(getattr(logging, Config.LOG_LEVEL, logging.INFO))
