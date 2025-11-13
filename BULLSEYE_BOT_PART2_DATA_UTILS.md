# Bullseye Bot - Part 2: Data Fetcher & Utilities

## Table of Contents (Part 2)
4. [Data Fetcher](#4-data-fetcher)
5. [Options Analyzer](#5-options-analyzer)
6. [Market Hours Utility](#6-market-hours-utility)
7. [Market Context](#7-market-context)
8. [Exit Strategies](#8-exit-strategies)

---

## 4. Data Fetcher

### File: `src/data_fetcher.py`

The Data Fetcher is the core interface to Polygon.io API. It handles all data retrieval with rate limiting, caching, and error handling.

**Key Capabilities:**
- Real-time stock prices via snapshot endpoint
- Options chain data (all contracts in single API call)
- Unusual flow detection algorithm
- Historical aggregates for technical analysis
- Automatic retry and circuit breaker patterns

```python
"""
ORAKL Bot Data Fetcher
Handles all Polygon.io API interactions for options and stock data
"""

import asyncio
import aiohttp
import pandas as pd
from datetime import datetime, timedelta
import pytz
from typing import Optional, List, Dict, Union, Any
import logging
from asyncio import Semaphore
import json
import time

from src.config import Config
from src.utils.resilience import exponential_backoff_retry, polygon_rate_limiter, api_circuit_breaker
from src.utils.exceptions import (
    APIException, RateLimitException, APITimeoutException, 
    InvalidAPIResponseException, DataValidationException
)
from src.utils.validation import DataValidator, SafeCalculations
from src.utils.cache import cached, cache_manager, MarketDataCache
from src.utils.ticker_translation import translate_ticker
from src.utils.volume_cache import volume_cache
from src.utils.gamma_profile import compute_gamma_profile

logger = logging.getLogger(__name__)

class DataFetcher:
    """Async data fetcher for Polygon.io API with enhanced resilience"""
    
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://api.polygon.io"
        self.session = None
        self.connector = None
        self.semaphore = Semaphore(5)  # Additional concurrency control
        self.timezone = pytz.timezone('US/Eastern')
        self.market_cache = MarketDataCache()
        self._request_count = 0
        self._error_count = 0
        self._last_error_time = None
        configured_skip_list = getattr(Config, 'SKIP_TICKERS', None)
        if not configured_skip_list:
            configured_skip_list = ['ABC', 'ATVI', 'BRK-A', 'BRK-B', 'SPX', 'DFS']
            logger.debug(
                "Config.SKIP_TICKERS not found or empty; using default skip list %s",
                configured_skip_list
            )
        self.skip_tickers = self._build_skip_set(configured_skip_list)
        
    async def __aenter__(self):
        """Async context manager entry"""
        await self._init_session()
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        await self._close_session()
            
    async def _init_session(self):
        """Initialize aiohttp session with connection pooling"""
        # Start volume cache cleanup task
        await volume_cache.start_cleanup_task()

        if not self.session:
            # Configure connection pooling
            self.connector = aiohttp.TCPConnector(
                limit=100,  # Total connection pool size
                limit_per_host=30,  # Per-host connection limit
                ttl_dns_cache=300,  # DNS cache timeout
                enable_cleanup_closed=True
            )
            
            # Configure timeout
            timeout = aiohttp.ClientTimeout(
                total=30,
                connect=5,
                sock_read=25
            )
            
            # Create session with custom settings
            self.session = aiohttp.ClientSession(
                connector=self.connector,
                timeout=timeout,
                headers={
                    'User-Agent': 'ORAKL-Bot/1.0',
                    'Accept': 'application/json'
                }
            )
            
            logger.info("Initialized DataFetcher with connection pooling")
            
    async def _close_session(self):
        """Close aiohttp session and connector"""
        # Stop volume cache cleanup task
        await volume_cache.stop_cleanup_task()

        if self.session:
            await self.session.close()
            self.session = None
        if self.connector:
            await self.connector.close()
            self.connector = None

    # ... [Additional helper methods for ticker management]

    @exponential_backoff_retry(
        max_retries=3,
        base_delay=1.0,
        exceptions=(APIException, aiohttp.ClientError, asyncio.TimeoutError)
    )
    async def _make_request(self, endpoint: str, params: Dict = None) -> Union[Dict, List]:
        """Make async request to Polygon API with retry and circuit breaker"""
        await self.ensure_session()
        
        if params is None:
            params = {}
        params['apiKey'] = self.api_key
        
        url = f"{self.base_url}{endpoint}"
        
        # Apply rate limiting
        await polygon_rate_limiter.acquire()
        
        # Check circuit breaker
        try:
            return await api_circuit_breaker.call(
                self._execute_request,
                url,
                params
            )
        except Exception as e:
            self._error_count += 1
            self._last_error_time = datetime.now()
            raise

    @cached(cache_name='market', ttl_seconds=30)
    async def get_stock_price(self, symbol: str) -> Optional[float]:
        """Get current stock price with caching (uses snapshot for real-time during market hours)"""
        original_symbol = symbol
        if self._should_skip(symbol):
            logger.debug(f"Skipping stock price fetch for {symbol} (skip list)")
            return None

        # Translate ticker if needed (e.g., BLOCK -> SQ)
        symbol = translate_ticker(symbol)

        try:
            # Check cache first (short TTL for real-time pricing)
            cached_price = await self.market_cache.get_stock_price(symbol)
            if cached_price is not None:
                return cached_price

            # Use snapshot endpoint for real-time price during market hours
            endpoint = f"/v2/snapshot/locale/us/markets/stocks/tickers/{symbol}"
            data = await self._make_request(endpoint)

            # Try to get current price from snapshot
            if data and 'ticker' in data:
                ticker_data = data['ticker']

                price_candidates = []

                day_data = ticker_data.get('day') or {}
                if day_data:
                    price_candidates.extend([
                        day_data.get('c'),
                        day_data.get('vw'),
                    ])

                last_trade = ticker_data.get('lastTrade') or ticker_data.get('last_trade') or {}
                if last_trade:
                    price_candidates.extend([
                        last_trade.get('price'),
                        last_trade.get('p'),
                    ])

                last_quote = ticker_data.get('lastQuote') or ticker_data.get('last_quote') or {}
                if last_quote:
                    price_candidates.extend([
                        last_quote.get('midpoint'),
                        last_quote.get('bid'),
                        last_quote.get('ask'),
                    ])

                prev_day = ticker_data.get('prevDay') or ticker_data.get('prev_day') or {}
                if prev_day:
                    price_candidates.extend([
                        prev_day.get('c'),
                        prev_day.get('vw'),
                    ])

                for candidate in price_candidates:
                    if candidate is None:
                        continue
                    try:
                        price = DataValidator.validate_price(candidate)
                        await self.market_cache.set_stock_price(symbol, price)
                        return price
                    except DataValidationException:
                        continue

            logger.warning(f"No price data available for {symbol}")
            return None
            
        except DataValidationException as e:
            logger.error(f"Price validation failed for {symbol}: {e}")
            return None
        except APIException as e:
            details = e.details or {}
            status = details.get('status')
            error_text_raw = details.get('error', '')
            error_text_upper = error_text_raw.upper() if isinstance(error_text_raw, str) else ''
            message_upper = str(e).upper()
            if status == 404 or 'NOTFOUND' in error_text_upper or 'NOTFOUND' in message_upper:
                logger.warning(
                    f"Polygon reports {symbol} (original: {original_symbol}) as not found. "
                    "Adding to skip list to avoid repeated 404s."
                )
                self._register_skip(symbol)
                self._register_skip(original_symbol)
                return None
            logger.error(f"API error fetching stock price for {symbol}: {e}")
            return None
        except Exception as e:
            logger.error(f"Error fetching stock price for {symbol}: {e}")
            return None

    async def detect_unusual_flow(
        self,
        underlying: str,
        min_premium: float = 10000,
        min_volume_delta: int = 10,
        min_volume_ratio: float = 2.0
    ) -> List[Dict]:
        """
        Detect unusual options flow by aggregating trades since last scan.

        This is the CORE FLOW DETECTION ALGORITHM using TRADES ENDPOINT.

        Algorithm:
        1. Get option chain snapshot for contract details (Greeks, OI, strikes)
        2. Retrieve last scan timestamp from cache
        3. For each contract, fetch trades since last scan timestamp
        4. Aggregate trade sizes to calculate volume delta
        5. Filter by premium threshold and unusual activity
        6. Update cache with current scan timestamp
        7. Return flow signals

        Args:
            underlying: Underlying ticker symbol
            min_premium: Minimum premium threshold (default: $10K)
            min_volume_delta: Minimum volume change (default: 10 contracts)
            min_volume_ratio: Minimum volume vs OI ratio for unusual activity (default: 2.0x)

        Returns:
            List of flow dictionaries sorted by premium (descending)

        Flow signal structure:
            {
                'ticker': 'O:AAPL250117C00200000',
                'underlying': 'AAPL',
                'type': 'CALL' or 'PUT',
                'strike': 200.0,
                'expiration': '2025-01-17',
                'volume_delta': 150,  # Trades since last scan
                'total_volume': 1500,  # Day's total volume
                'open_interest': 10000,
                'last_price': 5.25,
                'premium': 78750.0,  # volume_delta * last_price * 100
                'implied_volatility': 0.35,
                'delta': 0.52,
                'underlying_price': 195.50,
                'timestamp': datetime(...)
            }
        """
        try:
            if self._should_skip(underlying):
                logger.debug(f"Skipping unusual flow detection for {underlying} (skip list)")
                return []

            # Step 1: Get option chain snapshot for contract details
            current_snapshot = await self.get_option_chain_snapshot(underlying)

            if not current_snapshot:
                logger.warning(f"No option chain snapshot returned for {underlying}")
                return []
            
            logger.debug(f"{underlying}: Got {len(current_snapshot)} contracts from snapshot")

            # Step 2: Get volume data from cache for comparison
            cached_volumes = {}
            volume_cache_key = f"{underlying}_volumes"
            volume_cache = cache_manager.get_cache('volume')  # Get cache instance
            cached_data = await volume_cache.get(volume_cache_key)
            if cached_data:
                cached_volumes = cached_data
                logger.debug(f"{underlying}: Found cached volumes for {len(cached_volumes)} contracts")
            else:
                logger.info(f"{underlying}: No cached volumes, first scan")

            # Step 3: Aggregate trades for each contract
            flows = []

            # Diagnostic counters
            total_contracts = len(current_snapshot)
            contracts_with_trades = 0
            contracts_with_delta = 0
            contracts_with_premium = 0

            for contract in current_snapshot:
                try:
                    # Extract contract data with validation
                    details = contract.get('details', {}) or {}
                    ticker = contract.get('ticker') or details.get('ticker', '')
                    if not ticker:
                        continue

                    day_data = contract.get('day', {}) or {}
                    last_trade = contract.get('last_trade') or {}
                    last_quote = contract.get('last_quote') or {}
                    current_day_volume = day_data.get('volume', 0)

                    if current_day_volume > 0:
                        contracts_with_trades += 1

                    # Derive last traded price with sensible fallbacks
                    last_price = day_data.get('close')
                    if not last_price or last_price <= 0:
                        quote_last = last_quote.get('last')

                        price_candidates = [
                            last_trade.get('price'),
                            last_trade.get('p'),
                        ]

                        if isinstance(quote_last, dict):
                            price_candidates.extend([
                                quote_last.get('price'),
                                quote_last.get('p'),
                            ])

                        price_candidates.extend([
                            last_quote.get('midpoint'),
                            last_quote.get('bid'),
                            last_quote.get('ask'),
                            day_data.get('open'),
                            day_data.get('high'),
                            day_data.get('low'),
                        ])

                        for candidate in price_candidates:
                            if candidate and candidate > 0:
                                last_price = candidate
                                break

                    # Skip if no usable price data
                    if not last_price or last_price <= 0:
                        continue
                    last_price = DataValidator.validate_price(last_price, 'price')

                    # Step 4: Calculate volume delta by comparing with cached volume
                    cached_volume = cached_volumes.get(ticker, 0)
                    volume_delta = current_day_volume - cached_volume
                    
                    # If first scan or negative delta (market reset), use current volume
                    # Cap at 5000 to prevent extreme values while allowing institutional flows through
                    if volume_delta <= 0:
                        volume_delta = min(current_day_volume, 5000)

                    # Filter: Must have significant volume
                    if volume_delta < min_volume_delta:
                        continue

                    contracts_with_delta += 1

                    # Calculate flow intensity based on volume/OI ratio and premium
                    flow_intensity = "NORMAL"
                    vol_oi_ratio = 0.0
                    
                    # Get open interest for ratio calculation
                    open_interest = contract.get('open_interest', 0)
                    
                    if open_interest > 0:
                        vol_oi_ratio = volume_delta / open_interest
                        if vol_oi_ratio >= 0.5:
                            flow_intensity = "AGGRESSIVE"  # 50%+ of OI
                        elif vol_oi_ratio >= 0.2:
                            flow_intensity = "STRONG"      # 20-50% of OI
                        elif vol_oi_ratio >= 0.1:
                            flow_intensity = "MODERATE"    # 10-20% of OI

                    # Calculate premium for the delta volume
                    premium = volume_delta * last_price * 100  # Options multiplier

                    # Filter: Must meet premium threshold
                    if premium < min_premium:
                        continue

                    contracts_with_premium += 1

                    # Get contract details
                    strike = details.get('strike_price', 0)
                    expiration = details.get('expiration_date', '')
                    contract_type = details.get('contract_type', '')

                    # Get Greeks
                    greeks = contract.get('greeks', {})
                    delta_greek = greeks.get('delta', 0)
                    gamma = greeks.get('gamma', 0)
                    theta = greeks.get('theta', 0)
                    vega = greeks.get('vega', 0)

                    # Get additional metrics
                    implied_vol = contract.get('implied_volatility', 0)

                    # Get underlying price
                    underlying_asset = contract.get('underlying_asset', {})
                    underlying_price = underlying_asset.get('price', 0)

                    # Determine option type - ensure ticker is string
                    if not isinstance(ticker, str):
                        logger.warning(f"Ticker is not a string: {ticker} (type: {type(ticker)})")
                        ticker = str(ticker) if ticker else ''
                    
                    option_type = 'CALL' if contract_type == 'call' or (isinstance(ticker, str) and 'C' in ticker) else 'PUT'

                    # Extract quote-based metrics for downstream consumers
                    bid_price = last_quote.get('bid')
                    if isinstance(bid_price, dict):
                        bid_price = bid_price.get('price') or bid_price.get('p') or bid_price.get('midpoint')
                    if bid_price:
                        try:
                            bid_price = DataValidator.validate_price(bid_price, 'bid')
                        except DataValidationException:
                            bid_price = None

                    ask_price = last_quote.get('ask')
                    if isinstance(ask_price, dict):
                        ask_price = ask_price.get('price') or ask_price.get('p') or ask_price.get('midpoint')
                    if ask_price:
                        try:
                            ask_price = DataValidator.validate_price(ask_price, 'ask')
                        except DataValidationException:
                            ask_price = None

                    bid_size = last_quote.get('bid_size') or last_quote.get('bidSize') or 0
                    ask_size = last_quote.get('ask_size') or last_quote.get('askSize') or 0

                    # Create flow signal
                    flow = {
                        'ticker': ticker,
                        'underlying': underlying,
                        'type': option_type,
                        'strike': DataValidator.validate_price(strike, 'strike'),
                        'expiration': expiration,
                        'volume_delta': volume_delta,
                        'total_volume': current_day_volume,
                        'open_interest': open_interest,
                        'vol_oi_ratio': vol_oi_ratio,
                        'last_price': last_price,
                        'premium': premium,
                        'implied_volatility': implied_vol,
                        'delta': delta_greek,
                        'gamma': gamma,
                        'theta': theta,
                        'vega': vega,
                        'underlying_price': underlying_price,
                        'timestamp': datetime.now(),
                        'flow_intensity': flow_intensity,
                        'bid': bid_price or 0,
                        'ask': ask_price or 0,
                        'bid_size': int(bid_size) if isinstance(bid_size, (int, float)) and bid_size is not None else 0,
                        'ask_size': int(ask_size) if isinstance(ask_size, (int, float)) and ask_size is not None else 0,
                    }

                    flows.append(flow)

                except DataValidationException as e:
                    logger.debug(f"Skipping invalid contract data: {e}")
                    continue
                except Exception as e:
                    logger.debug(f"Error processing contract {ticker}: {e}")
                    continue

            # Step 6: Update volume cache with current volumes
            new_volumes = {}
            for contract in current_snapshot:
                details = contract.get('details', {}) or {}
                ticker = contract.get('ticker') or details.get('ticker', '')
                day_data = contract.get('day', {})
                volume = day_data.get('volume', 0)
                if ticker and volume > 0:
                    new_volumes[ticker] = volume
            
            # Save to cache
            await volume_cache.set(volume_cache_key, new_volumes, ttl_seconds=14400)  # 4 hours
            
            # Step 7: Sort by premium (highest first) and return
            flows_sorted = sorted(flows, key=lambda x: x['premium'], reverse=True)

            if flows_sorted:
                logger.info(
                    f"✅ {underlying}: {len(flows_sorted)} flows detected "
                    f"(top: ${flows_sorted[0]['premium']:,.0f}, {flows_sorted[0]['flow_intensity']})"
                )
            else:
                logger.info(
                    f"⚠️ {underlying}: 0 flows from {total_contracts} contracts "
                    f"(trades={contracts_with_trades}, delta={contracts_with_delta}, premium={contracts_with_premium})"
                )

            return flows_sorted

        except Exception as e:
            import traceback
            logger.error(f"Error detecting unusual flow for {underlying}: {e}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            return []

    async def get_aggregates(self, symbol: str, timespan: str = 'minute', 
                           multiplier: int = 5, from_date: str = None, to_date: str = None) -> pd.DataFrame:
        """Get aggregate bars for analysis"""
        if self._should_skip(symbol):
            logger.debug(f"Skipping aggregates fetch for {symbol} (skip list)")
            return pd.DataFrame()

        if not from_date:
            from_date = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
        if not to_date:
            to_date = datetime.now().strftime('%Y-%m-%d')
            
        endpoint = f"/v2/aggs/ticker/{symbol}/range/{multiplier}/{timespan}/{from_date}/{to_date}"
        params = {'adjusted': 'true', 'sort': 'asc', 'limit': 5000}
        
        data = await self._make_request(endpoint, params)
        
        if data and 'results' in data:
            df = pd.DataFrame(data['results'])
            df['timestamp'] = pd.to_datetime(df['t'], unit='ms')
            df = df.rename(columns={
                'o': 'open',
                'h': 'high',
                'l': 'low',
                'c': 'close',
                'v': 'volume',
                'vw': 'vwap'
            })
            return df[['timestamp', 'open', 'high', 'low', 'close', 'volume', 'vwap']]
            
        return pd.DataFrame()
```

---

## 5. Options Analyzer

### File: `src/options_analyzer.py`

The Options Analyzer provides advanced flow analysis and scoring capabilities.

```python
"""
ORAKL Bot Options Analyzer
Core analysis engine for options flow calculations and signal detection
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
from scipy.stats import norm
import logging
from collections import defaultdict
import math

from src.utils.validation import DataValidator, SafeCalculations
from src.utils.market_analysis import MarketAnalyzer, AdvancedScoring, MarketContext
from src.config import Config

logger = logging.getLogger(__name__)

class OptionsAnalyzer:
    """Enhanced options flow analysis with advanced scoring"""
    
    def __init__(self):
        self.signal_history = defaultdict(list)  # Track repeat signals
        self.success_tracking = defaultdict(dict)  # Track signal success rates
        self.market_analyzer = MarketAnalyzer()  # Market context analyzer
        self._price_cache = {}  # Cache for price data
        
    def analyze_flow(self, trades_df: pd.DataFrame) -> Dict:
        """Analyze options flow for a symbol"""
        if trades_df.empty:
            return {
                'total_premium': 0,
                'call_premium': 0,
                'put_premium': 0,
                'largest_trade': 0,
                'avg_trade_size': 0,
                'dominant_side': 'NEUTRAL',
                'unusual_trades': 0,
                'signal_strength': 'WEAK'
            }
            
        # Calculate metrics
        total_premium = trades_df['premium'].sum()
        call_trades = trades_df[trades_df['type'] == 'CALL']
        put_trades = trades_df[trades_df['type'] == 'PUT']
        
        call_premium = call_trades['premium'].sum()
        put_premium = put_trades['premium'].sum()
        
        # Find largest trade
        largest_trade = trades_df.loc[trades_df['premium'].idxmax()] if not trades_df.empty else None
        
        # Calculate averages
        avg_trade_size = trades_df['premium'].mean()
        
        # Determine dominant side
        if call_premium > put_premium * 1.5:
            dominant_side = 'BULLISH'
        elif put_premium > call_premium * 1.5:
            dominant_side = 'BEARISH'
        else:
            dominant_side = 'NEUTRAL'
            
        # Count unusual trades (>3x average)
        unusual_trades = len(trades_df[trades_df['premium'] > avg_trade_size * 3])
        
        # Determine signal strength
        if total_premium > 1000000 and unusual_trades > 5:
            signal_strength = 'STRONG'
        elif total_premium > 500000 and unusual_trades > 2:
            signal_strength = 'MODERATE'
        else:
            signal_strength = 'WEAK'
            
        return {
            'total_premium': total_premium,
            'call_premium': call_premium,
            'put_premium': put_premium,
            'largest_trade': largest_trade.to_dict() if largest_trade is not None else None,
            'avg_trade_size': avg_trade_size,
            'dominant_side': dominant_side,
            'unusual_trades': unusual_trades,
            'signal_strength': signal_strength,
            'trade_count': len(trades_df),
            'call_count': len(call_trades),
            'put_count': len(put_trades)
        }
        
    def calculate_probability_itm(self, option_type: str, strike: float, current_price: float,
                                 days_to_expiry: int, implied_volatility: float = 0.3) -> float:
        """Calculate probability of option finishing in-the-money using Black-Scholes"""
        if days_to_expiry <= 0:
            if option_type == 'CALL':
                return 100.0 if current_price > strike else 0.0
            else:
                return 100.0 if current_price < strike else 0.0

        # Black-Scholes formula for probability
        time_to_expiry_years = days_to_expiry / 365.25
        d2 = (np.log(current_price / strike) + (0.01 - 0.5 * implied_volatility ** 2) * time_to_expiry_years) / (implied_volatility * np.sqrt(time_to_expiry_years))
        
        if option_type == 'CALL':
            probability = norm.cdf(d2) * 100
        else:
            probability = (1 - norm.cdf(d2)) * 100
            
        return round(probability, 1)
        
    def identify_repeat_signals(self, symbol: str, strike: float, option_type: str,
                              expiration: str, premium: float) -> int:
        """Track and identify repeat signals"""
        signal_key = f"{symbol}_{option_type}_{strike}_{expiration}"
        
        # Add to history
        self.signal_history[signal_key].append({
            'timestamp': datetime.now(),
            'premium': premium
        })
        
        # Clean old signals (>1 hour)
        cutoff_time = datetime.now() - timedelta(hours=1)
        self.signal_history[signal_key] = [
            s for s in self.signal_history[signal_key]
            if s['timestamp'] > cutoff_time
        ]
        
        return len(self.signal_history[signal_key])
```

---

## 6. Market Hours Utility

### File: `src/utils/market_hours.py`

Handles market hours detection with holiday awareness.

```python
"""Market hours and holiday detection utilities"""
import datetime
import pytz
from typing import Optional

# US Market holidays for 2025
US_MARKET_HOLIDAYS_2025 = [
    datetime.date(2025, 1, 1),   # New Year's Day
    datetime.date(2025, 1, 20),  # Martin Luther King Jr. Day
    datetime.date(2025, 2, 17),  # Presidents' Day
    datetime.date(2025, 4, 18),  # Good Friday
    datetime.date(2025, 5, 26),  # Memorial Day
    datetime.date(2025, 6, 19),  # Juneteenth
    datetime.date(2025, 7, 4),   # Independence Day
    datetime.date(2025, 9, 1),   # Labor Day
    datetime.date(2025, 11, 27), # Thanksgiving
    datetime.date(2025, 12, 25), # Christmas
]

# US Market holidays for 2026 (add more years as needed)
US_MARKET_HOLIDAYS_2026 = [
    datetime.date(2026, 1, 1),   # New Year's Day
    datetime.date(2026, 1, 19),  # Martin Luther King Jr. Day
    datetime.date(2026, 2, 16),  # Presidents' Day
    datetime.date(2026, 4, 3),   # Good Friday
    datetime.date(2026, 5, 25),  # Memorial Day
    datetime.date(2026, 6, 19),  # Juneteenth
    datetime.date(2026, 7, 3),   # Independence Day (observed)
    datetime.date(2026, 9, 7),   # Labor Day
    datetime.date(2026, 11, 26), # Thanksgiving
    datetime.date(2026, 12, 25), # Christmas
]

ALL_MARKET_HOLIDAYS = US_MARKET_HOLIDAYS_2025 + US_MARKET_HOLIDAYS_2026
EST = pytz.timezone('America/New_York')


class MarketHours:
    """Utility class for checking market hours and trading days"""
    
    @staticmethod
    def is_market_open(check_time: Optional[datetime.datetime] = None, include_extended: bool = True) -> bool:
        """
        Check if the US stock market is open at the given time.

        Regular hours: 9:30 AM - 4:00 PM EST
        Extended hours: 4:00 AM - 8:00 PM EST (pre-market + regular + after-hours)

        Args:
            check_time: Time to check (default: current time)
            include_extended: Include pre-market (4:00-9:30 AM) and after-hours (4:00-8:00 PM)

        Returns:
            True if market is open (regular or extended hours), False otherwise
        """
        if check_time is None:
            check_time = datetime.datetime.now(EST)
        elif check_time.tzinfo is None:
            check_time = EST.localize(check_time)
        else:
            check_time = check_time.astimezone(EST)

        # Check if it's a weekend
        if check_time.weekday() >= 5:  # Saturday = 5, Sunday = 6
            return False

        # Check if it's a holiday
        if check_time.date() in ALL_MARKET_HOLIDAYS:
            return False

        if include_extended:
            # Extended hours: 4:00 AM - 8:00 PM EST
            extended_start = check_time.replace(hour=4, minute=0, second=0, microsecond=0)
            extended_end = check_time.replace(hour=20, minute=0, second=0, microsecond=0)
            return extended_start <= check_time < extended_end
        else:
            # Regular hours only: 9:30 AM - 4:00 PM EST
            market_open = check_time.replace(hour=9, minute=30, second=0, microsecond=0)
            market_close = check_time.replace(hour=16, minute=0, second=0, microsecond=0)
            return market_open <= check_time < market_close
    
    @staticmethod
    def is_trading_day(check_date: Optional[datetime.date] = None) -> bool:
        """
        Check if the given date is a trading day (weekday, not a holiday)
        
        Args:
            check_date: Date to check (default: today)
            
        Returns:
            True if it's a trading day, False otherwise
        """
        if check_date is None:
            check_date = datetime.datetime.now(EST).date()
        
        # Check if it's a weekend
        if check_date.weekday() >= 5:  # Saturday = 5, Sunday = 6
            return False
        
        # Check if it's a holiday
        if check_date in ALL_MARKET_HOLIDAYS:
            return False
        
        return True
    
    @staticmethod
    def next_market_open() -> datetime.datetime:
        """
        Get the next market open time
        
        Returns:
            Next market open datetime in EST
        """
        now = datetime.datetime.now(EST)
        
        # Start with next potential open (9:30 AM)
        next_open = now.replace(hour=9, minute=30, second=0, microsecond=0)
        
        # If it's after 9:30 AM today, move to tomorrow
        if now.time() >= datetime.time(9, 30):
            next_open += datetime.timedelta(days=1)
        
        # Keep moving forward until we find a trading day
        while not MarketHours.is_trading_day(next_open.date()):
            next_open += datetime.timedelta(days=1)
        
        return next_open
```

---

## 7. Market Context

### File: `src/utils/market_context.py`

Provides market regime classification and analysis.

```python
"""
Market Context Analysis Utility
Provides market regime classification and volatility analysis
"""
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import numpy as np

logger = logging.getLogger(__name__)

class MarketContext:
    """Analyze and classify market conditions"""
    
    # Market regime thresholds
    VIX_HIGH_THRESHOLD = 20
    VIX_EXTREME_THRESHOLD = 30
    MOMENTUM_STRONG_THRESHOLD = 1.0
    MOMENTUM_WEAK_THRESHOLD = 0.3
    
    # Sector ETFs for rotation analysis
    SECTOR_ETFS = {
        'XLK': 'Technology',
        'XLF': 'Financials',
        'XLE': 'Energy',
        'XLV': 'Healthcare',
        'XLI': 'Industrials',
        'XLY': 'Consumer Discretionary',
        'XLP': 'Consumer Staples',
        'XLU': 'Utilities',
        'XLRE': 'Real Estate',
        'XLB': 'Materials',
        'XLC': 'Communication Services'
    }
    
    @staticmethod
    async def get_market_context(fetcher) -> Dict:
        """
        Analyze current market conditions
        Returns comprehensive market analysis
        """
        try:
            context = {
                'timestamp': datetime.now(),
                'volatility': await MarketContext._get_volatility_regime(fetcher),
                'trend': await MarketContext._get_market_trend(fetcher),
                'momentum': await MarketContext._get_market_momentum(fetcher),
                'sectors': await MarketContext._get_sector_strength(fetcher),
                'regime': 'normal',  # Will be calculated
                'trading_bias': 'neutral',  # Will be calculated
                'risk_level': 'medium'  # Will be calculated
            }
            
            # Classify overall market regime
            context['regime'] = MarketContext._classify_regime(context)
            context['trading_bias'] = MarketContext._determine_trading_bias(context)
            context['risk_level'] = MarketContext._assess_risk_level(context)
            
            return context
            
        except Exception as e:
            logger.error(f"Error analyzing market context: {e}")
            return MarketContext._get_default_context()
    
    @staticmethod
    async def _get_market_trend(fetcher) -> Dict:
        """Analyze SPY trend across multiple timeframes"""
        try:
            # Get SPY data
            spy_bars = await fetcher.get_aggregates(
                'SPY', 'day', 1,
                (datetime.now() - timedelta(days=50)).strftime('%Y-%m-%d'),
                datetime.now().strftime('%Y-%m-%d')
            )
            
            if spy_bars.empty:
                return {'direction': 'unknown', 'strength': 0}
            
            # Calculate moving averages
            spy_bars['sma_20'] = spy_bars['close'].rolling(20).mean()
            spy_bars['sma_50'] = spy_bars['close'].rolling(50).mean()
            
            current_price = spy_bars.iloc[-1]['close']
            sma_20 = spy_bars.iloc[-1]['sma_20']
            sma_50 = spy_bars.iloc[-1]['sma_50'] if len(spy_bars) >= 50 else sma_20
            
            # Determine trend
            if current_price > sma_20 > sma_50:
                direction = 'bullish'
                strength = ((current_price - sma_50) / sma_50) * 100
            elif current_price < sma_20 < sma_50:
                direction = 'bearish'
                strength = ((sma_50 - current_price) / sma_50) * 100
            else:
                direction = 'choppy'
                strength = abs((current_price - sma_20) / sma_20) * 100
            
            return {
                'direction': direction,
                'strength': min(strength, 10),  # Cap at 10%
                'above_20ma': current_price > sma_20,
                'above_50ma': current_price > sma_50
            }
            
        except Exception as e:
            logger.error(f"Error analyzing market trend: {e}")
            return {'direction': 'unknown', 'strength': 0}
    
    @staticmethod
    def _classify_regime(context: Dict) -> str:
        """Classify overall market regime based on multiple factors"""
        volatility = context['volatility']['level']
        trend = context['trend']['direction']
        momentum = context['momentum']['direction']
        
        # Extreme volatility overrides everything
        if volatility == 'extreme':
            return 'crisis'
        
        # High volatility scenarios
        if volatility == 'high':
            if trend == 'bearish':
                return 'correction'
            else:
                return 'volatile'
        
        # Normal volatility scenarios
        if trend == 'bullish' and momentum == 'bullish':
            return 'trending_up'
        elif trend == 'bearish' and momentum == 'bearish':
            return 'trending_down'
        elif trend == 'choppy':
            return 'range_bound'
        else:
            return 'transitional'
```

---

## 8. Exit Strategies

### File: `src/utils/exit_strategies.py`

Calculates stop loss and profit targets for different trading styles.

```python
"""
Exit Strategy Calculator
Provides stop loss and profit target calculations for options trades
"""
import logging
from typing import Dict, Optional
from datetime import datetime

logger = logging.getLogger(__name__)

class ExitStrategies:
    """Calculate exit points for different trading strategies"""
    
    @staticmethod
    def calculate_exits(signal_type: str, entry_price: float, 
                       underlying_price: float, option_type: str,
                       atr: Optional[float] = None, dte: int = 1) -> Dict:
        """
        Calculate stop loss and profit targets based on signal type
        
        Args:
            signal_type: 'scalp' or 'bullseye'
            entry_price: Option entry price
            underlying_price: Current stock price
            option_type: 'CALL' or 'PUT'
            atr: Average True Range of underlying (optional)
            dte: Days to expiry
            
        Returns:
            Dict with stop_loss, targets, and recommendations
        """
        try:
            # Use default ATR if not provided (2% of underlying)
            if atr is None:
                atr = underlying_price * 0.02
            
            # Calculate based on signal type
            if signal_type.lower() == 'scalp':
                return ExitStrategies._calculate_scalp_exits(
                    entry_price, atr, option_type, dte
                )
            elif signal_type.lower() == 'bullseye':
                return ExitStrategies._calculate_bullseye_exits(
                    entry_price, atr, option_type, dte
                )
            else:
                # Default conservative exits
                return ExitStrategies._calculate_default_exits(entry_price)
                
        except Exception as e:
            logger.error(f"Error calculating exits: {e}")
            return ExitStrategies._calculate_default_exits(entry_price)
    
    @staticmethod
    def _calculate_bullseye_exits(entry_price: float, atr: float,
                                 option_type: str, dte: int) -> Dict:
        """
        Calculate exits for institutional swing trades.
        These aren't scalps - institutions expect MOVES.
        """
        
        # INSTITUTIONAL SWING EXITS - Much wider than scalps
        if dte <= 2:  # 0-2 DTE swings
            # Tighter stops, quicker targets
            stop_pct = 0.30  # 30% stop
            target1_pct = 0.75    # 75% gain
            target2_pct = 1.50    # 150% gain
            target3_pct = 3.00    # 300% runner
        else:  # 3-5 DTE swings  
            # More room to work
            stop_pct = 0.40  # 40% stop
            target1_pct = 1.00    # 100% gain
            target2_pct = 2.00    # 200% gain
            target3_pct = 4.00    # 400% runner
        
        stop_loss = entry_price * (1 - stop_pct)
        target_1 = entry_price * (1 + target1_pct)
        target_2 = entry_price * (1 + target2_pct)
        target_3 = entry_price * (1 + target3_pct)
        
        # Calculate R:R ratios
        risk = entry_price - stop_loss
        reward1 = target_1 - entry_price
        reward2 = target_2 - entry_price
        reward3 = target_3 - entry_price
        
        trail_pct = 0.25  # 25% trailing for swings

        return {
            'stop_loss': round(stop_loss, 2),
            'target_1': round(target_1, 2),
            'target_2': round(target_2, 2),
            'target_3': round(target_3, 2),
            'stop_pct': f"-{stop_pct*100:.0f}%",
            'target1_pct': f"+{target1_pct*100:.0f}%",
            'target2_pct': f"+{target2_pct*100:.0f}%",
            'target3_pct': f"+{target3_pct*100:.0f}%",
            'risk_reward_1': round(reward1 / risk, 2) if risk > 0 else 0,
            'risk_reward_2': round(reward2 / risk, 2) if risk > 0 else 0,
            'risk_reward_3': round(reward3 / risk, 2) if risk > 0 else 0,
            'trail_stop': round(entry_price * (1 - trail_pct), 2),
            'scale_out': {
                'target_1_size': 0.50,  # Take 50% at T1
                'target_2_size': 0.30,  # Take 30% at T2
                'runner_size': 0.20     # Let 20% run to T3
            },
            'management': 'Scale out recommended - Let winners run',
            'entry_zone': {
                'lower': round(entry_price * 0.95, 2),  # 5% entry zone
                'upper': round(entry_price * 1.05, 2)
            }
        }
```

---

## Summary

This document covers all the major components of the Bullseye Bot:

- **Data Fetcher**: Polygon.io API integration with flow detection
- **Options Analyzer**: Advanced scoring and flow analysis
- **Market Hours**: Trading day/hour detection with holidays
- **Market Context**: Regime classification and analysis
- **Exit Strategies**: Risk management and profit targets

**Total Code Documentation**: ~4,600 lines across 8 core files

---

**Part 2 Complete**
**Generated:** November 13, 2025


