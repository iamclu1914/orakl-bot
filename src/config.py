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
    SWEEPS_WEBHOOK = os.getenv('SWEEPS_WEBHOOK', DISCORD_WEBHOOK_URL)
    GOLDEN_SWEEPS_WEBHOOK = os.getenv('GOLDEN_SWEEPS_WEBHOOK', DISCORD_WEBHOOK_URL)
    BULLSEYE_WEBHOOK = os.getenv('BULLSEYE_WEBHOOK', DISCORD_WEBHOOK_URL)
    SPREAD_WEBHOOK = os.getenv('SPREAD_WEBHOOK', DISCORD_WEBHOOK_URL)
    INDEX_WHALE_WEBHOOK = os.getenv('INDEX_WHALE_WEBHOOK', DISCORD_WEBHOOK_URL)
    GAMMA_RATIO_WEBHOOK = os.getenv('GAMMA_RATIO_WEBHOOK', DISCORD_WEBHOOK_URL)
    
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
    
    # Bot-specific Thresholds - OPTIMIZED FOR QUALITY
    GOLDEN_MIN_PREMIUM = float(os.getenv('GOLDEN_MIN_PREMIUM', '1000000'))  # $1M (true institutional size)
    SWEEPS_MIN_PREMIUM = float(os.getenv('SWEEPS_MIN_PREMIUM', '750000'))  # $750K (raised for conviction)
    SWEEPS_MIN_VOLUME_RATIO = float(os.getenv('SWEEPS_MIN_VOLUME_RATIO', '1.3'))  # 1.3x (raised)
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
    BULLSEYE_MIN_PREMIUM = float(os.getenv('BULLSEYE_MIN_PREMIUM', '1000000'))  # $1M minimum (institutional size)
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
    # 99 Cent Store Bot Thresholds (sub-$1 swing trades - OPTIMIZED FOR QUALITY)
    SPREAD_MIN_PREMIUM = float(os.getenv('SPREAD_MIN_PREMIUM', '400000'))  # $400K+ (raised for conviction)
    SPREAD_MIN_VOLUME = int(os.getenv('SPREAD_MIN_VOLUME', '1000'))  # 1000 contracts for liquidity
    SPREAD_MIN_VOLUME_DELTA = int(os.getenv('SPREAD_MIN_VOLUME_DELTA', '500'))  # Strong new flow
    SPREAD_MAX_PRICE = float(os.getenv('SPREAD_MAX_PRICE', '1.00'))  # Hard cap: sub-$1.00 contracts only
    SPREAD_MIN_PRICE = float(os.getenv('SPREAD_MIN_PRICE', '0.05'))  # Avoid illiquid penny options
    SPREAD_MIN_VOI_RATIO = float(os.getenv('SPREAD_MIN_VOI_RATIO', '2.5'))  # 2.5x VOI (raised for quality)
    SPREAD_MIN_DTE = float(os.getenv('SPREAD_MIN_DTE', '2.0'))  # 2 days minimum for swing trades
    SPREAD_MAX_DTE = float(os.getenv('SPREAD_MAX_DTE', '30.0'))  # Up to 4 weeks for swing trades
    SPREAD_MAX_PERCENT_OTM = float(os.getenv('SPREAD_MAX_PERCENT_OTM', '0.10'))  # 10% OTM max (tightened)
    SPREAD_COOLDOWN_SECONDS = int(os.getenv('SPREAD_COOLDOWN_SECONDS', '1800'))  # 30 min cooldown (new)
    SPREAD_MAX_ALERTS_PER_SCAN = int(os.getenv('SPREAD_MAX_ALERTS_PER_SCAN', '2'))  # Max 2 per scan (new)

    # Gamma Ratio Bot Thresholds (G = call_gamma / total_gamma)
    # G → 1.0 = call-driven, G → 0.0 = put-driven, G ≈ 0.5 = balanced
    GAMMA_RATIO_CONSTANT_VOL = float(os.getenv('GAMMA_RATIO_CONSTANT_VOL', '0.20'))  # BSM volatility assumption
    GAMMA_RATIO_RISK_FREE_RATE = float(os.getenv('GAMMA_RATIO_RISK_FREE_RATE', '0.0'))
    GAMMA_RATIO_MIN_OI = int(os.getenv('GAMMA_RATIO_MIN_OI', '100'))  # Minimum OI to include
    GAMMA_RATIO_MAX_OTM_PCT = float(os.getenv('GAMMA_RATIO_MAX_OTM_PCT', '0.20'))  # Max distance from spot
    GAMMA_RATIO_MIN_TOTAL_GAMMA = float(os.getenv('GAMMA_RATIO_MIN_TOTAL_GAMMA', '5000'))  # Min gamma to filter illiquid names
    GAMMA_RATIO_MAX_CONTRACTS = int(os.getenv('GAMMA_RATIO_MAX_CONTRACTS', '750'))  # Max contracts to fetch (3 pages)
    GAMMA_RATIO_EXPIRY_DAYS = int(os.getenv('GAMMA_RATIO_EXPIRY_DAYS', '45'))  # Only near-term contracts
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
    WATCHLIST_MODE = os.getenv('WATCHLIST_MODE', 'ALL_MARKET')  # ALL_MARKET or STATIC
    WATCHLIST_REFRESH_INTERVAL = int(os.getenv('WATCHLIST_REFRESH_INTERVAL', '86400'))  # 24 hours in seconds

    # Minimum liquidity filters for ALL_MARKET mode
    MIN_MARKET_CAP = float(os.getenv('MIN_MARKET_CAP', '500000000'))  # $500M minimum
    MIN_DAILY_VOLUME = int(os.getenv('MIN_DAILY_VOLUME', '500000'))  # 500K shares minimum
    MIN_STOCK_PRICE = float(os.getenv('MIN_STOCK_PRICE', '5.0'))  # $5 minimum (avoid penny stocks)
    MAX_STOCK_PRICE = float(os.getenv('MAX_STOCK_PRICE', '10000'))  # $10K max (filter out Berkshire)

    # Unified Watchlist - OPTIMIZED FOR SCAN COMPLETION (~150 high-activity symbols)
    # Reduced from ~400 to prevent scan timeouts while covering most options flow
    _UNIFIED_WATCHLIST = (
        # Indices & ETFs (15)
        'SPY,QQQ,IWM,DIA,XLF,XLE,XLK,XLV,XLY,XLC,SMH,ARKK,SOXL,GLD,TLT,'
        # Mega-Cap Tech (20)
        'AAPL,MSFT,NVDA,GOOGL,META,AMZN,TSLA,AMD,AVGO,ADBE,CRM,ORCL,CSCO,INTC,QCOM,'
        'TXN,MU,AMAT,LRCX,KLAC,'
        # High-Options-Volume Growth (30)
        'PLTR,COIN,HOOD,SOFI,MARA,RIOT,SMCI,ARM,DELL,NET,SNOW,DDOG,CRWD,PANW,ZS,'
        'SHOP,SQ,PYPL,ROKU,SNAP,RBLX,U,ABNB,UBER,LYFT,DKNG,PENN,DASH,DOCU,OKTA,'
        # Meme & High-Beta (15)
        'GME,AMC,RIVN,LCID,NIO,PLUG,CHPT,SPCE,BB,MSTR,UPST,AFRM,SOUN,BBAI,AI,'
        # Healthcare & Biotech (15)
        'UNH,LLY,JNJ,PFE,MRNA,BNTX,ABBV,MRK,BMY,GILD,AMGN,REGN,ISRG,VRTX,BIIB,'
        # Financials (10)
        'JPM,BAC,GS,MS,WFC,C,V,MA,AXP,BLK,'
        # Energy & Materials (10)
        'XOM,CVX,COP,SLB,OXY,FCX,NEM,AA,CLF,CCJ,'
        # Consumer & Industrial (15)
        'DIS,NFLX,NKE,SBUX,MCD,HD,LOW,BA,CAT,GE,DE,LMT,RTX,UPS,FDX,'
        # Small Account Friendly Under $30 (20)
        'F,GM,T,VZ,PARA,WBD,AAL,DAL,UAL,CCL,RCL,PINS,BABA,ENPH,TEAM,ZM,PATH,ON,MRVL,RKLB'
    )
    
    # Legacy variable for backwards compatibility
    _DEFAULT_WATCHLIST = _UNIFIED_WATCHLIST

    STATIC_WATCHLIST = os.getenv('WATCHLIST', _UNIFIED_WATCHLIST).split(',')
    _UNIFIED_LIST = [ticker.strip().upper() for ticker in _UNIFIED_WATCHLIST.split(',') if ticker.strip()]

    SWEEPS_WATCHLIST = os.getenv(
        'SWEEPS_WATCHLIST',
        ','.join(_UNIFIED_LIST)
    ).split(',')

    GOLDEN_SWEEPS_WATCHLIST = os.getenv(
        'GOLDEN_SWEEPS_WATCHLIST',
        ','.join(_UNIFIED_LIST)
    ).split(',')
    INDEX_WHALE_WATCHLIST = os.getenv(
        'INDEX_WHALE_WATCHLIST',
        'SPY,QQQ,IWM'
    ).split(',')
    SPREAD_WATCHLIST = os.getenv(
        'SPREAD_WATCHLIST',
        ','.join(_UNIFIED_LIST)
    ).split(',')
    SPREAD_EXTRA_TICKERS = os.getenv(
        'SPREAD_EXTRA_TICKERS',
        'BBBY,SNDL,TLRY,CLOV,MARA,RIOT,MSTR,SQ,BNTX,MRNA,TQQQ,SQQQ,UPRO,GLD,SLV,USO,COF,USB,PNC,MRO,DVN,FANG,'
        'WYNN,LVS,PENN,PLTR,AMD,NVDA,TSLA,RIVN,LCID,NIO,F,GM,AMC,GME,COIN,HOOD,SOFI,UBER,LYFT,ABNB,CCL,RCL,SNAP,'
        'ROKU,NET,DDOG,MU,ON,ARM,SMCI,SHOP,CRWD,SNOW'
    ).split(',')
    # Gamma Bot default: Focus on index ETFs + mega caps only (gamma calculation is heavy)
    # Reduced from 18 to 9 to ensure scans complete within timeout
    # Can override via GAMMA_RATIO_WATCHLIST env var
    _GAMMA_DEFAULT = 'SPY,QQQ,IWM,DIA,TSLA,AAPL,NVDA,AMD,MSFT'
    GAMMA_RATIO_WATCHLIST = os.getenv(
        'GAMMA_RATIO_WATCHLIST',
        _GAMMA_DEFAULT
    ).split(',')

    SKIP_TICKERS = os.getenv(
        'SKIP_TICKERS',
        'ABC,ATVI,BRK-A,BRK-B,SPX,DFS'
    ).split(',')

    # Initialize WATCHLIST (will be populated dynamically by WatchlistManager)
    # All watchlists now use the unified list
    WATCHLIST = [ticker.strip().upper() for ticker in STATIC_WATCHLIST if ticker.strip()]
    SWEEPS_WATCHLIST = [ticker.strip().upper() for ticker in SWEEPS_WATCHLIST if ticker.strip()]
    GOLDEN_SWEEPS_WATCHLIST = [ticker.strip().upper() for ticker in GOLDEN_SWEEPS_WATCHLIST if ticker.strip()]
    INDEX_WHALE_WATCHLIST = [ticker.strip().upper() for ticker in INDEX_WHALE_WATCHLIST if ticker.strip()]
    SPREAD_WATCHLIST = [ticker.strip().upper() for ticker in SPREAD_WATCHLIST if ticker.strip()]
    SPREAD_EXTRA_TICKERS = [ticker.strip().upper() for ticker in SPREAD_EXTRA_TICKERS if ticker.strip()]
    GAMMA_RATIO_WATCHLIST = [ticker.strip().upper() for ticker in GAMMA_RATIO_WATCHLIST if ticker.strip()]
    
    # Verify all bots have same watchlist count
    logger.info(f"Unified Watchlist: {len(_UNIFIED_LIST)} tickers")
    logger.info(f"  - Sweeps: {len(SWEEPS_WATCHLIST)} tickers")
    logger.info(f"  - Golden Sweeps: {len(GOLDEN_SWEEPS_WATCHLIST)} tickers")
    logger.info(f"  - Index Whale: {len(INDEX_WHALE_WATCHLIST)} tickers")
    logger.info(f"  - Spread Sniper: {len(SPREAD_WATCHLIST)} tickers (+{len(SPREAD_EXTRA_TICKERS)} extras)")
    logger.info(f"  - Bullseye: Uses SWEEPS_WATCHLIST")
    logger.info(f"  - Gamma Ratio: {len(GAMMA_RATIO_WATCHLIST)} tickers")

    # Ensure core index ETFs are always monitored by flow-focused bots
    _REQUIRED_INDEX_ETFS = ['SPY', 'QQQ', 'IWM']
    for _core_symbol in _REQUIRED_INDEX_ETFS:
        if _core_symbol not in SWEEPS_WATCHLIST:
            SWEEPS_WATCHLIST.insert(0, _core_symbol)
        if _core_symbol not in GOLDEN_SWEEPS_WATCHLIST:
            GOLDEN_SWEEPS_WATCHLIST.insert(0, _core_symbol)

    SKIP_TICKERS = [ticker.strip().upper() for ticker in SKIP_TICKERS if ticker.strip()]
    
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
    SYMBOL_SCAN_TIMEOUT = int(os.getenv('SYMBOL_SCAN_TIMEOUT', '45'))  # Per-symbol scan guardrail (seconds) - increased for large option chains
    
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
    
    # =============================================================================
    # Lotto Bot Settings - Unusual OTM Flow Detection
    # =============================================================================
    LOTTO_BOT_WEBHOOK = os.getenv(
        'LOTTO_BOT_WEBHOOK',
        'https://discord.com/api/webhooks/1446398286570459146/_I5D1A3zRou2EfXP1a5ObwkilJB9PdcovGyvZOThg7FP9mW3012TXMDSXtYjCVDAip4g'
    )
    LOTTO_BOT_INTERVAL = int(os.getenv('LOTTO_BOT_INTERVAL', '300'))  # 5 minutes
    LOTTO_MAX_PRICE = float(os.getenv('LOTTO_MAX_PRICE', '0.15'))  # Max $0.15 per contract
    LOTTO_MIN_VOL_OI_RATIO = float(os.getenv('LOTTO_MIN_VOL_OI_RATIO', '50.0'))  # 50x volume/OI
    LOTTO_MIN_OTM_PCT = float(os.getenv('LOTTO_MIN_OTM_PCT', '0.10'))  # 10% OTM minimum
    LOTTO_MIN_VOLUME = int(os.getenv('LOTTO_MIN_VOLUME', '500'))  # Min 500 contracts
    LOTTO_MIN_PREMIUM = float(os.getenv('LOTTO_MIN_PREMIUM', '10000'))  # Min $10K total
    LOTTO_COOLDOWN_SECONDS = int(os.getenv('LOTTO_COOLDOWN_SECONDS', '1800'))  # 30 min cooldown
    LOTTO_MAX_ALERTS_PER_SCAN = int(os.getenv('LOTTO_MAX_ALERTS_PER_SCAN', '3'))  # Max 3 per scan
    
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
