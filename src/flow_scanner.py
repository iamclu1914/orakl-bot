"""
ORAKL Flow Scanner
Automated scanner for detecting high-probability options flow signals
"""

import asyncio
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import logging
from collections import defaultdict
import pandas as pd
from src.config import Config
from src.data_fetcher import DataFetcher
from src.options_analyzer import OptionsAnalyzer

logger = logging.getLogger(__name__)

class ORAKLFlowScanner:
    """ORAKL Flow automatic scanner for unusual options activity"""
    
    def __init__(self, data_fetcher: DataFetcher, analyzer: OptionsAnalyzer):
        self.fetcher = data_fetcher
        self.analyzer = analyzer
        self.scan_history = defaultdict(list)
        self.alert_history = defaultdict(set)  # Prevent duplicate alerts
        
    async def scan_symbol(self, symbol: str) -> List[Dict]:
        """Scan a single symbol for ORAKL signals"""
        signals = []
        
        try:
            # Get current stock price
            current_price = await self.fetcher.get_stock_price(symbol)
            if not current_price:
                logger.warning(f"Could not get price for {symbol}")
                return signals
                
            # Get options trades
            trades = await self.fetcher.get_options_trades(symbol)
            if trades.empty:
                return signals
                
            # Analyze flow
            flow_analysis = self.analyzer.analyze_flow(trades)
            
            # Filter for significant trades
            significant_trades = trades[
                (trades['premium'] >= Config.MIN_PREMIUM) &
                (trades['volume'] >= Config.MIN_VOLUME)
            ]
            
            # Group by contract
            for (contract, option_type, strike, expiration), group in significant_trades.groupby(
                ['contract', 'type', 'strike', 'expiration']
            ):
                total_premium = group['premium'].sum()
                total_volume = group['volume'].sum()
                avg_price = group['price'].mean()
                
                # Check for minimum thresholds
                if total_premium < Config.MIN_PREMIUM:
                    continue
                    
                # Calculate days to expiry
                exp_date = pd.to_datetime(expiration)
                days_to_expiry = (exp_date - datetime.now()).days
                
                # Skip if too far out or expired
                if days_to_expiry > 45 or days_to_expiry < 0:
                    continue
                    
                # Calculate probability ITM
                probability_itm = self.analyzer.calculate_probability_itm(
                    option_type, strike, current_price, days_to_expiry
                )
                
                # Check for repeat signals
                repeat_count = self.analyzer.identify_repeat_signals(
                    symbol, strike, option_type, expiration, total_premium
                )
                
                # Get historical success rate
                success_rate = self.analyzer.calculate_success_rate(symbol)
                
                # Determine if this is a high-probability signal
                if (probability_itm >= Config.SUCCESS_RATE_THRESHOLD * 100 and
                    repeat_count >= Config.REPEAT_SIGNAL_THRESHOLD):
                    
                    # Create signal
                    signal = {
                        'ticker': symbol,
                        'contract': contract,
                        'type': option_type,
                        'strike': strike,
                        'expiration': expiration,
                        'current_price': current_price,
                        'days_to_expiry': days_to_expiry,
                        'total_premium': total_premium,
                        'volume': total_volume,
                        'avg_price': avg_price,
                        'probability_itm': probability_itm,
                        'repeat_count': repeat_count,
                        'success_rate': success_rate,
                        'signal_strength': self._calculate_signal_strength(
                            probability_itm, repeat_count, total_premium
                        ),
                        'timestamp': datetime.now(),
                        'open_interest': 0  # Would need additional API call
                    }
                    
                    # Check if we've already alerted on this
                    alert_key = f"{symbol}_{option_type}_{strike}_{expiration}"
                    if alert_key not in self.alert_history[symbol]:
                        signals.append(signal)
                        self.alert_history[symbol].add(alert_key)
                        
        except Exception as e:
            logger.error(f"Error scanning {symbol}: {e}")
            
        return signals
        
    async def scan_all(self) -> List[Dict]:
        """Scan all symbols in watchlist"""
        logger.info(f"Starting ORAKL scan of {len(Config.WATCHLIST)} symbols")
        
        # Check if market is open
        is_open = await self.fetcher.is_market_open()
        if not is_open:
            logger.info("Market is closed, skipping scan")
            return []
            
        all_signals = []
        
        # Scan symbols concurrently
        tasks = []
        for symbol in Config.WATCHLIST:
            tasks.append(self.scan_symbol(symbol))
            
        # Wait for all scans with timeout
        try:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    logger.error(f"Scan failed for {Config.WATCHLIST[i]}: {result}")
                elif result:
                    all_signals.extend(result)
                    
        except asyncio.TimeoutError:
            logger.error("Scan timeout exceeded")
            
        # Rank signals
        if all_signals:
            all_signals = self.analyzer.rank_signals(all_signals)
            logger.info(f"Found {len(all_signals)} ORAKL signals")
            
        # Clean up old alerts (>24 hours)
        self._cleanup_alert_history()
        
        return all_signals
        
    async def scan_unusual_activity(self) -> List[Dict]:
        """Scan for unusual options activity across all contracts"""
        logger.info("Scanning for unusual options activity")
        
        try:
            unusual = await self.fetcher.get_unusual_options(
                min_volume=Config.MIN_VOLUME,
                min_premium=Config.MIN_PREMIUM
            )
            
            # Filter and enhance signals
            enhanced_signals = []
            for activity in unusual:
                # Get current price
                current_price = await self.fetcher.get_stock_price(activity['underlying'])
                if not current_price:
                    continue
                    
                # Calculate probability
                days_to_expiry = (pd.to_datetime(activity['expiration']) - datetime.now()).days
                probability_itm = self.analyzer.calculate_probability_itm(
                    activity['type'],
                    activity['strike'],
                    current_price,
                    days_to_expiry,
                    activity.get('implied_volatility', 0.3)
                )
                
                # Add enhanced data
                activity['current_price'] = current_price
                activity['probability_itm'] = probability_itm
                activity['days_to_expiry'] = days_to_expiry
                
                # Check thresholds
                if (activity['vol_oi_ratio'] >= Config.UNUSUAL_VOLUME_MULTIPLIER and
                    probability_itm >= Config.SUCCESS_RATE_THRESHOLD * 100):
                    enhanced_signals.append(activity)
                    
            return enhanced_signals
            
        except Exception as e:
            logger.error(f"Error scanning unusual activity: {e}")
            return []
            
    def _calculate_signal_strength(self, probability: float, repeat_count: int, 
                                 premium: float) -> str:
        """Calculate signal strength rating"""
        score = 0
        
        # Probability component (40%)
        if probability >= 80:
            score += 40
        elif probability >= 70:
            score += 30
        elif probability >= 65:
            score += 20
            
        # Repeat signal component (30%)
        if repeat_count >= 5:
            score += 30
        elif repeat_count >= 3:
            score += 20
        elif repeat_count >= 2:
            score += 10
            
        # Premium component (30%)
        if premium >= 100000:
            score += 30
        elif premium >= 50000:
            score += 20
        elif premium >= 25000:
            score += 10
            
        # Determine strength
        if score >= 70:
            return "STRONG"
        elif score >= 50:
            return "MODERATE"
        else:
            return "WEAK"
            
    def _cleanup_alert_history(self):
        """Clean up old alerts from history"""
        cutoff = datetime.now() - timedelta(hours=24)
        
        for symbol in list(self.alert_history.keys()):
            # For simplicity, clear all alerts older than 24 hours
            # In production, you'd track timestamps for each alert
            if symbol in self.scan_history:
                recent_scans = [s for s in self.scan_history[symbol] if s > cutoff]
                if not recent_scans:
                    del self.alert_history[symbol]
                    
    async def get_flow_summary(self, symbol: str) -> Dict:
        """Get comprehensive flow summary for a symbol"""
        try:
            # Get trades
            trades = await self.fetcher.get_options_trades(symbol)
            
            # Get snapshot
            snapshot = await self.fetcher.get_options_snapshot(symbol)
            
            # Analyze flow
            flow_analysis = self.analyzer.analyze_flow(trades)
            sentiment = self.analyzer.calculate_flow_sentiment(symbol, trades)
            
            # Combine all data
            summary = {
                'symbol': symbol,
                'timestamp': datetime.now(),
                'current_price': snapshot.get('underlying_price', 0),
                'flow_analysis': flow_analysis,
                'sentiment': sentiment,
                'snapshot': snapshot,
                'top_trades': trades.nlargest(5, 'premium').to_dict('records') if not trades.empty else []
            }
            
            return summary
            
        except Exception as e:
            logger.error(f"Error getting flow summary for {symbol}: {e}")
            return {}
