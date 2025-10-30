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
    POLYGON_API_KEY = os.getenv('POLYGON_API_KEY', 'NnbFphaif6yWkufcTV8rOEDXRi2LefZN')
    DISCORD_BOT_TOKEN = os.getenv('DISCORD_BOT_TOKEN', '')
    DISCORD_WEBHOOK_URL = os.getenv('DISCORD_WEBHOOK_URL', 'https://discord.com/api/webhooks/1427156966979010663/LQ-OzXtrj3WifaYADAWnVb9IzHbFhCcUxUmPTdylqWFSGJIz7Rwjwbl-o-B-n-7-VfkF')
    
    # Individual Bot Webhooks (Each bot posts to its own dedicated channel)
    SWEEPS_WEBHOOK = os.getenv('SWEEPS_WEBHOOK', DISCORD_WEBHOOK_URL)
    GOLDEN_SWEEPS_WEBHOOK = os.getenv('GOLDEN_SWEEPS_WEBHOOK', DISCORD_WEBHOOK_URL)
    SCALPS_WEBHOOK = os.getenv('SCALPS_WEBHOOK', DISCORD_WEBHOOK_URL)
    BULLSEYE_WEBHOOK = os.getenv('BULLSEYE_WEBHOOK', DISCORD_WEBHOOK_URL)
    DARKPOOL_WEBHOOK = os.getenv('DARKPOOL_WEBHOOK', DISCORD_WEBHOOK_URL)
    ORAKL_FLOW_WEBHOOK = os.getenv('ORAKL_FLOW_WEBHOOK', DISCORD_WEBHOOK_URL)
    STRAT_WEBHOOK = os.getenv('STRAT_WEBHOOK', DISCORD_WEBHOOK_URL)
    
    # Discord Settings
    DISCORD_COMMAND_PREFIX = os.getenv('DISCORD_COMMAND_PREFIX', 'ok-')
    DISCORD_CHANNEL_ID = int(os.getenv('DISCORD_CHANNEL_ID', '1427156934582079588'))
    ALERT_CHANNEL_ID = int(os.getenv('ALERT_CHANNEL_ID', '1427156934582079588'))
    
    # Bot Scan Intervals (seconds) - Original intervals restored
    TRADY_FLOW_INTERVAL = int(os.getenv('TRADY_FLOW_INTERVAL', '300'))  # 5 minutes
    BULLSEYE_INTERVAL = int(os.getenv('BULLSEYE_INTERVAL', '180'))  # 3 minutes
    SCALPS_INTERVAL = int(os.getenv('SCALPS_INTERVAL', '120'))  # 2 minutes
    SWEEPS_INTERVAL = int(os.getenv('SWEEPS_INTERVAL', '180'))  # 3 minutes
    GOLDEN_SWEEPS_INTERVAL = int(os.getenv('GOLDEN_SWEEPS_INTERVAL', '900'))  # 15 minutes
    DARKPOOL_INTERVAL = int(os.getenv('DARKPOOL_INTERVAL', '900'))  # 15 minutes
    STRAT_INTERVAL = int(os.getenv('STRAT_INTERVAL', '300'))  # 5 minutes
    
    # ORAKL Flow Settings
    SCAN_INTERVAL_MINUTES = int(os.getenv('SCAN_INTERVAL_MINUTES', '5'))
    MIN_PREMIUM = float(os.getenv('MIN_PREMIUM', '10000'))
    MIN_VOLUME = int(os.getenv('MIN_VOLUME', '100'))
    UNUSUAL_VOLUME_MULTIPLIER = float(os.getenv('UNUSUAL_VOLUME_MULTIPLIER', '3'))
    REPEAT_SIGNAL_THRESHOLD = int(os.getenv('REPEAT_SIGNAL_THRESHOLD', '3'))
    SUCCESS_RATE_THRESHOLD = float(os.getenv('SUCCESS_RATE_THRESHOLD', '0.65'))
    
    # Bot-specific Thresholds
    GOLDEN_MIN_PREMIUM = float(os.getenv('GOLDEN_MIN_PREMIUM', '1000000'))  # $1M
    DARKPOOL_MIN_BLOCK_SIZE = int(os.getenv('DARKPOOL_MIN_BLOCK_SIZE', '10000'))
    SWEEPS_MIN_PREMIUM = float(os.getenv('SWEEPS_MIN_PREMIUM', '50000'))  # $50k
    BULLSEYE_MIN_PREMIUM = float(os.getenv('BULLSEYE_MIN_PREMIUM', '5000'))  # $5k for intraday
    SCALPS_MIN_PREMIUM = float(os.getenv('SCALPS_MIN_PREMIUM', '2000'))  # $2k for scalps
    MIN_VOLUME_RATIO = float(os.getenv('MIN_VOLUME_RATIO', '3.0'))  # 3x volume for unusual
    MIN_ABSOLUTE_VOLUME = int(os.getenv('MIN_ABSOLUTE_VOLUME', '1000000'))  # 1M shares minimum

    # Score Thresholds
    MIN_GOLDEN_SCORE = int(os.getenv('MIN_GOLDEN_SCORE', '65'))
    MIN_SWEEP_SCORE = int(os.getenv('MIN_SWEEP_SCORE', '60'))
    MIN_DARKPOOL_SCORE = int(os.getenv('MIN_DARKPOOL_SCORE', '60'))
    MIN_BULLSEYE_SCORE = int(os.getenv('MIN_BULLSEYE_SCORE', '70'))
    MIN_SCALP_SCORE = int(os.getenv('MIN_SCALP_SCORE', '65'))
    
    # Watchlist Mode - Dynamic or Static
    WATCHLIST_MODE = os.getenv('WATCHLIST_MODE', 'ALL_MARKET')  # ALL_MARKET or STATIC
    WATCHLIST_REFRESH_INTERVAL = int(os.getenv('WATCHLIST_REFRESH_INTERVAL', '86400'))  # 24 hours in seconds

    # Minimum liquidity filters for ALL_MARKET mode
    MIN_MARKET_CAP = float(os.getenv('MIN_MARKET_CAP', '500000000'))  # $500M minimum
    MIN_DAILY_VOLUME = int(os.getenv('MIN_DAILY_VOLUME', '500000'))  # 500K shares minimum
    MIN_STOCK_PRICE = float(os.getenv('MIN_STOCK_PRICE', '5.0'))  # $5 minimum (avoid penny stocks)
    MAX_STOCK_PRICE = float(os.getenv('MAX_STOCK_PRICE', '10000'))  # $10K max (filter out Berkshire)

    # Static Watchlist (fallback when WATCHLIST_MODE = 'STATIC')
    _DEFAULT_WATCHLIST = (
        # Indices & ETFs
        'SPY,QQQ,IWM,DIA,'
        # Technology
        'AAPL,MSFT,NVDA,GOOGL,META,AMD,AVGO,ADBE,CRM,ORCL,CSCO,INTC,QCOM,TXN,PLTR,CRWD,PANW,'
        # Consumer Discretionary
        'AMZN,TSLA,NFLX,HD,NKE,SBUX,MCD,TGT,BKNG,LOW,DIS,'
        # Financial Services
        'JPM,BAC,WFC,GS,MS,C,BLK,SCHW,AXP,V,MA,PYPL,'
        # Healthcare
        'UNH,JNJ,LLY,ABBV,MRK,PFE,TMO,ABT,DHR,BMY,AMGN,CVS,GILD,'
        # Energy
        'XOM,CVX,COP,SLB,EOG,MPC,PSX,VLO,OXY,HAL,'
        # Industrials
        'BA,CAT,GE,HON,UPS,RTX,LMT,DE,MMM,UNP,'
        # Communication Services
        'T,VZ,CMCSA,TMUS,DIS,'
        # Consumer Staples
        'PG,KO,PEP,WMT,COST,PM,MO,CL,MDLZ,'
        # Materials
        'LIN,APD,ECL,DD,NEM,FCX,DOW,'
        # Real Estate
        'AMT,PLD,CCI,EQIX,PSA,'
        # Utilities
        'NEE,DUK,SO,D,AEP'
    )

    STATIC_WATCHLIST = os.getenv('WATCHLIST', _DEFAULT_WATCHLIST).split(',')
    _DEFAULT_STATIC_LIST = [ticker.strip().upper() for ticker in _DEFAULT_WATCHLIST.split(',') if ticker.strip()]

    SCALPS_WATCHLIST = os.getenv(
        'SCALPS_WATCHLIST',
        (
            'SPY,QQQ,NVDA,TSLA,AMD,AAPL,MSFT,META,GOOGL,'
            'AMZN,SMCI,CRM,PLTR,COIN,INTC,SOFI,RIVN,AFRM,'
            'SNOW,NET,SHOP,LSCC,ON,MRVL,LCID,UPST,ROKU,'
            'ETSY,AI,BB,CHPT,CLSK,MU,SQ,UBER,ABNB'
        )
    ).split(',')

    ORAKL_FLOW_WATCHLIST = os.getenv(
        'ORAKL_FLOW_WATCHLIST',
        ','.join(_DEFAULT_STATIC_LIST[:80])
    ).split(',')

    SWEEPS_WATCHLIST = os.getenv(
        'SWEEPS_WATCHLIST',
        ','.join(_DEFAULT_STATIC_LIST[:120])
    ).split(',')

    _DEFAULT_GOLDEN_LIST = (
        # Mega cap technology & AI leaders
        'AAPL,MSFT,NVDA,GOOGL,META,AMZN,TSLA,AVGO,ADBE,CRM,ORCL,CSCO,INTC,AMD,QCOM,TXN,SMCI,SHOP,PLTR,'  # noqa: E501
        # Financial heavyweights & crypto-exposed
        'JPM,BAC,WFC,MS,GS,C,BLK,SCHW,AXP,V,MA,PYPL,COIN,HOOD,'  # noqa: E501
        # Energy & industrial majors
        'XOM,CVX,COP,SLB,EOG,MPC,PSX,VLO,OXY,HAL,BA,CAT,GE,DE,UPS,LMT,RTX,UNP,'  # noqa: E501
        # Discretionary & consumer brands
        'HD,NKE,SBUX,MCD,TGT,BKNG,LOW,DIS,CMG,LULU,TSCO,DPZ,'  # noqa: E501
        # Healthcare & biotech momentum names
        'LLY,UNH,ABBV,MNKD,MRK,PFE,TMO,DHR,ISRG,VRTX,REGN,VRTX,'  # noqa: E501
        # High-beta tech & growth favorites
        'NFLX,SNOW,NET,ROKU,CRWD,PANW,ZS,DDOG,OKTA,SPLK,TEAM,ZM,AFRM,RIVN,LCID,MU,ON,MRVL,ARM,'  # noqa: E501
        # Semiconductors & hardware
        'ASML,LRCX,MPWR,NXPI,ADI,KLAC,AMAT,TSM,BRCM,STM,'  # noqa: E501
        # Materials & commodities movers
        'FCX,NEM,AA,CLF,VALE,CCJ,ALB,LTHM,MP,'  # noqa: E501
        # Media, telecom & entertainment
        'CMCSA,TMUS,CHTR,T,TMUS,VZ,PARA,WBD,EA,TTWO,'  # noqa: E501
        # Travel & reopening plays
        'UBER,LYFT,ABNB,CCL,RCL,MAR,H,HLT,UAL,DAL,AAL,SBUX,EXPE,'  # noqa: E501
        # ETFs for mega moves
        'SPY,QQQ,IWM,DIA,ARKK,SOXL,SMH,XLF,XLE,XLY,XLC'  # noqa: E501
    )

    GOLDEN_SWEEPS_WATCHLIST = os.getenv(
        'GOLDEN_SWEEPS_WATCHLIST',
        _DEFAULT_GOLDEN_LIST
    ).split(',')

    SKIP_TICKERS = os.getenv(
        'SKIP_TICKERS',
        'ABC,ATVI,BRK-A,BRK-B,SPX,DFS'
    ).split(',')

    # Initialize WATCHLIST (will be populated dynamically by WatchlistManager)
    WATCHLIST = [ticker.strip().upper() for ticker in STATIC_WATCHLIST if ticker.strip()]
    SCALPS_WATCHLIST = [ticker.strip().upper() for ticker in SCALPS_WATCHLIST if ticker.strip()]
    ORAKL_FLOW_WATCHLIST = [ticker.strip().upper() for ticker in ORAKL_FLOW_WATCHLIST if ticker.strip()]
    SWEEPS_WATCHLIST = [ticker.strip().upper() for ticker in SWEEPS_WATCHLIST if ticker.strip()]
    GOLDEN_SWEEPS_WATCHLIST = [ticker.strip().upper() for ticker in GOLDEN_SWEEPS_WATCHLIST if ticker.strip()]

    # Ensure Golden Sweeps watches the same high-premium names surfaced by scalps
    for ticker in SCALPS_WATCHLIST:
        if ticker not in GOLDEN_SWEEPS_WATCHLIST:
            GOLDEN_SWEEPS_WATCHLIST.append(ticker)
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
    
    # Chart Settings
    CHART_STYLE = os.getenv('CHART_STYLE', 'seaborn-v0_8-darkgrid')
    CHART_DPI = int(os.getenv('CHART_DPI', '100'))
    CHART_WIDTH = int(os.getenv('CHART_WIDTH', '10'))
    CHART_HEIGHT = int(os.getenv('CHART_HEIGHT', '6'))
    CHART_SIZE = (CHART_WIDTH, CHART_HEIGHT)
    
    # Health Check Settings
    HEALTH_CHECK_INTERVAL = int(os.getenv('HEALTH_CHECK_INTERVAL', '60'))  # 1 minute
    HEALTH_CHECK_TIMEOUT = int(os.getenv('HEALTH_CHECK_TIMEOUT', '10'))
    
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
        logger.info(f"  Darkpool: {cls.DARKPOOL_MIN_BLOCK_SIZE:,} shares (Score: {cls.MIN_DARKPOOL_SCORE})")
        logger.info(f"  Sweeps: ${cls.SWEEPS_MIN_PREMIUM:,.0f} (Score: {cls.MIN_SWEEP_SCORE})")
        logger.info(f"  Bullseye: ${cls.BULLSEYE_MIN_PREMIUM:,.0f} (Score: {cls.MIN_BULLSEYE_SCORE})")
        logger.info(f"  Scalps: ${cls.SCALPS_MIN_PREMIUM:,.0f} (Score: {cls.MIN_SCALP_SCORE})")
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
