"""
ORAKL Context Manager - Net GEX Engine

Maintains live "Market State" (Gamma Exposure Regime) for top liquid tickers.
Updates in the background to prevent blocking scan loops.

Net GEX (Gamma Exposure) determines market behavior:
- POSITIVE_GAMMA: Dealers are long gamma → Market tends to mean-revert, low vol
- NEGATIVE_GAMMA: Dealers are short gamma → Market amplifies moves, high vol

The "Flip Level" is where Net GEX crosses zero - a critical support/resistance level.
"""

import asyncio
import time
import logging
from datetime import datetime, timedelta
from typing import Dict, Optional, List
from src.config import Config
from src.utils.gamma_ratio import transform_polygon_snapshot, compute_gamma_ratio

logger = logging.getLogger(__name__)


class ContextManager:
    """
    Singleton that maintains the 'Market State' (GEX Regime) for top tickers.
    
    State Object per ticker:
        {
            'regime': 'POSITIVE_GAMMA' | 'NEGATIVE_GAMMA',
            'net_gex': float,           # Dollar-weighted gamma exposure
            'G': float,                 # Call/Put gamma ratio (0-1)
            'flip_level': float,        # Strike where GEX crosses zero
            'call_wall': float,         # Strike with max call OI
            'put_wall': float,          # Strike with max put OI
            'last_updated': float       # Unix timestamp
        }
    
    Usage:
        manager = ContextManager(data_fetcher)
        asyncio.create_task(manager.run_loop())  # Start background updates
        
        # Later, in your bot:
        context = manager.get_context('SPY')
        if context['regime'] == 'NEGATIVE_GAMMA':
            # Market is volatile, be cautious
    """
    
    def __init__(self, data_fetcher):
        """
        Initialize Context Manager
        
        Args:
            data_fetcher: DataFetcher instance
        """
        self.fetcher = data_fetcher
        self.tickers = getattr(Config, 'GEX_UNIVERSE', [
            'SPY', 'QQQ', 'IWM', 'AAPL', 'NVDA', 
            'TSLA', 'MSFT', 'AMZN', 'META', 'GOOGL'
        ])
        self.update_interval = getattr(Config, 'GEX_UPDATE_INTERVAL', 300)  # 5 minutes
        self.max_dte_days = getattr(Config, 'GEX_MAX_DTE_DAYS', 30)  # Only include < 30 DTE
        
        # State storage: {'SPY': {...}, 'QQQ': {...}}
        self.state: Dict[str, Dict] = {}
        
        # Running flag for graceful shutdown
        self._running = False
        self._last_full_update: Optional[float] = None
        
    async def run_loop(self):
        """Background task entry point - runs continuously"""
        logger.info(f"🔄 [ContextManager] Starting GEX Engine for {len(self.tickers)} tickers...")
        self._running = True
        
        while self._running:
            try:
                await self.update_all_contexts()
                self._last_full_update = time.time()
            except Exception as e:
                logger.error(f"[ContextManager] Update cycle failed: {e}")
            
            # Wait for next update cycle
            await asyncio.sleep(self.update_interval)
        
        logger.info("[ContextManager] GEX Engine stopped")
    
    async def stop(self):
        """Stop the background loop"""
        self._running = False
        
    async def update_all_contexts(self):
        """Update GEX context for all tracked tickers"""
        logger.info(f"🔄 [ContextManager] Updating GEX profiles for {len(self.tickers)} tickers...")
        
        success_count = 0
        
        for ticker in self.tickers:
            try:
                await self._update_ticker_context(ticker)
                success_count += 1
            except Exception as e:
                logger.error(f"[ContextManager] Failed to update {ticker}: {e}")
        
        logger.info(f"✅ [ContextManager] Update complete: {success_count}/{len(self.tickers)} tickers")
    
    async def _update_ticker_context(self, ticker: str):
        """Update GEX context for a single ticker"""
        # 1. Get Option Chain Snapshot
        snapshot = await self.fetcher.get_options_snapshot(ticker)
        
        if not snapshot:
            logger.debug(f"[ContextManager] No options data for {ticker}")
            return
        
        # 2. Get current spot price from underlying
        spot_price = await self._get_spot_price(ticker, snapshot)
        if not spot_price or spot_price <= 0:
            logger.debug(f"[ContextManager] No spot price for {ticker}")
            return
        
        # 3. Filter contracts by DTE (only include < 30 days where gamma matters most)
        expiry_limit = (datetime.now() + timedelta(days=self.max_dte_days)).strftime('%Y-%m-%d')
        filtered_contracts = self._filter_by_expiry(snapshot, expiry_limit)
        
        # 4. Calculate Net GEX and related metrics
        gex_data = self._calculate_gex(filtered_contracts, spot_price)
        
        # 5. Calculate G ratio using existing utility
        standardized = transform_polygon_snapshot(filtered_contracts)
        gamma_ratio_data = compute_gamma_ratio(standardized, spot_price)
        
        # 6. Update state
        self.state[ticker] = {
            'regime': gex_data['regime'],
            'net_gex': gex_data['net_gex'],
            'G': gamma_ratio_data['G'],
            'flip_level': gex_data['flip_level'],
            'call_wall': gex_data['call_wall'],
            'put_wall': gex_data['put_wall'],
            'spot_price': spot_price,
            'contracts_analyzed': len(filtered_contracts),
            'last_updated': time.time()
        }
        
        logger.debug(
            f"[ContextManager] {ticker}: {gex_data['regime']} | "
            f"G={gamma_ratio_data['G']:.2f} | "
            f"NetGEX=${gex_data['net_gex']:,.0f} | "
            f"Flip={gex_data['flip_level']:.1f}"
        )
    
    def _filter_by_expiry(self, contracts: List[Dict], expiry_limit: str) -> List[Dict]:
        """Filter contracts to only include those expiring before the limit"""
        filtered = []
        for contract in contracts:
            details = contract.get('details', {}) or {}
            exp_date = details.get('expiration_date', '')
            
            if exp_date and exp_date <= expiry_limit:
                filtered.append(contract)
        
        return filtered
    
    async def _get_spot_price(self, ticker: str, snapshot: List[Dict]) -> Optional[float]:
        """Extract spot price from snapshot or fetch separately"""
        # Try to get from underlying_asset in snapshot
        for contract in snapshot:
            underlying = contract.get('underlying_asset', {}) or {}
            price = underlying.get('price')
            if price and price > 0:
                return float(price)
        
        # Fallback: fetch current price
        try:
            price = await self.fetcher.get_current_price(ticker)
            return float(price) if price else None
        except Exception:
            return None
    
    def _calculate_gex(self, contracts: List[Dict], spot_price: float) -> Dict:
        """
        Calculate Net Gamma Exposure (GEX) from options chain.
        
        GEX Formula per strike:
            Call GEX = Gamma × OI × 100 × Spot Price
            Put GEX = Gamma × OI × 100 × Spot Price × -1 (negative)
        
        Net GEX > 0: Dealers are long gamma (stabilizing)
        Net GEX < 0: Dealers are short gamma (amplifying)
        """
        total_gex = 0.0
        gex_by_strike: Dict[float, float] = {}
        call_oi_by_strike: Dict[float, int] = {}
        put_oi_by_strike: Dict[float, int] = {}
        
        for contract in contracts:
            # Extract data from Polygon snapshot format
            details = contract.get('details', {}) or {}
            greeks = contract.get('greeks', {}) or {}
            
            gamma = greeks.get('gamma', 0)
            oi = contract.get('open_interest', 0)
            strike = details.get('strike_price', 0)
            contract_type = details.get('contract_type', '').lower()
            
            # Skip if missing critical data
            if not gamma or not oi or not strike:
                continue
            
            # Calculate dollar GEX
            # Using strike as proxy (could use spot, but strike is more accurate for that strike's gamma)
            gex_value = gamma * oi * 100 * spot_price
            
            if contract_type == 'put':
                gex_value = -gex_value  # Puts are negative dealer gamma
            
            total_gex += gex_value
            
            # Accumulate by strike for flip level calculation
            gex_by_strike[strike] = gex_by_strike.get(strike, 0) + gex_value
            
            # Track OI for wall detection
            if contract_type == 'call':
                call_oi_by_strike[strike] = call_oi_by_strike.get(strike, 0) + oi
            else:
                put_oi_by_strike[strike] = put_oi_by_strike.get(strike, 0) + oi
        
        # Determine regime
        regime = "POSITIVE_GAMMA" if total_gex > 0 else "NEGATIVE_GAMMA"
        
        # Find Zero Gamma Flip Level (where cumulative GEX crosses zero)
        flip_level = self._find_flip_level(gex_by_strike, spot_price)
        
        # Find Walls (strikes with max OI)
        call_wall = max(call_oi_by_strike.keys(), key=lambda k: call_oi_by_strike[k], default=0)
        put_wall = max(put_oi_by_strike.keys(), key=lambda k: put_oi_by_strike[k], default=0)
        
        return {
            'regime': regime,
            'net_gex': total_gex,
            'flip_level': flip_level,
            'call_wall': call_wall,
            'put_wall': put_wall
        }
    
    def _find_flip_level(self, gex_by_strike: Dict[float, float], spot_price: float) -> float:
        """
        Find the strike price where cumulative GEX flips from negative to positive.
        
        This is a critical level - below flip = amplified moves, above flip = stabilized.
        """
        if not gex_by_strike:
            return 0.0
        
        sorted_strikes = sorted(gex_by_strike.keys())
        cumulative_gex = 0.0
        
        for strike in sorted_strikes:
            prev_gex = cumulative_gex
            cumulative_gex += gex_by_strike[strike]
            
            # If sign changes, we crossed zero
            if prev_gex < 0 and cumulative_gex > 0:
                return strike
            elif prev_gex > 0 and cumulative_gex < 0:
                return strike
        
        # If no flip found, return closest strike to spot
        return min(sorted_strikes, key=lambda s: abs(s - spot_price), default=0.0)
    
    def get_context(self, ticker: str) -> Dict:
        """
        Get current market context for a ticker.
        
        Args:
            ticker: Symbol to look up
        
        Returns:
            Context dict with regime, GEX values, etc.
            Returns neutral defaults if ticker not tracked.
        """
        return self.state.get(ticker, {
            'regime': 'NEUTRAL',
            'net_gex': 0,
            'G': 0.5,
            'flip_level': 0,
            'call_wall': 0,
            'put_wall': 0,
            'spot_price': 0,
            'contracts_analyzed': 0,
            'last_updated': 0
        })
    
    def get_all_contexts(self) -> Dict[str, Dict]:
        """Get all tracked ticker contexts"""
        return self.state.copy()
    
    def is_negative_gamma(self, ticker: str) -> bool:
        """Check if ticker is in negative gamma regime (high vol environment)"""
        return self.get_context(ticker).get('regime') == 'NEGATIVE_GAMMA'
    
    def get_status(self) -> Dict:
        """Get engine status for monitoring"""
        return {
            'running': self._running,
            'tickers_tracked': len(self.tickers),
            'tickers_with_data': len(self.state),
            'update_interval': self.update_interval,
            'last_update': self._last_full_update
        }

