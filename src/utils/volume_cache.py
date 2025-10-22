"""
Volume Cache - In-memory volume tracking for options flow detection
Tracks volume changes across polling intervals to detect unusual flow
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, Optional
from collections import defaultdict

logger = logging.getLogger(__name__)


class VolumeCache:
    """
    In-memory cache for tracking options contract volume changes.

    Purpose:
    - Store previous volume snapshots for comparison
    - Calculate volume deltas to detect unusual flow
    - Automatic cleanup of stale entries

    Architecture:
    - Multi-level cache: Ticker → Contract → Volume data
    - Time-based expiration (2-5 minute TTL)
    - Thread-safe async operations
    """

    def __init__(self, ttl_seconds: int = 120, cleanup_interval: int = 300):
        """
        Initialize volume cache.

        Args:
            ttl_seconds: Time-to-live for cache entries (default: 2 minutes)
            cleanup_interval: Cleanup task interval (default: 5 minutes)
        """
        # Cache structure: {ticker: {contract_ticker: {volume, timestamp}}}
        self.cache: Dict[str, Dict[str, Dict]] = defaultdict(dict)

        # Timestamps for each ticker's last update
        self.timestamps: Dict[str, datetime] = {}

        # Configuration
        self.ttl_seconds = ttl_seconds
        self.cleanup_interval = cleanup_interval

        # Statistics
        self.hits = 0
        self.misses = 0
        self.sets = 0
        self.cleanups = 0

        # Cleanup task reference
        self._cleanup_task: Optional[asyncio.Task] = None

        logger.info(f"VolumeCache initialized (TTL: {ttl_seconds}s, Cleanup: {cleanup_interval}s)")

    async def get(self, ticker: str) -> Optional[Dict[str, Dict]]:
        """
        Get previous volume snapshot for a ticker.

        Args:
            ticker: Underlying ticker symbol (e.g., 'AAPL')

        Returns:
            Dict mapping contract tickers to volume data, or None if not cached

        Example:
            {
                'O:AAPL250117C00200000': {'volume': 1500, 'timestamp': ...},
                'O:AAPL250117P00200000': {'volume': 800, 'timestamp': ...}
            }
        """
        if ticker not in self.cache:
            self.misses += 1
            logger.debug(f"Volume cache MISS for {ticker}")
            return None

        # Check if cache is still fresh
        if ticker in self.timestamps:
            age_seconds = (datetime.now() - self.timestamps[ticker]).total_seconds()

            if age_seconds < self.ttl_seconds:
                self.hits += 1
                logger.debug(f"Volume cache HIT for {ticker} (age: {age_seconds:.1f}s)")
                return self.cache[ticker]
            else:
                # Expired - remove and return None
                logger.debug(f"Volume cache EXPIRED for {ticker} (age: {age_seconds:.1f}s)")
                self._remove_ticker(ticker)
                self.misses += 1
                return None

        # Ticker in cache but no timestamp (shouldn't happen)
        self.misses += 1
        return None

    async def set(self, ticker: str, snapshot: Dict[str, Dict]):
        """
        Store volume snapshot for a ticker.

        Args:
            ticker: Underlying ticker symbol
            snapshot: Dict mapping contract tickers to volume data

        Example:
            await cache.set('AAPL', {
                'O:AAPL250117C00200000': {'volume': 1500},
                'O:AAPL250117P00200000': {'volume': 800}
            })
        """
        if not snapshot:
            logger.debug(f"Skipping empty snapshot for {ticker}")
            return

        # Add timestamp to each contract if not present
        current_time = datetime.now()
        for contract_ticker, data in snapshot.items():
            if 'timestamp' not in data:
                data['timestamp'] = current_time

        # Store snapshot
        self.cache[ticker] = snapshot
        self.timestamps[ticker] = current_time
        self.sets += 1

        logger.debug(f"Stored volume snapshot for {ticker} ({len(snapshot)} contracts)")

    def _remove_ticker(self, ticker: str):
        """Remove ticker from cache"""
        if ticker in self.cache:
            del self.cache[ticker]
        if ticker in self.timestamps:
            del self.timestamps[ticker]

    async def cleanup(self):
        """
        Remove stale entries from cache.

        Removes entries older than TTL + grace period (2x TTL).
        """
        cutoff_time = datetime.now() - timedelta(seconds=self.ttl_seconds * 2)
        stale_tickers = []

        for ticker, timestamp in self.timestamps.items():
            if timestamp < cutoff_time:
                stale_tickers.append(ticker)

        for ticker in stale_tickers:
            logger.debug(f"Removing stale cache entry for {ticker}")
            self._remove_ticker(ticker)

        if stale_tickers:
            self.cleanups += 1
            logger.info(f"Cleaned up {len(stale_tickers)} stale cache entries")

        return len(stale_tickers)

    async def start_cleanup_task(self):
        """Start background cleanup task"""
        if self._cleanup_task and not self._cleanup_task.done():
            logger.warning("Cleanup task already running")
            return

        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        logger.info("Volume cache cleanup task started")

    async def stop_cleanup_task(self):
        """Stop background cleanup task"""
        if self._cleanup_task and not self._cleanup_task.done():
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
            logger.info("Volume cache cleanup task stopped")

    async def _cleanup_loop(self):
        """Background cleanup loop"""
        while True:
            try:
                await asyncio.sleep(self.cleanup_interval)
                await self.cleanup()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in volume cache cleanup: {e}")

    def get_stats(self) -> Dict:
        """
        Get cache statistics.

        Returns:
            Dict with cache performance metrics
        """
        total_requests = self.hits + self.misses
        hit_rate = self.hits / total_requests if total_requests > 0 else 0

        return {
            'hits': self.hits,
            'misses': self.misses,
            'sets': self.sets,
            'cleanups': self.cleanups,
            'hit_rate': hit_rate,
            'cached_tickers': len(self.cache),
            'total_contracts': sum(len(contracts) for contracts in self.cache.values()),
            'ttl_seconds': self.ttl_seconds
        }

    def clear(self):
        """Clear all cache entries"""
        count = len(self.cache)
        self.cache.clear()
        self.timestamps.clear()
        logger.info(f"Cleared volume cache ({count} tickers)")

    def __repr__(self):
        stats = self.get_stats()
        return (
            f"VolumeCache(tickers={stats['cached_tickers']}, "
            f"contracts={stats['total_contracts']}, "
            f"hit_rate={stats['hit_rate']:.1%})"
        )


# Global volume cache instance
volume_cache = VolumeCache()
