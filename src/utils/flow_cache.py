"""
Shared Flow Cache - Centralized flow data prefetching for all bots.

This module implements the "Gamma Bot efficiency pattern":
- ONE prefetch per cycle for all watchlist symbols
- Local filtering by each bot (no per-symbol API calls during scan)
- Automatic cache refresh every 5 minutes

All bots share this cache, eliminating redundant API calls.
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Set
from dataclasses import dataclass, field
import time

from src.config import Config

logger = logging.getLogger(__name__)


@dataclass
class CachedFlow:
    """Single flow entry in the cache."""
    ticker: str
    underlying: str
    option_type: str  # 'CALL' or 'PUT'
    strike: float
    expiration: str
    volume_delta: int
    total_volume: int
    open_interest: int
    last_price: float
    premium: float
    implied_volatility: float
    delta: float
    gamma: float
    theta: float
    vega: float
    underlying_price: float
    vol_oi_ratio: float
    flow_intensity: str  # 'NORMAL', 'MODERATE', 'STRONG', 'AGGRESSIVE'
    bid: float
    ask: float
    timestamp: datetime
    last_trade_timestamp: Optional[datetime] = None


@dataclass
class FlowCacheState:
    """State of the flow cache."""
    last_refresh: Optional[datetime] = None
    refresh_in_progress: bool = False
    flows_by_symbol: Dict[str, List[CachedFlow]] = field(default_factory=dict)
    all_flows: List[CachedFlow] = field(default_factory=list)
    symbols_scanned: Set[str] = field(default_factory=set)
    refresh_duration_ms: float = 0
    error_count: int = 0
    last_error: Optional[str] = None


class FlowCache:
    """
    Centralized flow cache for all bots.
    
    Usage Pattern:
        # At start of each scan cycle
        await flow_cache.refresh_if_needed(fetcher, watchlist)
        
        # In each bot's scan (no API calls!)
        flows = flow_cache.get_flows_for_symbol("AAPL")
        
        # Or filter across all flows
        high_premium = flow_cache.filter_flows(min_premium=500000)
    """
    
    def __init__(self, refresh_interval_seconds: int = 300):
        """
        Initialize flow cache.
        
        Args:
            refresh_interval_seconds: How often to refresh (default: 5 minutes)
        """
        self.refresh_interval = refresh_interval_seconds
        self._state = FlowCacheState()
        self._lock = asyncio.Lock()
        self._fetcher = None
        
    @property
    def is_fresh(self) -> bool:
        """Check if cache data is still fresh."""
        if not self._state.last_refresh:
            return False
        age = (datetime.now() - self._state.last_refresh).total_seconds()
        return age < self.refresh_interval
    
    @property
    def age_seconds(self) -> float:
        """Get age of cache in seconds."""
        if not self._state.last_refresh:
            return float('inf')
        return (datetime.now() - self._state.last_refresh).total_seconds()
    
    def set_fetcher(self, fetcher) -> None:
        """Set the data fetcher reference."""
        self._fetcher = fetcher
    
    async def refresh_if_needed(
        self,
        fetcher,
        watchlist: List[str],
        force: bool = False
    ) -> bool:
        """
        Refresh cache if stale or forced.
        
        This is the ONLY method that makes API calls.
        All bots should call this at the start of their scan cycle.
        
        Args:
            fetcher: DataFetcher instance
            watchlist: List of ticker symbols to prefetch
            force: Force refresh even if cache is fresh
            
        Returns:
            True if refresh was performed, False if cache was fresh
        """
        # Quick check without lock
        if not force and self.is_fresh:
            logger.debug("FlowCache is fresh (%.1fs old), skipping refresh", self.age_seconds)
            return False
        
        async with self._lock:
            # Double-check after acquiring lock
            if not force and self.is_fresh:
                return False
            
            # Prevent concurrent refreshes
            if self._state.refresh_in_progress:
                logger.debug("FlowCache refresh already in progress, waiting...")
                return False
            
            self._state.refresh_in_progress = True
            
        try:
            start_time = time.time()
            logger.info("FlowCache: Starting prefetch for %d symbols...", len(watchlist))
            
            # Store fetcher reference
            self._fetcher = fetcher
            
            # Prefetch all symbols concurrently
            await self._prefetch_all_flows(fetcher, watchlist)
            
            duration_ms = (time.time() - start_time) * 1000
            self._state.refresh_duration_ms = duration_ms
            self._state.last_refresh = datetime.now()
            
            logger.info(
                "FlowCache: Prefetch complete in %.0fms - %d symbols, %d total flows",
                duration_ms,
                len(self._state.symbols_scanned),
                len(self._state.all_flows)
            )
            
            return True
            
        except Exception as e:
            self._state.error_count += 1
            self._state.last_error = str(e)
            logger.error("FlowCache refresh error: %s", e)
            return False
            
        finally:
            self._state.refresh_in_progress = False
    
    async def _prefetch_all_flows(
        self,
        fetcher,
        watchlist: List[str]
    ) -> None:
        """
        Prefetch flow data for all symbols concurrently.
        
        This uses the SAME approach as Gamma Bot:
        - High concurrency (but respecting rate limits)
        - Single API call per symbol (get_option_chain_snapshot)
        - Local computation of flow metrics
        """
        # Reset state
        self._state.flows_by_symbol = {}
        self._state.all_flows = []
        self._state.symbols_scanned = set()
        
        # Concurrency control - match the config
        max_concurrent = min(Config.MAX_CONCURRENT_REQUESTS, 10)  # Cap at 10 to avoid rate limits
        semaphore = asyncio.Semaphore(max_concurrent)
        
        async def fetch_symbol_flows(symbol: str) -> List[CachedFlow]:
            """Fetch flows for a single symbol."""
            async with semaphore:
                try:
                    # Single API call - same as Gamma Bot uses
                    snapshot = await fetcher.get_option_chain_snapshot(symbol)
                    
                    if not snapshot:
                        return []
                    
                    # Process snapshot locally (no API calls)
                    flows = self._process_snapshot_to_flows(symbol, snapshot)
                    return flows
                    
                except Exception as e:
                    logger.debug("FlowCache: Error fetching %s: %s", symbol, e)
                    return []
        
        # Fetch all symbols concurrently
        tasks = [fetch_symbol_flows(symbol) for symbol in watchlist]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Aggregate results
        for symbol, result in zip(watchlist, results):
            self._state.symbols_scanned.add(symbol)
            
            if isinstance(result, Exception):
                logger.debug("FlowCache: Exception for %s: %s", symbol, result)
                continue
            
            if result:
                self._state.flows_by_symbol[symbol] = result
                self._state.all_flows.extend(result)
    
    def _process_snapshot_to_flows(
        self,
        underlying: str,
        snapshot: List[Dict]
    ) -> List[CachedFlow]:
        """
        Process option chain snapshot into flow signals.
        
        This is LOCAL computation - no API calls.
        Uses the same logic as detect_unusual_flow() but without caching overhead.
        """
        flows = []
        
        for contract in snapshot:
            try:
                details = contract.get('details', {}) or {}
                ticker = contract.get('ticker') or details.get('ticker', '')
                if not ticker:
                    continue
                
                day_data = contract.get('day', {}) or {}
                last_quote = contract.get('last_quote', {}) or {}
                last_trade = contract.get('last_trade', {}) or {}
                greeks = contract.get('greeks', {}) or {}
                
                # Get volume
                current_volume = day_data.get('volume', 0)
                if current_volume <= 0:
                    continue
                
                # Get price with fallbacks
                last_price = self._extract_price(day_data, last_quote, last_trade)
                if not last_price or last_price <= 0:
                    continue
                
                # Get open interest
                open_interest = contract.get('open_interest', 0)
                
                # Calculate volume/OI ratio and intensity
                vol_oi_ratio = current_volume / open_interest if open_interest > 0 else 100.0
                
                flow_intensity = "NORMAL"
                if vol_oi_ratio >= 0.5:
                    flow_intensity = "AGGRESSIVE"
                elif vol_oi_ratio >= 0.2:
                    flow_intensity = "STRONG"
                elif vol_oi_ratio >= 0.1:
                    flow_intensity = "MODERATE"
                
                # Calculate premium (use current volume as delta for first scan)
                # In a real implementation, we'd track volume deltas between scans
                volume_delta = min(current_volume, 5000)  # Cap to prevent extreme values
                premium = volume_delta * last_price * 100
                
                # Get contract details
                strike = details.get('strike_price', 0)
                expiration = details.get('expiration_date', '')
                contract_type = details.get('contract_type', '')
                
                # Determine option type
                option_type = 'CALL' if contract_type == 'call' or 'C' in str(ticker) else 'PUT'
                
                # Get underlying price
                underlying_asset = contract.get('underlying_asset', {}) or {}
                underlying_price = underlying_asset.get('price', 0) or underlying_asset.get('close', 0)
                
                # Get bid/ask
                bid = self._extract_quote_price(last_quote, 'bid')
                ask = self._extract_quote_price(last_quote, 'ask')
                
                # Create flow entry
                flow = CachedFlow(
                    ticker=ticker,
                    underlying=underlying,
                    option_type=option_type,
                    strike=float(strike) if strike else 0.0,
                    expiration=expiration,
                    volume_delta=volume_delta,
                    total_volume=current_volume,
                    open_interest=open_interest,
                    last_price=last_price,
                    premium=premium,
                    implied_volatility=contract.get('implied_volatility', 0),
                    delta=greeks.get('delta', 0),
                    gamma=greeks.get('gamma', 0),
                    theta=greeks.get('theta', 0),
                    vega=greeks.get('vega', 0),
                    underlying_price=underlying_price,
                    vol_oi_ratio=vol_oi_ratio,
                    flow_intensity=flow_intensity,
                    bid=bid,
                    ask=ask,
                    timestamp=datetime.now(),
                )
                
                flows.append(flow)
                
            except Exception as e:
                logger.debug("FlowCache: Error processing contract: %s", e)
                continue
        
        # Sort by premium descending
        flows.sort(key=lambda f: f.premium, reverse=True)
        
        return flows[:25]  # Limit per symbol
    
    def _extract_price(
        self,
        day_data: Dict,
        last_quote: Dict,
        last_trade: Dict
    ) -> float:
        """Extract price from various sources."""
        candidates = [
            day_data.get('close'),
            day_data.get('vwap'),
            last_trade.get('price'),
            last_trade.get('p'),
            last_quote.get('midpoint'),
        ]
        
        # Handle nested last in quote
        quote_last = last_quote.get('last')
        if isinstance(quote_last, dict):
            candidates.extend([quote_last.get('price'), quote_last.get('p')])
        
        candidates.extend([
            last_quote.get('bid'),
            last_quote.get('ask'),
        ])
        
        for candidate in candidates:
            if candidate and candidate > 0:
                return float(candidate)
        
        return 0.0
    
    def _extract_quote_price(self, quote: Dict, key: str) -> float:
        """Extract bid or ask price."""
        value = quote.get(key)
        if isinstance(value, dict):
            value = value.get('price') or value.get('p')
        return float(value) if value and value > 0 else 0.0
    
    # ==================== QUERY METHODS (No API calls!) ====================
    
    def get_flows_for_symbol(self, symbol: str) -> List[CachedFlow]:
        """
        Get all cached flows for a specific symbol.
        
        This is LOCAL - no API calls.
        """
        return self._state.flows_by_symbol.get(symbol.upper(), [])
    
    def get_all_flows(self) -> List[CachedFlow]:
        """Get all cached flows across all symbols."""
        return self._state.all_flows
    
    def filter_flows(
        self,
        min_premium: float = 0,
        min_volume: int = 0,
        min_voi_ratio: float = 0,
        option_type: Optional[str] = None,
        flow_intensity: Optional[Set[str]] = None,
        max_dte: Optional[float] = None,
        min_dte: Optional[float] = None,
        symbols: Optional[List[str]] = None
    ) -> List[CachedFlow]:
        """
        Filter cached flows by various criteria.
        
        This is LOCAL filtering - no API calls.
        
        Args:
            min_premium: Minimum premium threshold
            min_volume: Minimum volume delta
            min_voi_ratio: Minimum volume/OI ratio
            option_type: Filter by 'CALL' or 'PUT'
            flow_intensity: Set of intensity levels ('STRONG', 'AGGRESSIVE', etc.)
            max_dte: Maximum days to expiration
            min_dte: Minimum days to expiration
            symbols: List of symbols to include (None = all)
            
        Returns:
            List of flows matching criteria
        """
        now = datetime.now()
        results = []
        
        for flow in self._state.all_flows:
            # Symbol filter
            if symbols and flow.underlying not in symbols:
                continue
            
            # Premium filter
            if flow.premium < min_premium:
                continue
            
            # Volume filter
            if flow.volume_delta < min_volume:
                continue
            
            # VOI ratio filter
            if flow.vol_oi_ratio < min_voi_ratio:
                continue
            
            # Option type filter
            if option_type and flow.option_type != option_type:
                continue
            
            # Intensity filter
            if flow_intensity and flow.flow_intensity not in flow_intensity:
                continue
            
            # DTE filters
            if flow.expiration:
                try:
                    exp_date = datetime.strptime(flow.expiration, '%Y-%m-%d')
                    dte = (exp_date - now).days
                    
                    if max_dte is not None and dte > max_dte:
                        continue
                    if min_dte is not None and dte < min_dte:
                        continue
                except ValueError:
                    pass
            
            results.append(flow)
        
        return results
    
    def get_top_flows(
        self,
        n: int = 10,
        min_premium: float = 0
    ) -> List[CachedFlow]:
        """Get top N flows by premium."""
        filtered = [f for f in self._state.all_flows if f.premium >= min_premium]
        return sorted(filtered, key=lambda f: f.premium, reverse=True)[:n]
    
    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        return {
            'is_fresh': self.is_fresh,
            'age_seconds': self.age_seconds,
            'last_refresh': self._state.last_refresh.isoformat() if self._state.last_refresh else None,
            'symbols_scanned': len(self._state.symbols_scanned),
            'total_flows': len(self._state.all_flows),
            'refresh_duration_ms': self._state.refresh_duration_ms,
            'error_count': self._state.error_count,
            'last_error': self._state.last_error,
        }
    
    def flow_to_dict(self, flow: CachedFlow) -> Dict[str, Any]:
        """Convert CachedFlow to dictionary for bot consumption."""
        return {
            'ticker': flow.ticker,
            'underlying': flow.underlying,
            'type': flow.option_type,
            'strike': flow.strike,
            'expiration': flow.expiration,
            'volume_delta': flow.volume_delta,
            'total_volume': flow.total_volume,
            'open_interest': flow.open_interest,
            'last_price': flow.last_price,
            'premium': flow.premium,
            'implied_volatility': flow.implied_volatility,
            'delta': flow.delta,
            'gamma': flow.gamma,
            'theta': flow.theta,
            'vega': flow.vega,
            'underlying_price': flow.underlying_price,
            'vol_oi_ratio': flow.vol_oi_ratio,
            'flow_intensity': flow.flow_intensity,
            'bid': flow.bid,
            'ask': flow.ask,
            'timestamp': flow.timestamp,
            'last_trade_timestamp': flow.last_trade_timestamp,
        }


# Global singleton instance
flow_cache = FlowCache(refresh_interval_seconds=300)  # 5 minutes


def get_flow_cache() -> FlowCache:
    """Get the global flow cache instance."""
    return flow_cache

