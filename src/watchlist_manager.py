"""
Dynamic Watchlist Manager
Fetches and maintains market-wide ticker universe from Polygon API
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Set
from src.config import Config

logger = logging.getLogger(__name__)


class WatchlistManager:
    """
    Manages dynamic watchlist with automatic refresh
    Fetches all liquid tickers from Polygon API based on liquidity filters
    """

    def __init__(self, data_fetcher):
        self.data_fetcher = data_fetcher
        self.watchlist: List[str] = []
        self.ticker_details: Dict[str, Dict] = {}
        self.last_refresh: datetime = None
        self.refresh_interval = Config.WATCHLIST_REFRESH_INTERVAL
        self.mode = Config.WATCHLIST_MODE

        # Liquidity filters
        self.min_market_cap = Config.MIN_MARKET_CAP
        self.min_daily_volume = Config.MIN_DAILY_VOLUME
        self.min_price = Config.MIN_STOCK_PRICE
        self.max_price = Config.MAX_STOCK_PRICE

        logger.info(f"WatchlistManager initialized in {self.mode} mode")
        if self.mode == 'ALL_MARKET':
            logger.info(f"Liquidity Filters: Market Cap >${self.min_market_cap/1e9:.1f}B, "
                       f"Volume >{self.min_daily_volume/1e6:.1f}M, "
                       f"Price ${self.min_price}-${self.max_price}")

    async def get_watchlist(self) -> List[str]:
        """
        Get current watchlist, refreshing if needed
        Returns list of ticker symbols
        """
        if self.mode == 'STATIC':
            return Config.STATIC_WATCHLIST

        # Check if refresh needed
        if self._needs_refresh():
            await self.refresh_watchlist()

        return self.watchlist

    def _needs_refresh(self) -> bool:
        """Check if watchlist needs refresh"""
        if not self.watchlist:
            return True

        if not self.last_refresh:
            return True

        time_since_refresh = (datetime.now() - self.last_refresh).total_seconds()
        return time_since_refresh >= self.refresh_interval

    async def refresh_watchlist(self):
        """
        Refresh watchlist from Polygon API
        Fetches all active tickers and filters by liquidity
        """
        logger.info("🔄 Refreshing watchlist from Polygon API...")
        start_time = datetime.now()

        try:
            # Validate data_fetcher is initialized
            if not self.data_fetcher or not hasattr(self.data_fetcher, '_make_request'):
                logger.error(f"❌ DataFetcher not properly initialized. Type: {type(self.data_fetcher)}")
                raise ValueError("DataFetcher not initialized")

            # Get all active tickers from Polygon
            all_tickers = await self._fetch_all_tickers()
            logger.info(f"📊 Fetched {len(all_tickers)} total tickers from Polygon")

            if not all_tickers:
                logger.warning("⚠️ No tickers fetched from Polygon API, using static fallback")
                self.watchlist = Config.STATIC_WATCHLIST.split(',')
                self.last_refresh = datetime.now()
                return

            # Filter by liquidity criteria
            liquid_tickers = await self._filter_by_liquidity(all_tickers)
            logger.info(f"✅ Filtered to {len(liquid_tickers)} liquid tickers")

            # Update watchlist
            self.watchlist = liquid_tickers
            self.last_refresh = datetime.now()

            duration = (datetime.now() - start_time).total_seconds()
            logger.info(f"✅ Watchlist refreshed in {duration:.1f}s: {len(self.watchlist)} tickers")
            logger.info(f"📈 Sample tickers: {', '.join(self.watchlist[:10])}")

        except Exception as e:
            logger.error(f"❌ Error refreshing watchlist: {e}", exc_info=True)
            # Fall back to static watchlist on error
            if not self.watchlist:
                logger.warning("⚠️ Using static watchlist as fallback")
                static_list = Config.STATIC_WATCHLIST
                if isinstance(static_list, str):
                    self.watchlist = [t.strip() for t in static_list.split(',') if t.strip()]
                else:
                    self.watchlist = static_list
                logger.info(f"📋 Loaded {len(self.watchlist)} tickers from static watchlist")
                self.last_refresh = datetime.now()

    async def _fetch_all_tickers(self) -> List[Dict]:
        """
        Fetch all active US stock tickers from Polygon
        Uses /v3/reference/tickers endpoint with pagination
        """
        all_tickers = []
        next_url = None

        try:
            # Ensure DataFetcher session is initialized
            if hasattr(self.data_fetcher, 'ensure_session'):
                await self.data_fetcher.ensure_session()

            # Initial request
            params = {
                'market': 'stocks',
                'exchange': 'XNGS,XNYS,ARCX',  # NASDAQ, NYSE, NYSE Arca
                'active': 'true',
                'limit': 1000  # Max per page
            }

            endpoint = '/v3/reference/tickers'
            logger.debug(f"Fetching tickers from {endpoint} with params: {params}")
            data = await self.data_fetcher._make_request(endpoint, params)
            logger.debug(f"Received response with {len(data.get('results', []))} results")

            if data and 'results' in data:
                all_tickers.extend(data['results'])
                next_url = data.get('next_url')

            # Paginate through remaining results
            page_count = 1
            while next_url and page_count < 10:  # Limit to 10 pages (10,000 tickers)
                # Extract URL path and query params
                if 'cursor=' in next_url:
                    cursor = next_url.split('cursor=')[1].split('&')[0]
                    params['cursor'] = cursor

                data = await self.data_fetcher._make_request(endpoint, params)

                if data and 'results' in data:
                    all_tickers.extend(data['results'])
                    next_url = data.get('next_url')
                    page_count += 1
                else:
                    break

                # Small delay to avoid rate limits
                await asyncio.sleep(0.1)

            logger.info(f"📄 Fetched {page_count} pages, {len(all_tickers)} total tickers")

        except Exception as e:
            logger.error(f"Error fetching tickers: {e}")

        return all_tickers

    async def _filter_by_liquidity(self, tickers: List[Dict]) -> List[str]:
        """
        Filter tickers by liquidity criteria
        Uses snapshot data for real-time volume/price filtering
        """
        filtered = []

        # First pass: Filter by market cap (from ticker details)
        candidates = []
        for ticker in tickers:
            try:
                # Skip non-common stock (ADRs, preferred, etc.)
                ticker_type = ticker.get('type', '')
                if ticker_type not in ['CS', 'ADRC']:  # CS = Common Stock, ADRC = ADR Common
                    continue

                # Get market cap
                market_cap = ticker.get('market_cap', 0)
                if market_cap and market_cap >= self.min_market_cap:
                    candidates.append(ticker['ticker'])

            except Exception as e:
                logger.debug(f"Error filtering {ticker.get('ticker', 'unknown')}: {e}")
                continue

        logger.info(f"📊 {len(candidates)} tickers passed market cap filter (>${self.min_market_cap/1e9:.1f}B)")

        # Second pass: Get snapshot data for volume/price filtering
        # Process in batches of 250 (Polygon limit)
        batch_size = 250
        for i in range(0, len(candidates), batch_size):
            batch = candidates[i:i+batch_size]

            try:
                # Get snapshot for batch
                snapshots = await self._get_batch_snapshot(batch)

                for symbol, snap in snapshots.items():
                    try:
                        # Get price and volume
                        price = snap.get('day', {}).get('c', 0)  # Close price
                        volume = snap.get('day', {}).get('v', 0)  # Volume

                        # Apply filters
                        if (self.min_price <= price <= self.max_price and
                            volume >= self.min_daily_volume):
                            filtered.append(symbol)

                            # Store details for future use
                            self.ticker_details[symbol] = {
                                'price': price,
                                'volume': volume,
                                'market_cap': next((t.get('market_cap') for t in tickers if t.get('ticker') == symbol), None)
                            }

                    except Exception as e:
                        logger.debug(f"Error processing snapshot for {symbol}: {e}")
                        continue

            except Exception as e:
                logger.warning(f"Error fetching snapshot batch: {e}")
                continue

            # Small delay between batches
            await asyncio.sleep(0.2)

        # Sort by volume (most liquid first)
        filtered.sort(key=lambda t: self.ticker_details.get(t, {}).get('volume', 0), reverse=True)

        return filtered

    async def _get_batch_snapshot(self, symbols: List[str]) -> Dict[str, Dict]:
        """
        Get snapshot data for batch of symbols
        Uses /v2/snapshot/locale/us/markets/stocks/tickers endpoint
        """
        try:
            endpoint = '/v2/snapshot/locale/us/markets/stocks/tickers'
            params = {
                'tickers': ','.join(symbols)
            }

            data = await self.data_fetcher._make_request(endpoint, params)

            if data and 'tickers' in data:
                return {t['ticker']: t for t in data['tickers']}

        except Exception as e:
            logger.error(f"Error fetching batch snapshot: {e}")

        return {}

    def get_ticker_details(self, symbol: str) -> Dict:
        """Get cached details for a ticker"""
        return self.ticker_details.get(symbol, {})

    def get_stats(self) -> Dict:
        """Get watchlist statistics"""
        return {
            'mode': self.mode,
            'count': len(self.watchlist),
            'last_refresh': self.last_refresh.isoformat() if self.last_refresh else None,
            'next_refresh': (self.last_refresh + timedelta(seconds=self.refresh_interval)).isoformat()
                           if self.last_refresh else None,
            'top_10_by_volume': [
                {
                    'symbol': symbol,
                    'volume': self.ticker_details.get(symbol, {}).get('volume', 0),
                    'price': self.ticker_details.get(symbol, {}).get('price', 0)
                }
                for symbol in self.watchlist[:10]
            ]
        }


class SmartWatchlistManager(WatchlistManager):
    """
    Enhanced watchlist manager with sector rotation and momentum-based filtering
    """

    def __init__(self, data_fetcher):
        super().__init__(data_fetcher)
        self.sector_performance: Dict[str, float] = {}
        self.momentum_leaders: Set[str] = set()

    async def refresh_watchlist(self):
        """
        Enhanced refresh with sector rotation detection
        Prioritizes tickers from top-performing sectors
        """
        await super().refresh_watchlist()

        # Add sector-based enhancements
        if self.mode == 'ALL_MARKET' and self.watchlist:
            await self._detect_sector_rotation()
            await self._identify_momentum_leaders()

    async def _detect_sector_rotation(self):
        """
        Detect which sectors are outperforming
        Boost tickers from top 3 sectors
        """
        logger.info("📊 Detecting sector rotation...")

        # Get sector ETF performance (last 5 days)
        sector_etfs = {
            'XLK': 'Technology',
            'XLF': 'Financials',
            'XLV': 'Healthcare',
            'XLE': 'Energy',
            'XLI': 'Industrials',
            'XLY': 'Consumer Discretionary',
            'XLP': 'Consumer Staples',
            'XLB': 'Materials',
            'XLRE': 'Real Estate',
            'XLU': 'Utilities'
        }

        try:
            for etf, sector_name in sector_etfs.items():
                # Get 5-day performance
                end_date = datetime.now()
                start_date = end_date - timedelta(days=7)

                bars = await self.data_fetcher.get_aggregates(
                    etf,
                    timespan='day',
                    multiplier=1,
                    from_date=start_date.strftime('%Y-%m-%d'),
                    to_date=end_date.strftime('%Y-%m-%d')
                )

                if not bars.empty and len(bars) >= 2:
                    performance = ((bars.iloc[-1]['close'] - bars.iloc[0]['close']) /
                                 bars.iloc[0]['close']) * 100
                    self.sector_performance[sector_name] = performance

            # Log top performers
            top_sectors = sorted(self.sector_performance.items(),
                               key=lambda x: x[1], reverse=True)[:3]
            logger.info(f"🔥 Top performing sectors: {', '.join([f'{s} ({p:+.1f}%)' for s, p in top_sectors])}")

        except Exception as e:
            logger.warning(f"Error detecting sector rotation: {e}")

    async def _identify_momentum_leaders(self):
        """
        Identify stocks with strongest momentum
        These get priority in scanning
        """
        logger.info("🚀 Identifying momentum leaders...")

        # Sample top 100 by volume, check 5-day momentum
        candidates = self.watchlist[:100]
        momentum_data = []

        for symbol in candidates:
            try:
                end_date = datetime.now()
                start_date = end_date - timedelta(days=7)

                bars = await self.data_fetcher.get_aggregates(
                    symbol,
                    timespan='day',
                    multiplier=1,
                    from_date=start_date.strftime('%Y-%m-%d'),
                    to_date=end_date.strftime('%Y-%m-%d')
                )

                if not bars.empty and len(bars) >= 2:
                    momentum = ((bars.iloc[-1]['close'] - bars.iloc[0]['close']) /
                              bars.iloc[0]['close']) * 100

                    volume_trend = bars['volume'].iloc[-2:].mean() / bars['volume'].iloc[:-2].mean()

                    # Momentum score = price momentum + volume acceleration
                    score = momentum + (volume_trend - 1) * 50
                    momentum_data.append((symbol, score))

            except Exception as e:
                logger.debug(f"Error checking momentum for {symbol}: {e}")
                continue

            # Avoid rate limits
            if len(momentum_data) % 10 == 0:
                await asyncio.sleep(0.1)

        # Top 20 momentum leaders
        momentum_data.sort(key=lambda x: x[1], reverse=True)
        self.momentum_leaders = set([s for s, _ in momentum_data[:20]])

        logger.info(f"🚀 Momentum leaders: {', '.join(list(self.momentum_leaders)[:10])}")

    def is_momentum_leader(self, symbol: str) -> bool:
        """Check if symbol is a momentum leader"""
        return symbol in self.momentum_leaders
