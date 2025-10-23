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

from src.utils.resilience import exponential_backoff_retry, polygon_rate_limiter, api_circuit_breaker
from src.utils.exceptions import (
    APIException, RateLimitException, APITimeoutException, 
    InvalidAPIResponseException, DataValidationException
)
from src.utils.validation import DataValidator, SafeCalculations
from src.utils.cache import cached, cache_manager, MarketDataCache
from src.utils.ticker_translation import translate_ticker
from src.utils.volume_cache import volume_cache

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
            
    async def ensure_session(self):
        """Ensure aiohttp session exists"""
        if not self.session:
            await self._init_session()
            
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
    
    async def _execute_request(self, url: str, params: Dict) -> Union[Dict, List]:
        """Execute the actual HTTP request"""
        async with self.semaphore:
            try:
                self._request_count += 1
                
                async with self.session.get(url, params=params) as response:
                    # Handle rate limiting
                    if response.status == 429:
                        retry_after = int(response.headers.get('Retry-After', 60))
                        raise RateLimitException(
                            f"Rate limit exceeded. Retry after {retry_after} seconds",
                            retry_after
                        )
                    
                    # Handle successful response
                    if response.status == 200:
                        data = await response.json()
                        
                        # Validate response structure
                        if data is None:
                            raise InvalidAPIResponseException(
                                "Received null response from API",
                                None
                            )
                        
                        return data
                    
                    # Handle client errors
                    elif 400 <= response.status < 500:
                        error_text = await response.text()
                        raise APIException(
                            f"Client error: {response.status} - {error_text}",
                            {'status': response.status, 'error': error_text}
                        )
                    
                    # Handle server errors
                    else:
                        error_text = await response.text()
                        raise APIException(
                            f"Server error: {response.status} - {error_text}",
                            {'status': response.status, 'error': error_text}
                        )
                        
            except asyncio.TimeoutError:
                raise APITimeoutException(
                    f"Request timeout for {url}",
                    timeout=30
                )
            except aiohttp.ClientError as e:
                raise APIException(
                    f"Network error: {str(e)}",
                    {'error_type': type(e).__name__}
                )
                
    @cached(cache_name='market', ttl_seconds=30)
    async def get_stock_price(self, symbol: str) -> Optional[float]:
        """Get current stock price with caching"""
        # Translate ticker if needed (e.g., BLOCK -> SQ)
        symbol = translate_ticker(symbol)
        
        try:
            # Check cache first
            cached_price = await self.market_cache.get_stock_price(symbol)
            if cached_price is not None:
                return cached_price
            
            endpoint = f"/v2/aggs/ticker/{symbol}/prev"
            data = await self._make_request(endpoint)
            
            if data and 'results' in data and len(data['results']) > 0:
                price = DataValidator.validate_price(data['results'][0]['c'])
                
                # Cache the price
                await self.market_cache.set_stock_price(symbol, price)
                
                return price
            
            logger.warning(f"No price data available for {symbol}")
            return None
            
        except DataValidationException as e:
            logger.error(f"Price validation failed for {symbol}: {e}")
            return None
        except Exception as e:
            logger.error(f"Error fetching stock price for {symbol}: {e}")
            return None
        
    @cached(cache_name='financials', ttl_seconds=43200)  # Cache for 12 hours
    async def get_financials(self, symbol: str) -> Optional[Dict[str, float]]:
        """Get key financials for a stock, like 52-week high/low from daily aggregates"""
        # Translate ticker if needed
        symbol = translate_ticker(symbol)
        
        try:
            cached_financials = await self.market_cache.get_financials(symbol)
            if cached_financials:
                return cached_financials

            # Get 52-week data from daily aggregates (last 365 days)
            to_date = datetime.now().strftime('%Y-%m-%d')
            from_date = (datetime.now() - timedelta(days=365)).strftime('%Y-%m-%d')
            
            endpoint = f"/v2/aggs/ticker/{symbol}/range/1/day/{from_date}/{to_date}"
            params = {'adjusted': 'true', 'sort': 'desc', 'limit': 365}
            data = await self._make_request(endpoint, params)

            if data and 'results' in data and len(data['results']) > 0:
                bars = data['results']
                # Calculate 52-week high/low from the bars
                highs = [bar['h'] for bar in bars if 'h' in bar]
                lows = [bar['l'] for bar in bars if 'l' in bar]
                
                if highs and lows:
                    financials = {
                        '52_week_high': max(highs),
                        '52_week_low': min(lows),
                    }
                    
                    # Cache and return
                    await self.market_cache.set_financials(symbol, financials)
                    return financials
            
            # Return None silently - no warning needed
            return None
        except Exception as e:
            # Only log error if it's not a 404 (ticker not found)
            if "404" not in str(e) and "NOT_FOUND" not in str(e):
                logger.error(f"Error fetching financials for {symbol}: {e}")
            return None

    @cached(cache_name='volume', ttl_seconds=14400)  # Cache for 4 hours
    async def get_30_day_avg_volume(self, symbol: str) -> Optional[float]:
        """Get 30-day average trading volume"""
        try:
            cached_volume = await self.market_cache.get_avg_volume(symbol)
            if cached_volume:
                return cached_volume

            to_date = datetime.now().strftime('%Y-%m-%d')
            from_date = (datetime.now() - timedelta(days=45)).strftime('%Y-%m-%d')
            
            endpoint = f"/v2/aggs/ticker/{symbol}/range/1/day/{from_date}/{to_date}"
            params = {'adjusted': 'true', 'sort': 'desc', 'limit': 30}
            
            data = await self._make_request(endpoint, params)

            if data and 'results' in data and len(data['results']) >= 20: # Ensure enough data
                volumes = [bar.get('v', 0) for bar in data['results']]
                avg_volume = sum(volumes) / len(volumes)
                
                await self.market_cache.set_avg_volume(symbol, avg_volume)
                return avg_volume

            logger.warning(f"Not enough daily volume data to calculate average for {symbol}")
            return None
        except Exception as e:
            logger.error(f"Error fetching 30-day avg volume for {symbol}: {e}")
            return None
        
    async def get_options_chain(self, symbol: str, expiration_date: Optional[str] = None, 
                              expiration_date_gte: Optional[str] = None,
                              expiration_date_lte: Optional[str] = None) -> pd.DataFrame:
        """Get options chain for a symbol"""
        params = {
            'underlying_ticker': symbol,
            'limit': 1000,
            'sort': 'expiration_date'
        }
        
        if expiration_date:
            params['expiration_date'] = expiration_date
        if expiration_date_gte:
            params['expiration_date.gte'] = expiration_date_gte
        if expiration_date_lte:
            params['expiration_date.lte'] = expiration_date_lte
            
        endpoint = "/v3/reference/options/contracts"
        data = await self._make_request(endpoint, params)
        
        if data and 'results' in data:
            df = pd.DataFrame(data['results'])
            return df
        return pd.DataFrame()
        
    async def get_stock_trades(self, symbol: str, limit: int = 1000) -> List[Dict]:
        """Get recent stock trades for block detection"""
        # Translate ticker if needed
        symbol = translate_ticker(symbol)
        
        endpoint = f"/v3/trades/{symbol}"
        params = {
            'limit': limit,
            'sort': 'timestamp',
            'order': 'desc'
        }

        data = await self._make_request(endpoint, params)

        if data and 'results' in data:
            return data['results']
        return []

    async def get_stock_trades_range(self, symbol: str, start_date: str, end_date: str) -> List[Dict]:
        """Get stock trades for a specific date range (for darkpool analysis)"""
        try:
            # Polygon API: /v3/trades/{ticker}?timestamp.gte={start}&timestamp.lte={end}
            from datetime import datetime
            import time

            # Convert dates to timestamps (milliseconds)
            start_ts = int(datetime.strptime(start_date, '%Y-%m-%d').timestamp() * 1000)
            end_ts = int(datetime.strptime(end_date, '%Y-%m-%d').timestamp() * 1000)

            endpoint = f"/v3/trades/{symbol}"
            params = {
                'timestamp.gte': start_ts,
                'timestamp.lte': end_ts,
                'limit': 50000,  # Max for 1 week
                'sort': 'timestamp',
                'order': 'desc'
            }

            data = await self._make_request(endpoint, params)

            if data and 'results' in data:
                return data['results']
            return []

        except Exception as e:
            logger.error(f"Error fetching stock trades range for {symbol}: {e}")
            return []

    async def get_options_trades(self, symbol: str, date: Optional[str] = None) -> pd.DataFrame:
        """Get options trades for a symbol with concurrent fetching"""
        try:
            if not date:
                date = datetime.now().strftime('%Y-%m-%d')
            
            # Get options contracts first
            contracts = await self.get_options_chain(symbol)
            if contracts.empty:
                return pd.DataFrame()
            
            # Select most active contracts based on available data
            # Try volume first, fall back to other fields if not available
            if 'volume' in contracts.columns and contracts['volume'].notna().any():
                active_contracts = contracts.nlargest(20, 'volume', keep='all').head(30)
            elif 'open_interest' in contracts.columns and contracts['open_interest'].notna().any():
                active_contracts = contracts.nlargest(20, 'open_interest', keep='all').head(30)
            else:
                # Just take first 20 if no volume/OI data
                active_contracts = contracts.head(20)
            
            # Fetch trades concurrently for better performance
            tasks = []
            for _, contract in active_contracts.iterrows():
                ticker = contract.get('ticker', '')
                if ticker:
                    task = self._fetch_contract_trades(
                        symbol, ticker, contract, date
                    )
                    tasks.append(task)
            
            # Wait for all trades with timeout
            try:
                results = await asyncio.gather(*tasks, return_exceptions=True)
            except asyncio.TimeoutError:
                logger.warning(f"Timeout fetching options trades for {symbol}")
                results = []
            
            # Combine results
            all_trades = []
            for result in results:
                if isinstance(result, list):
                    all_trades.extend(result)
                elif isinstance(result, Exception):
                    logger.debug(f"Error in trade fetch: {result}")
            
            if not all_trades:
                return pd.DataFrame()
            
            # Create DataFrame with validation
            df = pd.DataFrame(all_trades)
            df = DataValidator.validate_dataframe(
                df,
                required_columns=['symbol', 'contract', 'type', 'strike', 'expiration', 
                                'timestamp', 'price', 'volume', 'premium'],
                min_rows=0
            )
            
            # Filter for significant trades
            if not df.empty:
                df = df[df['premium'] >= 1000]  # Min $1000 premium
                df = df.sort_values('timestamp', ascending=False)
                
                # Remove duplicates
                df = df.drop_duplicates(
                    subset=['contract', 'timestamp', 'volume'],
                    keep='first'
                )
            
            return df
            
        except Exception as e:
            logger.error(f"Error fetching options trades for {symbol}: {e}")
            return pd.DataFrame()
    
    @cached(cache_name='market', ttl_seconds=60)
    async def _fetch_contract_trades(
        self, symbol: str, ticker: str, contract: pd.Series, date: str
    ) -> List[Dict]:
        """Fetch trades for a single contract"""
        try:
            endpoint = f"/v2/aggs/ticker/{ticker}/range/1/minute/{date}/{date}"
            params = {'adjusted': 'true', 'sort': 'desc', 'limit': 5000}
            
            data = await self._make_request(endpoint, params)
            
            trades = []
            if data and 'results' in data:
                for bar in data['results']:
                    try:
                        # Validate bar data
                        if bar.get('v', 0) > 0 and bar.get('c', 0) > 0:
                            trade = {
                                'symbol': symbol,
                                'contract': ticker,
                                'type': 'CALL' if (isinstance(ticker, str) and 'C' in ticker) else 'PUT',
                                'strike': DataValidator.validate_price(
                                    contract.get('strike_price', 0), 'strike'
                                ),
                                'expiration': contract.get('expiration_date', ''),
                                'timestamp': datetime.fromtimestamp(bar['t'] / 1000),
                                'price': DataValidator.validate_price(bar['c'], 'price'),
                                'volume': DataValidator.validate_volume(bar['v']),
                                'vwap': bar.get('vw', bar['c']),
                                'size': bar['v'],
                                'premium': bar['v'] * bar['c'] * 100  # Contract multiplier
                            }
                            trades.append(trade)
                    except DataValidationException as e:
                        logger.debug(f"Skipping invalid trade data: {e}")
                        continue
            
            return trades
            
        except Exception as e:
            logger.debug(f"Error fetching trades for {ticker}: {e}")
            return []
        
    async def get_options_snapshot(self, symbol: str) -> Dict:
        """Get current options snapshot"""
        # Get underlying price first
        underlying_price = await self.get_stock_price(symbol)
        
        # Get options chain
        contracts = await self.get_options_chain(symbol)
        
        if contracts.empty:
            return {}
            
        # Calculate metrics
        total_call_volume = 0
        total_put_volume = 0
        total_call_oi = 0
        total_put_oi = 0
        
        # Get snapshot for each contract
        for _, contract in contracts.head(50).iterrows():
            ticker = contract.get('ticker', '')
            if not ticker:
                continue
                
            endpoint = f"/v2/snapshot/options/contracts/{ticker}"
            data = await self._make_request(endpoint)
            
            if data and 'results' in data:
                result = data['results']
                volume = result.get('day', {}).get('volume', 0)
                oi = result.get('open_interest', 0)
                
                if isinstance(ticker, str) and 'C' in ticker:
                    total_call_volume += volume
                    total_call_oi += oi
                else:
                    total_put_volume += volume
                    total_put_oi += oi
                    
        return {
            'symbol': symbol,
            'underlying_price': underlying_price,
            'total_call_volume': total_call_volume,
            'total_put_volume': total_put_volume,
            'total_call_oi': total_call_oi,
            'total_put_oi': total_put_oi,
            'put_call_ratio': total_put_volume / max(total_call_volume, 1),
            'timestamp': datetime.now()
        }
        
    async def get_unusual_options(self, min_volume: int = 100, min_premium: float = 10000) -> List[Dict]:
        """Scan for unusual options activity across all symbols"""
        endpoint = "/v2/snapshot/options/contracts"
        params = {
            'order': 'desc',
            'sort': 'volume',
            'limit': 100
        }
        
        data = await self._make_request(endpoint, params)
        
        unusual = []
        if data and 'results' in data:
            for option in data['results']:
                volume = option.get('day', {}).get('volume', 0)
                oi = option.get('open_interest', 0)
                last_price = option.get('day', {}).get('close', 0)
                
                # Calculate premium
                premium = volume * last_price * 100
                
                # Check for unusual activity
                if volume >= min_volume and premium >= min_premium:
                    if oi > 0 and volume > oi * 2:  # Volume > 2x OI
                        vol_oi_ratio = volume / oi
                    else:
                        vol_oi_ratio = 0
                        
                    unusual.append({
                        'ticker': option.get('ticker', ''),
                        'underlying': option.get('underlying_ticker', ''),
                        'type': 'CALL' if 'C' in option.get('ticker', '') else 'PUT',
                        'strike': option.get('details', {}).get('strike_price', 0),
                        'expiration': option.get('details', {}).get('expiration_date', ''),
                        'volume': volume,
                        'open_interest': oi,
                        'vol_oi_ratio': vol_oi_ratio,
                        'last_price': last_price,
                        'premium': premium,
                        'implied_volatility': option.get('implied_volatility', 0),
                        'delta': option.get('greeks', {}).get('delta', 0),
                        'gamma': option.get('greeks', {}).get('gamma', 0),
                        'timestamp': datetime.now()
                    })
                    
        return sorted(unusual, key=lambda x: x['premium'], reverse=True)

    async def get_option_chain_snapshot(
        self,
        underlying: str,
        contract_type: Optional[str] = None
    ) -> List[Dict]:
        """
        Get complete snapshot of all options contracts for an underlying ticker.

        This is the PRIMARY METHOD for efficient options flow detection.

        Endpoint: /v3/snapshot/options/{underlyingAsset}

        Benefits:
        - Returns ALL contracts in ONE API call (vs 50+ individual calls)
        - Includes: volume, OI, last price, Greeks, bid/ask for each contract
        - Perfect for flow detection via volume delta comparison

        Args:
            underlying: Underlying ticker symbol (e.g., 'AAPL', 'SPY')
            contract_type: Filter by 'call' or 'put', None for both

        Returns:
            List of contract dictionaries with complete market data

        Example response per contract:
            {
                'ticker': 'O:AAPL250117C00200000',
                'day': {'volume': 1500, 'close': 5.25, 'open': 5.10, ...},
                'open_interest': 10000,
                'implied_volatility': 0.35,
                'greeks': {'delta': 0.52, 'gamma': 0.03, ...},
                'details': {'strike_price': 200.0, 'expiration_date': '2025-01-17', ...},
                'underlying_asset': {'ticker': 'AAPL', 'price': 195.50, ...}
            }
        """
        try:
            endpoint = f"/v3/snapshot/options/{underlying}"
            params = {
                'limit': 250  # Get up to 250 contracts per request (Polygon API max)
            }

            if contract_type:
                # Filter by contract type if specified
                params['contract_type'] = contract_type.lower()

            data = await self._make_request(endpoint, params)

            if data and 'results' in data and len(data['results']) > 0:
                logger.debug(
                    f"Retrieved option chain snapshot for {underlying}: "
                    f"{len(data['results'])} contracts"
                )
                return data['results']

            logger.debug(f"No option contracts found for {underlying}")
            return []

        except Exception as e:
            logger.error(f"Error fetching option chain snapshot for {underlying}: {e}")
            return []

    async def get_option_trades(
        self,
        option_ticker: str,
        timestamp_gte: Optional[int] = None,
        limit: int = 50000
    ) -> List[Dict]:
        """
        Get trade history for a specific option contract.

        Endpoint: /v3/trades/{optionsTicker}

        Args:
            option_ticker: Option ticker (e.g., 'O:AAPL250117C00200000')
            timestamp_gte: Nanosecond timestamp - only get trades >= this time
            limit: Max trades to return (default/max: 50000)

        Returns:
            List of trade dictionaries with structure:
            {
                'sip_timestamp': 1623456789000000000,  # Nanosecond timestamp
                'participant_timestamp': 1623456788999000000,
                'price': 5.25,  # Trade price
                'size': 10,     # Trade size (volume)
                'exchange': 11,
                'conditions': [1, 2],
                'correction': 0
            }
        """
        try:
            endpoint = f"/v3/trades/{option_ticker}"
            params = {'limit': limit}

            if timestamp_gte:
                params['timestamp.gte'] = timestamp_gte

            data = await self._make_request(endpoint, params)

            # Defensive check: ensure data is a dict before checking for 'results'
            if data and isinstance(data, dict) and 'results' in data:
                return data.get('results', [])

            return []

        except Exception as e:
            logger.debug(f"Error fetching trades for {option_ticker}: {e}")
            return []

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
            # Step 1: Get option chain snapshot for contract details
            current_snapshot = await self.get_option_chain_snapshot(underlying)

            if not current_snapshot:
                logger.debug(f"No contracts found for {underlying}")
                return []

            # Step 2: Get last scan timestamp from cache
            cache_data = await volume_cache.get(underlying)
            last_scan_timestamp_ns = None  # Nanoseconds

            # Handle cache format - be defensive about old cache data
            if cache_data is not None and isinstance(cache_data, dict):
                # New format: {'last_scan_ns': timestamp}
                last_scan_timestamp_ns = cache_data.get('last_scan_ns')

                # If old format (per-contract dict with ticker keys), treat as first scan
                if last_scan_timestamp_ns is None:
                    logger.info(f"🔄 {underlying}: Detected old cache format, treating as first scan")

            # Current timestamp in nanoseconds
            current_timestamp_ns = int(datetime.now().timestamp() * 1_000_000_000)

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
                    ticker = contract.get('ticker', '')
                    if not ticker:
                        continue

                    # Get contract details for pricing
                    day_data = contract.get('day', {})
                    last_price = day_data.get('close', 0)
                    current_day_volume = day_data.get('volume', 0)

                    # Skip if no price data
                    if last_price == 0:
                        continue

                    # Step 4: Fetch trades since last scan
                    trades = await self.get_option_trades(
                        option_ticker=ticker,
                        timestamp_gte=last_scan_timestamp_ns,
                        limit=50000
                    )

                    if not trades:
                        continue  # No trades since last scan

                    contracts_with_trades += 1

                    # Step 5: Aggregate trade sizes to get volume delta
                    volume_delta = sum(trade.get('size', 0) for trade in trades)

                    # Filter: Must have significant volume
                    if volume_delta < min_volume_delta:
                        continue

                    contracts_with_delta += 1

                    # Calculate time elapsed for velocity
                    time_elapsed_minutes = 0
                    volume_velocity = 0
                    flow_intensity = "NORMAL"

                    if last_scan_timestamp_ns:
                        time_elapsed_seconds = (current_timestamp_ns - last_scan_timestamp_ns) / 1_000_000_000
                        time_elapsed_minutes = max(time_elapsed_seconds / 60, 0.1)
                        volume_velocity = volume_delta / time_elapsed_minutes

                        # Classify flow intensity
                        if volume_velocity >= 50:
                            flow_intensity = "AGGRESSIVE"  # 50+ contracts/min
                        elif volume_velocity >= 20:
                            flow_intensity = "STRONG"      # 20-50 contracts/min
                        elif volume_velocity >= 10:
                            flow_intensity = "MODERATE"    # 10-20 contracts/min

                    # Calculate premium for the delta volume
                    premium = volume_delta * last_price * 100  # Options multiplier

                    # Filter: Must meet premium threshold
                    if premium < min_premium:
                        continue

                    contracts_with_premium += 1

                    # Get contract details
                    details = contract.get('details', {})
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
                    open_interest = contract.get('open_interest', 0)
                    implied_vol = contract.get('implied_volatility', 0)

                    # Get underlying price
                    underlying_asset = contract.get('underlying_asset', {})
                    underlying_price = underlying_asset.get('price', 0)

                    # Calculate volume/OI ratio
                    vol_oi_ratio = 0
                    if open_interest > 0:
                        vol_oi_ratio = volume_delta / open_interest

                    # Determine option type - ensure ticker is string
                    if not isinstance(ticker, str):
                        logger.warning(f"Ticker is not a string: {ticker} (type: {type(ticker)})")
                        ticker = str(ticker) if ticker else ''
                    
                    option_type = 'CALL' if contract_type == 'call' or (isinstance(ticker, str) and 'C' in ticker) else 'PUT'

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
                        'last_price': DataValidator.validate_price(last_price, 'price'),
                        'premium': premium,
                        'implied_volatility': implied_vol,
                        'delta': delta_greek,
                        'gamma': gamma,
                        'theta': theta,
                        'vega': vega,
                        'underlying_price': underlying_price,
                        'timestamp': datetime.now(),
                        'volume_velocity': volume_velocity,
                        'flow_intensity': flow_intensity,
                        'time_elapsed_minutes': time_elapsed_minutes,
                        'num_trades': len(trades)  # NEW: Number of individual trades
                    }

                    flows.append(flow)

                except DataValidationException as e:
                    logger.debug(f"Skipping invalid contract data: {e}")
                    continue
                except Exception as e:
                    logger.debug(f"Error processing contract {ticker}: {e}")
                    continue

            # Step 6: Update cache with current scan timestamp
            await volume_cache.set(underlying, {'last_scan_ns': current_timestamp_ns})

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

    async def get_market_hours(self, date: Optional[str] = None) -> Dict:
        """Check if market is open"""
        if not date:
            date = datetime.now().strftime('%Y-%m-%d')
            
        endpoint = f"/v1/marketstatus/now"
        data = await self._make_request(endpoint)
        
        if data:
            return {
                'market': data.get('market', 'unknown'),
                'server_time': data.get('serverTime', ''),
                'exchanges': data.get('exchanges', {}),
                'currencies': data.get('currencies', {})
            }
        return {}
        
    async def is_market_open(self) -> bool:
        """Check if US market is currently open with time-based fallback"""
        try:
            status = await self.get_market_hours()
            market_status = status.get('market', '')

            # Log the API response for debugging
            if market_status:
                logger.debug(f"Polygon market status: {market_status}, server_time: {status.get('server_time', 'N/A')}")

            # If API says open, trust it
            if market_status == 'open':
                return True

            # Fallback: Use time-based check (US Eastern Time)
            # Market hours: 9:30 AM - 4:00 PM ET, Monday-Friday
            from datetime import datetime
            import pytz

            eastern = pytz.timezone('America/New_York')
            now_et = datetime.now(eastern)

            # Check if weekend
            if now_et.weekday() >= 5:  # Saturday=5, Sunday=6
                logger.debug(f"Market closed: Weekend ({now_et.strftime('%A')})")
                return False

            # Check if within trading hours (9:30 AM - 4:00 PM ET)
            market_open = now_et.replace(hour=9, minute=30, second=0, microsecond=0)
            market_close = now_et.replace(hour=16, minute=0, second=0, microsecond=0)

            is_open = market_open <= now_et <= market_close

            if is_open:
                logger.info(f"✅ Market OPEN (time-based check): {now_et.strftime('%I:%M %p ET')}")
            else:
                logger.debug(f"Market closed (time-based check): {now_et.strftime('%I:%M %p ET')}")

            return is_open

        except Exception as e:
            logger.error(f"Error checking market status: {e}")
            # If error, assume market is open during business hours as fallback
            return True
        
    async def get_aggregates(self, symbol: str, timespan: str = 'minute', 
                           multiplier: int = 5, from_date: str = None, to_date: str = None) -> pd.DataFrame:
        """Get aggregate bars for analysis"""
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
        
    async def close(self):
        """Close the session"""
        await self._close_session()
    
    def get_stats(self) -> Dict[str, Any]:
        """Get fetcher statistics"""
        return {
            'request_count': self._request_count,
            'error_count': self._error_count,
            'error_rate': SafeCalculations.safe_percentage(
                self._error_count, self._request_count
            ),
            'last_error_time': self._last_error_time.isoformat() if self._last_error_time else None,
            'circuit_breaker_state': api_circuit_breaker.state,
            'cache_stats': cache_manager.get_all_stats()
        }
    
    async def health_check(self) -> Dict[str, Any]:
        """Perform health check"""
        try:
            # Try to get market status
            start_time = time.time()
            market_status = await self.get_market_hours()
            response_time = time.time() - start_time
            
            return {
                'healthy': True,
                'response_time_ms': response_time * 1000,
                'market_status': market_status.get('market', 'unknown'),
                'stats': self.get_stats()
            }
        except Exception as e:
            return {
                'healthy': False,
                'error': str(e),
                'stats': self.get_stats()
            }
