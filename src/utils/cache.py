"""
Caching utilities for ORAKL Bot
Implements in-memory and Redis caching with TTL support
"""

import asyncio
import json
import pickle
import time
from typing import Any, Optional, Union, Callable, Dict
from datetime import datetime, timedelta
from functools import wraps
import hashlib
import logging

logger = logging.getLogger(__name__)


class CacheEntry:
    """Single cache entry with TTL support"""
    
    def __init__(self, value: Any, ttl_seconds: Optional[int] = None):
        self.value = value
        self.created_at = time.time()
        self.ttl_seconds = ttl_seconds
        self.access_count = 0
        self.last_accessed = self.created_at
    
    def is_expired(self) -> bool:
        """Check if entry has expired"""
        if self.ttl_seconds is None:
            return False
        return time.time() - self.created_at > self.ttl_seconds
    
    def get(self) -> Any:
        """Get value and update access stats"""
        self.access_count += 1
        self.last_accessed = time.time()
        return self.value


class InMemoryCache:
    """Thread-safe in-memory cache with TTL and size limits"""
    
    def __init__(self, max_size: int = 1000, default_ttl: int = 300):
        """
        Initialize in-memory cache
        
        Args:
            max_size: Maximum number of entries
            default_ttl: Default TTL in seconds
        """
        self.max_size = max_size
        self.default_ttl = default_ttl
        self._cache: Dict[str, CacheEntry] = {}
        self._lock = asyncio.Lock()
        self._stats = {
            'hits': 0,
            'misses': 0,
            'evictions': 0,
            'expirations': 0
        }
    
    async def get(self, key: str) -> Optional[Any]:
        """Get value from cache"""
        async with self._lock:
            if key in self._cache:
                entry = self._cache[key]
                if entry.is_expired():
                    del self._cache[key]
                    self._stats['expirations'] += 1
                    self._stats['misses'] += 1
                    return None
                
                self._stats['hits'] += 1
                return entry.get()
            
            self._stats['misses'] += 1
            return None
    
    async def set(
        self,
        key: str,
        value: Any,
        ttl_seconds: Optional[int] = None
    ) -> None:
        """Set value in cache"""
        async with self._lock:
            # Use default TTL if not specified
            if ttl_seconds is None:
                ttl_seconds = self.default_ttl
            
            # Check if we need to evict entries
            if len(self._cache) >= self.max_size:
                await self._evict_lru()
            
            self._cache[key] = CacheEntry(value, ttl_seconds)
    
    async def delete(self, key: str) -> bool:
        """Delete key from cache"""
        async with self._lock:
            if key in self._cache:
                del self._cache[key]
                return True
            return False
    
    async def clear(self) -> None:
        """Clear entire cache"""
        async with self._lock:
            self._cache.clear()
    
    async def _evict_lru(self) -> None:
        """Evict least recently used entry"""
        if not self._cache:
            return
        
        # Find LRU entry
        lru_key = min(
            self._cache.keys(),
            key=lambda k: self._cache[k].last_accessed
        )
        
        del self._cache[lru_key]
        self._stats['evictions'] += 1
    
    async def cleanup_expired(self) -> int:
        """Remove all expired entries"""
        async with self._lock:
            expired_keys = [
                key for key, entry in self._cache.items()
                if entry.is_expired()
            ]
            
            for key in expired_keys:
                del self._cache[key]
                self._stats['expirations'] += 1
            
            return len(expired_keys)
    
    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics"""
        total_requests = self._stats['hits'] + self._stats['misses']
        hit_rate = self._stats['hits'] / total_requests if total_requests > 0 else 0
        
        return {
            **self._stats,
            'size': len(self._cache),
            'hit_rate': hit_rate,
            'total_requests': total_requests
        }


class CacheManager:
    """Manages multiple cache instances"""
    
    def __init__(self):
        self.caches = {
            'api': InMemoryCache(max_size=500, default_ttl=60),      # 1 minute for API data
            'market': InMemoryCache(max_size=1000, default_ttl=300), # 5 minutes for market data
            'analysis': InMemoryCache(max_size=200, default_ttl=900), # 15 minutes for analysis
            'signals': InMemoryCache(max_size=100, default_ttl=3600)  # 1 hour for signals
        }
        self._cleanup_task = None
    
    async def start(self):
        """Start cache cleanup task"""
        self._cleanup_task = asyncio.create_task(self._periodic_cleanup())
    
    async def stop(self):
        """Stop cache cleanup task"""
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
    
    async def _periodic_cleanup(self):
        """Periodically clean up expired entries"""
        while True:
            try:
                await asyncio.sleep(60)  # Run every minute
                
                for name, cache in self.caches.items():
                    expired = await cache.cleanup_expired()
                    if expired > 0:
                        logger.debug(f"Cleaned up {expired} expired entries from {name} cache")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in cache cleanup: {e}")
    
    def get_cache(self, name: str) -> InMemoryCache:
        """Get specific cache instance"""
        if name not in self.caches:
            # Create new cache if doesn't exist
            self.caches[name] = InMemoryCache()
        return self.caches[name]
    
    async def clear_all(self):
        """Clear all caches"""
        for cache in self.caches.values():
            await cache.clear()
    
    def get_all_stats(self) -> Dict[str, Dict[str, Any]]:
        """Get statistics for all caches"""
        return {
            name: cache.get_stats()
            for name, cache in self.caches.items()
        }


# Global cache manager instance
cache_manager = CacheManager()


def cached(
    cache_name: str = 'api',
    ttl_seconds: Optional[int] = None,
    key_func: Optional[Callable] = None
):
    """
    Decorator for caching function results
    
    Args:
        cache_name: Name of cache to use
        ttl_seconds: TTL for cached value
        key_func: Function to generate cache key from arguments
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            # Generate cache key
            if key_func:
                cache_key = key_func(*args, **kwargs)
            else:
                # Default key generation
                key_parts = [func.__name__]
                if args:
                    key_parts.extend(str(arg) for arg in args)
                if kwargs:
                    key_parts.extend(f"{k}={v}" for k, v in sorted(kwargs.items()))
                cache_key = ":".join(key_parts)
            
            # Get cache instance
            cache = cache_manager.get_cache(cache_name)
            
            # Try to get from cache
            cached_value = await cache.get(cache_key)
            if cached_value is not None:
                logger.debug(f"Cache hit for {func.__name__} with key {cache_key}")
                return cached_value
            
            # Call function and cache result
            logger.debug(f"Cache miss for {func.__name__} with key {cache_key}")
            result = await func(*args, **kwargs)
            
            # Cache the result
            await cache.set(cache_key, result, ttl_seconds)
            
            return result
        
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            # For sync functions, we need to run in event loop
            loop = asyncio.get_event_loop()
            return loop.run_until_complete(async_wrapper(*args, **kwargs))
        
        return async_wrapper if asyncio.iscoroutinefunction(func) else sync_wrapper
    
    return decorator


