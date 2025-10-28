"""Golden Sweeps Bot - 1 Million+ premium sweeps"""
import logging
from datetime import datetime, timedelta
from typing import List, Dict
import pandas as pd
from .base_bot import BaseAutoBot
from src.data_fetcher import DataFetcher
from src.options_analyzer import OptionsAnalyzer
from src.config import Config
from src.utils.monitoring import signals_generated, timed
from src.utils.exceptions import DataException, handle_exception
from src.utils.enhanced_analysis import EnhancedAnalyzer, SmartDeduplicator
from src.utils.market_hours import MarketHours

logger = logging.getLogger(__name__)

class GoldenSweepsBot(BaseAutoBot):
    """
    Golden Sweeps Bot
    Tracks unusually large sweeps with premiums worth over 1 million dollars
    These represent massive conviction trades
    """

    def __init__(self, webhook_url: str, watchlist: List[str], fetcher: DataFetcher, analyzer: OptionsAnalyzer):
        super().__init__(webhook_url, "Golden Sweeps Bot", scan_interval=Config.GOLDEN_SWEEPS_INTERVAL)
        self.watchlist = watchlist
        self.fetcher = fetcher
        self.analyzer = analyzer
        self.signal_history = {}
        self.MIN_GOLDEN_PREMIUM = max(Config.GOLDEN_MIN_PREMIUM, 1_000_000)
        self.MIN_CONTRACT_VOLUME = 100
        self.MIN_VOLUME_DELTA = 100
        self.MAX_STRIKE_DISTANCE = 5  # percent
        self.MIN_SCORE = Config.MIN_GOLDEN_SCORE

        # Enhanced analysis tools
        self.enhanced_analyzer = EnhancedAnalyzer(fetcher)
        self.deduplicator = SmartDeduplicator()

    @timed()
    async def scan_and_post(self):
        """Scan for golden sweeps (1M+ premium) with enhanced analysis"""
        logger.info(f"{self.name} scanning for million dollar sweeps")

        # Only scan during market hours (9:30 AM - 4:00 PM EST, Monday-Friday)
        if not MarketHours.is_market_open(include_extended=False):
            logger.debug(f"{self.name} - Market closed, skipping scan")
            return
        
        # Use base class concurrent implementation
        await super().scan_and_post()
    
    async def _scan_symbol(self, symbol: str) -> List[Dict]:
        """Scan a symbol for golden sweeps with enhancements"""
        try:
            sweeps = await self._scan_golden_sweeps(symbol)

            enhanced_sweeps: List[Dict] = []
            for sweep in sweeps:
                try:
                    volume_ratio = await self.enhanced_analyzer.calculate_volume_ratio(
                        symbol, sweep['volume']
                    )
                    sweep['volume_ratio'] = volume_ratio

                    volume_boost = 0
                    if volume_ratio > 10:
                        volume_boost = 0.20
                    elif volume_ratio > 5:
                        volume_boost = 0.10

                    boosted_score = sweep.get('golden_score', 50) + int(volume_boost * 100)
                    sweep['golden_score'] = min(boosted_score, 100)
                except Exception as enhancement_error:
                    logger.debug(f"Golden sweep enhancement error for {symbol}: {enhancement_error}")

                signal_key = f"{symbol}_{sweep.get('type')}_{sweep.get('strike')}_{sweep.get('expiration')}"
                dedup_result = self.deduplicator.should_alert(signal_key, sweep.get('premium', 0))

                if not dedup_result.get('should_alert', True):
                    self._log_skip(symbol, dedup_result.get('reason', 'golden sweep deduplicated'))
                    continue

                if self._cooldown_active(signal_key):
                    self._log_skip(symbol, f'golden sweep cooldown {signal_key}')
                    continue

                sweep['alert_type'] = dedup_result.get('type', 'NEW')
                sweep['alert_reason'] = dedup_result.get('reason', '')
                self._mark_cooldown(signal_key)

                if sweep.get('golden_score', 0) >= self.MIN_SCORE:
                    enhanced_sweeps.append(sweep)

            return sorted(enhanced_sweeps, key=lambda x: x.get('golden_score', 0), reverse=True)[:3]
        except Exception as e:
            logger.error(f"Error scanning {symbol}: {e}")
            return []

    async def _scan_golden_sweeps(self, symbol: str) -> List[Dict]:
        """
        Scan for 1M+ premium sweeps using efficient REST flow detection.

        NEW APPROACH (REST):
        - Uses detect_unusual_flow() with $1M premium threshold
        - Volume delta analysis for massive flow detection
        - Smart strike filtering (≤5% OTM/ITM)
        """
        sweeps = []

        try:
            # Get current price for context
            current_price = await self.fetcher.get_stock_price(symbol)
            if not current_price:
                return sweeps

            # NEW: Use efficient flow detection (single API call)
            flows = await self.fetcher.detect_unusual_flow(
                underlying=symbol,
                min_premium=self.MIN_GOLDEN_PREMIUM,  # $1M minimum
                min_volume_delta=10  # At least 10 contracts of volume change
            )

            # Process each flow signal
            for flow in flows:
                # Extract flow data
                opt_type = flow['type']
                strike = flow['strike']
                expiration = flow['expiration']
                premium = flow['premium']
                total_volume = flow['total_volume']
                volume_delta = flow['volume_delta']

                if total_volume < 100 or volume_delta < 100:
                    self._log_skip(symbol, f"golden sweep volume too small ({total_volume} total / {volume_delta} delta)")
                    continue

                # Calculate DTE
                exp_date = datetime.strptime(expiration, '%Y-%m-%d')
                days_to_expiry = (exp_date - datetime.now()).days

                # Filter: Valid DTE range (1-180 days for golden sweeps)
                if days_to_expiry <= 0 or days_to_expiry > 180:
                    continue

                # Calculate strike distance
                strike_distance = ((strike - current_price) / current_price) * 100

                # Smart strike filtering (≤5% OTM/ITM only - no lottery tickets)
                if not self.is_smart_strike(strike, current_price, opt_type):
                    self._log_skip(symbol, f"golden sweep lottery strike distance {strike_distance:.1f}%")
                    continue

                # Calculate probability ITM
                prob_itm = self.analyzer.calculate_probability_itm(
                    opt_type, strike, current_price, days_to_expiry
                )

                # Moneyness analysis
                if opt_type == 'CALL':
                    moneyness = 'ITM' if strike < current_price else 'OTM' if strike > current_price else 'ATM'
                else:
                    moneyness = 'ITM' if strike > current_price else 'OTM' if strike < current_price else 'ATM'

                # Calculate golden score (estimate fills from volume)
                num_fills = max(5, int(volume_delta / 100))  # Estimate fills for massive orders
                golden_score = self._calculate_golden_score(
                    premium, total_volume, abs(strike_distance), days_to_expiry
                )

                # Only proceed if score meets minimum threshold
                if golden_score < self.MIN_SCORE:
                    continue

                # Create golden sweep signal
                sweep = {
                    'ticker': symbol,
                    'symbol': symbol,
                    'contract': flow.get('ticker'),
                    'type': opt_type,
                    'strike': strike,
                    'expiration': expiration,
                    'current_price': current_price,
                    'days_to_expiry': days_to_expiry,
                    'premium': premium,
                    'volume': total_volume,
                    'num_fills': num_fills,
                    'avg_price': premium / (total_volume * 100) if total_volume > 0 else 0,
                    'moneyness': moneyness,
                    'strike_distance': strike_distance,
                    'probability_itm': prob_itm,
                    'golden_score': golden_score,
                    'time_span': 0,  # Not available in REST
                    'volume_ratio': total_volume / 100,
                    'volume_delta': volume_delta,
                    'delta': flow.get('delta', 0),
                    'gamma': flow.get('gamma', 0),
                    'vega': flow.get('vega', 0),
                    # Note: Multi-exchange and urgency not available in REST snapshots
                    'exchanges_hit': 0,
                    'urgency': 'UNKNOWN',
                    'contracts_per_second': 0,
                    'urgency_score': 0
                }

                # CRITICAL FEATURE #4: Smart Deduplication (catches accumulation)
                signal_key = f"{symbol}_{opt_type}_{strike}_{expiration}"
                dedup_result = self.deduplicator.should_alert(signal_key, premium)

                if dedup_result['should_alert']:
                    sweep['alert_type'] = dedup_result['type']  # NEW, ACCUMULATION, REFRESH
                    sweep['alert_reason'] = dedup_result['reason']
                    sweeps.append(sweep)

                    logger.info(f"✅ Golden Sweep detected: {symbol} {opt_type} ${strike} - "
                              f"Premium:${premium:,.0f}, Score:{golden_score}/100")

        except Exception as e:
            logger.error(f"Error scanning golden sweeps for {symbol}: {e}")

        return sweeps

    def detect_multi_exchange(self, trades_df: pd.DataFrame) -> int:
        """PRD Enhancement: Count unique exchanges hit"""
        if 'exchange' not in trades_df.columns:
            return 1
        return trades_df['exchange'].nunique()

    def calculate_urgency(self, trades_df: pd.DataFrame) -> Dict:
        """PRD Enhancement: Calculate execution urgency (contracts per second)"""
        time_span = (trades_df['timestamp'].max() - trades_df['timestamp'].min()).total_seconds()
        total_contracts = trades_df['volume'].sum()

        contracts_per_sec = total_contracts / max(time_span, 1)

        if contracts_per_sec >= 200:
            return {'urgency': 'VERY HIGH', 'score': 1.0, 'cps': contracts_per_sec}
        elif contracts_per_sec >= 100:
            return {'urgency': 'HIGH', 'score': 0.8, 'cps': contracts_per_sec}
        elif contracts_per_sec >= 50:
            return {'urgency': 'MEDIUM', 'score': 0.6, 'cps': contracts_per_sec}
        else:
            return {'urgency': 'LOW', 'score': 0.4, 'cps': contracts_per_sec}

    def is_smart_strike(self, strike: float, current_price: float, option_type: str) -> bool:
        """PRD Enhancement: Filter lottery tickets (only ≤5% OTM/ITM allowed)"""
        distance_pct = abs((strike - current_price) / current_price) * 100

        # Only allow near-money strikes (≤5%)
        if distance_pct > 5.0:
            return False
        return True

    def _calculate_golden_score(self, premium: float, volume: int,
                                strike_distance: float, dte: int) -> int:
        """Calculate golden sweep score (0-100) using generic scoring system"""
        score = self.calculate_score({
            'premium': (premium, [
                (10000000, 50),  # $10M+ → 50 points (50%)
                (5000000, 45),   # $5M+ → 45 points
                (2500000, 40),   # $2.5M+ → 40 points
                (1000000, 35)    # $1M+ → 35 points
            ]),
            'volume': (volume, [
                (2000, 20),  # 2000+ → 20 points (20%)
                (1000, 17),  # 1000+ → 17 points
                (500, 14),   # 500+ → 14 points
                (0, 10)      # Default → 10 points
            ])
        })

        # Strike proximity (15%) - lower distance = higher score
        if strike_distance <= 3:
            score += 15
        elif strike_distance <= 7:
            score += 12
        elif strike_distance <= 15:
            score += 8

        # DTE factor (15%)
        if 7 <= dte <= 45:
            score += 15
        elif dte <= 90:
            score += 10
        else:
            score += 5

        return score

    async def _post_signal(self, sweep: Dict) -> bool:
        """Post enhanced golden sweep signal to Discord"""
        color = 0x00FF00 if sweep['type'] == 'CALL' else 0xFF0000

        # Format time
        now = datetime.now()
        time_str = now.strftime('%I:%M %p')
        date_str = now.strftime('%m/%d/%y')

        # Format expiration
        exp_str = sweep['expiration']

        # Format premium in millions
        premium_millions = sweep['premium'] / 1000000

        # Get enhanced score
        final_score = sweep.get('enhanced_score', sweep.get('final_score', sweep['golden_score']))

        # Determine contract symbol and sector (if provided)
        contract_symbol = (
            sweep.get('contract')
            or sweep.get('option_symbol')
            or sweep.get('contract_symbol')
            or "N/A"
        )
        sector = sweep.get('sector')

        # Format details string (contracts @ avg_price)
        details = f"{sweep['volume']:,} @ {sweep['avg_price']:.2f}"

        fields = [
            {"name": "Date", "value": date_str, "inline": True},
            {"name": "Time", "value": time_str, "inline": True},
            {"name": "Ticker", "value": sweep['symbol'], "inline": True},
            {"name": "Contract", "value": contract_symbol, "inline": False},
            {"name": "Exp", "value": exp_str, "inline": True},
            {"name": "Strike", "value": f"{sweep['strike']:.0f}", "inline": True},
            {"name": "C/P", "value": sweep['type'] + "S", "inline": True},
            {"name": "Spot", "value": f"{sweep['current_price']:.2f}", "inline": True},
            {"name": "Details", "value": details, "inline": True},
            {"name": "Type", "value": "SWEEP", "inline": True},
            {"name": "Prem", "value": f"${premium_millions:.1f}M", "inline": True},
            {"name": "Algo Score", "value": str(int(final_score)), "inline": True}
        ]

        if sector:
            fields.append({"name": "Sector", "value": sector, "inline": True})

        embed = self.create_signal_embed_with_disclaimer(
            title=f"🏆 {sweep['ticker']} - Golden Sweep Detected",
            description="",
            color=color,
            fields=fields,
            footer="ORAKL Bot - Golden Sweeps"
        )

        success = await self.post_to_discord(embed)
        if success:
            logger.info(f"🚨 GOLDEN SWEEP: {sweep['ticker']} {sweep['type']} ${sweep['strike']} Premium:${premium_millions:.1f}M Score:{int(final_score)}")

        return success
