"""
ORAKL Trade Enricher - Just-in-Time Data Augmentation

Receives filtered Kafka trade events and enriches them with
additional context from Polygon's single-contract snapshot API.

The Kafka message provides:
- Symbol, Premium, Strike, Type, Trade Size

This enricher adds:
- Current Bid/Ask (for spread analysis)
- Open Interest (for Vol/OI ratio)
- Day Volume (for volume ratio)
- Greeks (Delta, Gamma for HedgeHunter)
- Underlying Price (for OTM calculations)

Only 1 Polygon API call per trade that passes the pre-filter.
"""

import asyncio
import logging
from datetime import datetime
from typing import Dict, Optional, Any

from src.config import Config
from src.data_fetcher import DataFetcher

logger = logging.getLogger(__name__)


class TradeEnricher:
    """
    Enriches Kafka trade events with Polygon contract snapshot data.
    
    Flow:
    1. Receive trade event (already filtered by $100K+ premium)
    2. Extract underlying symbol and contract ticker
    3. Fetch single contract snapshot from Polygon
    4. Merge trade data with snapshot data
    5. Return enriched object ready for bot processing
    
    Usage:
        enricher = TradeEnricher(data_fetcher)
        enriched = await enricher.enrich(trade_event)
        if enriched:
            await bot_manager.process_single_event(enriched)
    """
    
    def __init__(self, fetcher: DataFetcher):
        """
        Initialize enricher with data fetcher.
        
        Args:
            fetcher: DataFetcher instance for Polygon API calls
        """
        self.fetcher = fetcher
        self.timeout = Config.KAFKA_ENRICHMENT_TIMEOUT
        
        # Stats tracking
        self.total_enrichments = 0
        self.successful_enrichments = 0
        self.failed_enrichments = 0
        self.timeouts = 0
    
    def _clean_contract_ticker(self, raw_ticker: str) -> str:
        """
        Strip O: prefix if present for Polygon API compatibility.
        
        Args:
            raw_ticker: Contract ticker, e.g., "O:AAPL240216C00185000"
            
        Returns:
            Cleaned ticker, e.g., "AAPL240216C00185000"
        """
        if raw_ticker.startswith('O:'):
            return raw_ticker[2:]
        return raw_ticker
    
    def _extract_underlying(self, contract_ticker: str) -> str:
        """
        Extract underlying symbol from options contract ticker.
        
        Args:
            contract_ticker: e.g., "AAPL240216C00185000"
            
        Returns:
            Underlying symbol, e.g., "AAPL"
        """
        # Clean first
        ticker = self._clean_contract_ticker(contract_ticker)
        
        # Extract alphabetic prefix (underlying symbol)
        underlying = ''
        for char in ticker:
            if char.isalpha():
                underlying += char
            else:
                break
        
        return underlying if underlying else ticker[:4]  # Fallback to first 4 chars
    
    async def enrich(self, trade_data: Dict) -> Optional[Dict]:
        """
        Enrich a Kafka trade event with Polygon snapshot data.
        
        Args:
            trade_data: Trade event from Kafka listener
            
        Returns:
            Enriched trade dict with Greeks, OI, Bid/Ask, etc.
            Returns None if enrichment fails.
        """
        self.total_enrichments += 1
        
        # Get contract ticker
        contract_ticker = trade_data.get('contract_ticker', '')
        if not contract_ticker:
            logger.warning("Trade event missing contract_ticker, cannot enrich")
            self.failed_enrichments += 1
            return None
        
        # Clean and extract
        clean_ticker = self._clean_contract_ticker(contract_ticker)
        underlying = trade_data.get('symbol') or self._extract_underlying(contract_ticker)
        
        try:
            # Fetch single contract snapshot with timeout
            snapshot = await asyncio.wait_for(
                self.fetcher.get_single_option_snapshot(underlying, clean_ticker),
                timeout=self.timeout
            )
            
            if not snapshot:
                logger.debug(f"No snapshot data for {clean_ticker}")
                self.failed_enrichments += 1
                # Return original data without enrichment
                return self._build_minimal_enriched(trade_data, underlying)
            
            # Merge trade data with snapshot
            enriched = self._merge_data(trade_data, snapshot, underlying)
            self.successful_enrichments += 1
            
            logger.debug(
                f"Enriched {underlying} trade: premium=${trade_data.get('premium', 0):,.0f}, "
                f"OI={enriched.get('open_interest', 0)}, delta={enriched.get('delta', 0):.2f}"
            )
            
            return enriched
            
        except asyncio.TimeoutError:
            logger.warning(f"Enrichment timeout for {clean_ticker} ({self.timeout}s)")
            self.timeouts += 1
            self.failed_enrichments += 1
            # Return original data without enrichment (better than nothing)
            return self._build_minimal_enriched(trade_data, underlying)
            
        except Exception as e:
            logger.error(f"Error enriching {clean_ticker}: {e}")
            self.failed_enrichments += 1
            return self._build_minimal_enriched(trade_data, underlying)
    
    def _merge_data(self, trade_data: Dict, snapshot: Dict, underlying: str) -> Dict:
        """
        Merge Kafka trade data with Polygon snapshot data.
        
        Args:
            trade_data: Original trade event from Kafka
            snapshot: Contract snapshot from Polygon
            underlying: Underlying symbol
            
        Returns:
            Merged enriched trade dict
        """
        # Start with trade data
        enriched = dict(trade_data)
        enriched['underlying'] = underlying
        enriched['enriched'] = True
        enriched['enriched_at'] = datetime.utcnow().isoformat()
        
        # Extract data from snapshot (handle nested structure)
        # Polygon snapshot format can vary, handle both flat and nested
        
        # Greeks
        greeks = snapshot.get('greeks', {}) or {}
        enriched['delta'] = greeks.get('delta', 0.0)
        enriched['gamma'] = greeks.get('gamma', 0.0)
        enriched['theta'] = greeks.get('theta', 0.0)
        enriched['vega'] = greeks.get('vega', 0.0)
        enriched['iv'] = snapshot.get('implied_volatility', greeks.get('iv', 0.0))
        
        # Quote data
        last_quote = snapshot.get('last_quote', {}) or {}
        enriched['current_bid'] = last_quote.get('bid', snapshot.get('bid', 0.0))
        enriched['current_ask'] = last_quote.get('ask', snapshot.get('ask', 0.0))
        enriched['bid_size'] = last_quote.get('bid_size', 0)
        enriched['ask_size'] = last_quote.get('ask_size', 0)
        
        # Calculate spread
        bid = enriched['current_bid'] or 0
        ask = enriched['current_ask'] or 0
        if bid > 0 and ask > 0:
            enriched['spread'] = ask - bid
            enriched['spread_pct'] = (ask - bid) / ((ask + bid) / 2) * 100
        else:
            enriched['spread'] = 0
            enriched['spread_pct'] = 0
        
        # Volume and OI
        day_data = snapshot.get('day', {}) or {}
        enriched['day_volume'] = day_data.get('volume', snapshot.get('volume', 0))
        enriched['open_interest'] = snapshot.get('open_interest', 0)
        
        # Volume/OI ratio (critical for sweep detection)
        oi = enriched['open_interest']
        vol = enriched['day_volume']
        enriched['vol_oi_ratio'] = vol / oi if oi > 0 else 0
        
        # Underlying data
        underlying_data = snapshot.get('underlying_asset', {}) or {}
        enriched['underlying_price'] = (
            underlying_data.get('price') or 
            underlying_data.get('last_price') or
            snapshot.get('underlying_price', 0)
        )
        
        # Contract details
        details = snapshot.get('details', {}) or {}
        enriched['expiration_date'] = details.get('expiration_date', enriched.get('expiration_date'))
        enriched['strike_price'] = details.get('strike_price', enriched.get('strike_price', 0))
        enriched['contract_type'] = details.get('contract_type', enriched.get('contract_type', '')).lower()
        
        # Calculate OTM percentage if we have underlying price
        if enriched['underlying_price'] and enriched['strike_price']:
            strike = float(enriched['strike_price'])
            spot = float(enriched['underlying_price'])
            if enriched['contract_type'] == 'call':
                enriched['otm_pct'] = max(0, (strike - spot) / spot) if spot > 0 else 0
            else:
                enriched['otm_pct'] = max(0, (spot - strike) / spot) if spot > 0 else 0
        else:
            enriched['otm_pct'] = 0
        
        # Calculate DTE if we have expiration
        if enriched.get('expiration_date'):
            try:
                exp = datetime.strptime(enriched['expiration_date'], '%Y-%m-%d')
                now = datetime.now()
                enriched['dte'] = max(0, (exp - now).days)
            except (ValueError, TypeError):
                enriched['dte'] = 0
        else:
            enriched['dte'] = 0
        
        return enriched
    
    def _build_minimal_enriched(self, trade_data: Dict, underlying: str) -> Dict:
        """
        Build minimal enriched object when snapshot fetch fails.
        
        This allows processing to continue with available data,
        though some bot filters may reject due to missing fields.
        """
        enriched = dict(trade_data)
        enriched['underlying'] = underlying
        enriched['enriched'] = False
        enriched['enriched_at'] = datetime.utcnow().isoformat()
        
        # Set defaults for missing fields
        enriched.setdefault('delta', 0.0)
        enriched.setdefault('gamma', 0.0)
        enriched.setdefault('open_interest', 0)
        enriched.setdefault('day_volume', 0)
        enriched.setdefault('current_bid', 0.0)
        enriched.setdefault('current_ask', 0.0)
        enriched.setdefault('underlying_price', 0.0)
        enriched.setdefault('vol_oi_ratio', 0.0)
        enriched.setdefault('otm_pct', 0.0)
        enriched.setdefault('dte', 0)
        
        return enriched
    
    def get_stats(self) -> Dict[str, Any]:
        """Get enricher statistics"""
        return {
            'total_enrichments': self.total_enrichments,
            'successful': self.successful_enrichments,
            'failed': self.failed_enrichments,
            'timeouts': self.timeouts,
            'success_rate': self.successful_enrichments / max(1, self.total_enrichments)
        }