def invalidate_cache(cache_name: str, key_pattern: Optional[str] = None):
    """
    Invalidate cache entries
    
    Args:
        cache_name: Name of cache
        key_pattern: Optional pattern to match keys (if None, clears entire cache)
    """
    async def _invalidate():
        cache = cache_manager.get_cache(cache_name)
        
        if key_pattern is None:
            await cache.clear()
            logger.info(f"Cleared entire {cache_name} cache")
        else:
            # For pattern matching, we'd need to iterate through keys
            # This is a simplified version
            deleted = await cache.delete(key_pattern)
            if deleted:
                logger.info(f"Invalidated {key_pattern} from {cache_name} cache")
    
    # Run invalidation
    asyncio.create_task(_invalidate())


class MarketDataCache:
    """Specialized cache for market data with smart invalidation"""
    
    def __init__(self):
        self.cache = InMemoryCache(max_size=2000, default_ttl=60)
        self.market_hours_cache = {}
    
    async def get_stock_price(self, symbol: str) -> Optional[float]:
        """Get cached stock price"""
        key = f"price:{symbol}"
        return await self.cache.get(key)
    
    async def set_stock_price(self, symbol: str, price: float):
        """Cache stock price"""
        key = f"price:{symbol}"
        # Shorter TTL during market hours
        ttl = 30 if self._is_market_hours() else 300
        await self.cache.set(key, price, ttl)
    
    async def get_options_chain(self, symbol: str, expiration: Optional[str] = None) -> Optional[Any]:
        """Get cached options chain"""
        key = f"chain:{symbol}:{expiration or 'all'}"
        return await self.cache.get(key)
    
    async def set_options_chain(self, symbol: str, chain: Any, expiration: Optional[str] = None):
        """Cache options chain"""
        key = f"chain:{symbol}:{expiration or 'all'}"
        # Longer TTL for options chains
        ttl = 300 if self._is_market_hours() else 3600
        await self.cache.set(key, chain, ttl)

    async def get_financials(self, symbol: str) -> Optional[Dict]:
        """Get cached financials"""
        key = f"financials:{symbol}"
        return await self.cache.get(key)

    async def set_financials(self, symbol: str, financials: Dict):
        """Cache financials"""
        key = f"financials:{symbol}"
        await self.cache.set(key, financials, ttl_seconds=43200)  # 12 hours

    async def get_avg_volume(self, symbol: str) -> Optional[float]:
        """Get cached 30-day average volume"""
        key = f"avg_volume:{symbol}"
        return await self.cache.get(key)

    async def set_avg_volume(self, symbol: str, avg_volume: float):
        """Cache 30-day average volume"""
        key = f"avg_volume:{symbol}"
        await self.cache.set(key, avg_volume, ttl_seconds=14400)  # 4 hours
    
    def _is_market_hours(self) -> bool:
        """Check if market is currently open"""
        now = datetime.now()
        weekday = now.weekday()
        
        # Check if weekend
        if weekday >= 5:  # Saturday = 5, Sunday = 6
            return False
        
        # Check time (9:30 AM - 4:00 PM ET)
        market_open = now.replace(hour=9, minute=30, second=0)
        market_close = now.replace(hour=16, minute=0, second=0)
        
        return market_open <= now <= market_close
