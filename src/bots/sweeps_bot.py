"""Sweeps Bot - Large options sweeps tracker

Independent scanning - each bot scans its own watchlist directly.
Uses base class batching for efficient concurrent API calls.
"""
import asyncio
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import pandas as pd
from .base_bot import BaseAutoBot
from src.data_fetcher import DataFetcher
from src.options_analyzer import OptionsAnalyzer
from src.config import Config
from src.utils.monitoring import signals_generated, timed
from src.utils.exceptions import DataException, handle_exception
from src.utils.enhanced_analysis import EnhancedAnalyzer, SmartDeduplicator
from src.utils.market_hours import MarketHours
from src.utils.option_contract_format import format_option_contract_pretty, normalize_option_ticker
# Removed FlowCache - each bot scans independently now

logger = logging.getLogger(__name__)

class SweepsBot(BaseAutoBot):
    """
    Sweeps Bot
    High premium large options sweeps showing conviction buyers
    Tracks aggressive market orders that sweep the order book
    
    ORAKL v3.0: Now includes Brain validation (HedgeHunter + ContextManager)
    """

    def __init__(
        self, 
        webhook_url: str, 
        watchlist: List[str], 
        fetcher: DataFetcher, 
        analyzer: OptionsAnalyzer,
        hedge_hunter: Optional[object] = None,
        context_manager: Optional[object] = None
    ):
        super().__init__(
            webhook_url, 
            "Sweeps Bot", 
            scan_interval=Config.SWEEPS_INTERVAL,
            hedge_hunter=hedge_hunter,
            context_manager=context_manager
        )
        self.watchlist = watchlist
        self.fetcher = fetcher
        self.analyzer = analyzer
        self.signal_history = {}
        # IMPORTANT: Respect config/env. Do NOT hard-force $750k; that can suppress alerts all day.
        self.MIN_SWEEP_PREMIUM = float(Config.SWEEPS_MIN_PREMIUM)
        self.MAX_SWEEP_PREMIUM = Config.GOLDEN_MIN_PREMIUM  # Sweeps >= this go to Golden Sweeps
        # Loosen volume gates so medium-size sweeps can alert.
        self.MIN_VOLUME = max(getattr(Config, "SWEEPS_MIN_VOLUME", 0), 100)
        self.MIN_VOLUME_DELTA = max(getattr(Config, "SWEEPS_MIN_VOLUME_DELTA", 0), 50)
        # Full scan mode - scan ALL symbols every cycle (no batching)
        self.scan_batch_size = 0  # 0 = full scan
        self.concurrency_limit = 30  # High concurrency for speed
        self.MAX_STRIKE_DISTANCE = getattr(Config, 'SWEEPS_MAX_STRIKE_DISTANCE', 0.06) * 100  # 6% from config
        # Require a high conviction sweep score before alerting (env override supported)
        self.MIN_SCORE = int(Config.MIN_SWEEP_SCORE)
        self.MIN_VOLUME_RATIO = max(Config.SWEEPS_MIN_VOLUME_RATIO, 1.3)  # 1.3x minimum
        # Disable price-action alignment for standard sweeps (alignment proved too restrictive)
        self.SKIP_ALIGNMENT_CHECK = True
        self.MIN_ALIGNMENT_CONFIDENCE = max(Config.SWEEPS_MIN_ALIGNMENT_CONFIDENCE, 20)
        self.PRICE_ALIGNMENT_OVERRIDE_PREMIUM = 1000000  # $1M to override alignment
        self.PRICE_ALIGNMENT_OVERRIDE_VOI = 2.5
        self.VOLUME_RATIO_FLEX_MULTIPLIER = 0.85  # allow 15% flexibility when premium is massive
        # Tiered strike distance overrides based on premium size
        self.STRIKE_DISTANCE_OVERRIDE_PREMIUM = 750000  # Base tier for extension (raised)
        self.STRIKE_DISTANCE_EXTENSION = 4  # percent (reduced from 6)
        self.STRIKE_DISTANCE_PREMIUM_TIERS = [
            (1500000, 15),   # $1.5M+ allows 15% OTM
            (1000000, 12),   # $1M+ allows 12% OTM
        ]
        # Short DTE gets wider allowance (0-3 DTE allows +5% more)
        self.SHORT_DTE_STRIKE_EXTENSION = 5  # percent
        self.SHORT_DTE_THRESHOLD = 3  # days
        self.TOP_SWEEPS_PER_SYMBOL = 1
        self.symbol_cooldown_seconds = getattr(Config, 'SWEEPS_COOLDOWN_SECONDS', 1800)  # 30 min from config
        self.max_alerts_per_scan = getattr(Config, 'SWEEPS_MAX_ALERTS_PER_SCAN', 2)  # Max 2 per scan

        # Enhanced analysis tools
        self.enhanced_analyzer = EnhancedAnalyzer(fetcher)
        self.deduplicator = SmartDeduplicator()
        
        # Golden sweeps fallback tracking
        self._golden_bot_last_healthy: Optional[datetime] = None
        self._golden_fallback_threshold_seconds = 600  # 10 minutes without golden = emit fallback

    # =========================================================================
    # ORAKL v2.0: Kafka Event Processing
    # =========================================================================
    
    async def process_event(self, enriched_trade: Dict) -> Optional[Dict]:
        """
        Process a single enriched trade event from Kafka.
        
        Evaluates if the trade qualifies as a sweep alert based on:
        - Premium threshold ($750K - $1M for Sweeps, $1M+ goes to Golden)
        - Strike distance from spot
        - Volume/OI ratio
        - Cooldown check
        
        Args:
            enriched_trade: Trade data enriched with Greeks, OI, Bid/Ask
            
        Returns:
            Alert payload dict if trade qualifies, None otherwise
        """
        try:
            symbol = enriched_trade.get('symbol', '')
            premium = float(enriched_trade.get('premium', 0))
            
            # Skip if below minimum premium
            if premium < self.MIN_SWEEP_PREMIUM:
                self._count_filter("premium_below_min")
                return None
            
            # Skip if above max (should go to Golden Sweeps)
            if premium >= self.MAX_SWEEP_PREMIUM:
                self._count_filter("premium_routed_to_golden")
                logger.debug(f"{self.name} skipping {symbol} - premium ${premium:,.0f} >= Golden threshold")
                return None
            
            # Extract key fields
            strike = float(enriched_trade.get('strike_price', 0))
            underlying_price = float(enriched_trade.get('underlying_price', 0))
            contract_type = enriched_trade.get('contract_type', '').upper()
            open_interest = int(enriched_trade.get('open_interest', 0))
            day_volume = int(enriched_trade.get('day_volume', 0))
            trade_size = int(enriched_trade.get('trade_size', 0))
            delta = float(enriched_trade.get('delta', 0))
            dte = int(enriched_trade.get('dte', 0))
            
            # Validate required fields (count specific missing reasons so we can debug quickly)
            if not symbol:
                self._count_filter("missing_symbol")
                return None
            if strike <= 0:
                self._count_filter("missing_strike")
                return None
            if not contract_type:
                self._count_filter("missing_contract_type")
                return None
            if not enriched_trade.get('expiration_date'):
                self._count_filter("missing_expiration_date")
                return None
            
            # Calculate strike distance (underlying price is required for all strike/moneyness logic)
            if underlying_price <= 0:
                self._count_filter("missing_underlying_price")
                return None
            strike_distance = abs(strike - underlying_price) / underlying_price * 100
            
            # Calculate effective max strike distance
            max_strike_distance = self.MAX_STRIKE_DISTANCE
            
            # Tiered extension based on premium
            for tier_premium, tier_extension in self.STRIKE_DISTANCE_PREMIUM_TIERS:
                if premium >= tier_premium:
                    max_strike_distance = tier_extension
                    break
            
            # Short DTE extension
            if dte <= self.SHORT_DTE_THRESHOLD:
                max_strike_distance += self.SHORT_DTE_STRIKE_EXTENSION
            
            # Check strike distance
            if strike_distance > max_strike_distance:
                self._log_skip(symbol, f"strike distance {strike_distance:.1f}% > max {max_strike_distance:.1f}%")
                return None
            
            # Calculate volume/OI ratio
            if open_interest > 0:
                vol_oi_ratio = day_volume / open_interest
            else:
                vol_oi_ratio = 1.0
            
            # Check volume ratio
            if vol_oi_ratio < self.MIN_VOLUME_RATIO:
                # Allow flexibility for massive premiums
                flex_threshold = self.MIN_VOLUME_RATIO * self.VOLUME_RATIO_FLEX_MULTIPLIER
                if not (premium >= self.STRIKE_DISTANCE_OVERRIDE_PREMIUM and vol_oi_ratio >= flex_threshold):
                    self._log_skip(symbol, f"vol/OI ratio {vol_oi_ratio:.2f}x < {self.MIN_VOLUME_RATIO:.2f}x")
                    return None
            
            # Check cooldown
            cooldown_key = f"{symbol}_{contract_type}_{strike}_{enriched_trade.get('expiration_date', '')}"
            if self._cooldown_active(cooldown_key, self.symbol_cooldown_seconds):
                self._log_skip(symbol, "cooldown active")
                return None
            
            # Calculate sweep score (Kafka/event mode)
            score = self._calculate_sweep_score_event(enriched_trade, vol_oi_ratio, strike_distance)
            
            if score < self.MIN_SCORE:
                self._log_skip(symbol, f"score {score} < min {self.MIN_SCORE}")
                return None
            
            # Derive an average/print price for display (prefer actual trade price).
            # premium ≈ price * contracts * 100
            derived_price = 0.0
            try:
                derived_price = float(enriched_trade.get('trade_price') or 0.0)
            except (TypeError, ValueError):
                derived_price = 0.0
            if derived_price <= 0:
                try:
                    derived_price = float(premium) / max(float(trade_size) * 100.0, 1.0)
                except Exception:
                    derived_price = 0.0

            # Build sweep data structure
            sweep = {
                # Normalized keys expected by embed/posting logic (shared with scan-based path)
                'ticker': symbol,
                'symbol': symbol,
                'type': contract_type if contract_type in ['CALL', 'PUT'] else 'CALL',
                'strike': strike,
                'expiration': enriched_trade.get('expiration_date', ''),
                'premium': premium,
                # In Kafka mode, "size" should represent the trade size (contracts), not day volume.
                'volume': trade_size,
                'day_volume': day_volume,
                'volume_delta': trade_size,
                'open_interest': open_interest,
                'vol_oi_ratio': vol_oi_ratio,
                'volume_ratio': vol_oi_ratio,
                'underlying_price': underlying_price,
                'current_price': underlying_price,
                'strike_distance': strike_distance,
                'delta': delta,
                'dte': dte,
                'days_to_expiry': dte,
                'moneyness': self._classify_moneyness(strike, underlying_price, contract_type),
                'score': score,
                'sweep_score': score,
                'execution_type': 'SWEEP',
                # Display helpers used by GoldenSweepsBot embed
                'avg_price': derived_price,
                'details': f"{trade_size}@{derived_price:.2f}" if derived_price > 0 else f"{trade_size}@?",
                'contract_price': derived_price,
                'num_fills': 1,
                'contract': enriched_trade.get('contract_ticker') or enriched_trade.get('contract') or enriched_trade.get('option_symbol'),
                'kafka_event': True,
                'event_timestamp': enriched_trade.get('event_timestamp'),
            }
            
            # Mark cooldown
            self._mark_cooldown(cooldown_key)
            
            # Post the signal
            await self._post_signal(sweep)
            
            logger.info(f"{self.name} ALERT: {symbol} {contract_type} sweep ${premium:,.0f} score={score}")
            
            return sweep
            
        except Exception as e:
            logger.error(f"{self.name} error processing event: {e}")
            return None
    
    def _calculate_sweep_score_event(self, trade: Dict, vol_oi_ratio: float, strike_distance: float) -> int:
        """Calculate conviction score for a sweep trade (Kafka/event mode)."""
        score = 50  # Base score
        
        premium = float(trade.get('premium', 0))
        delta = abs(float(trade.get('delta', 0)))
        dte = int(trade.get('dte', 0))
        
        # Premium tiers
        if premium >= 1000000:
            score += 25
        elif premium >= 800000:
            score += 20
        elif premium >= 750000:
            score += 15
        
        # Volume/OI ratio
        if vol_oi_ratio >= 3.0:
            score += 15
        elif vol_oi_ratio >= 2.0:
            score += 10
        elif vol_oi_ratio >= 1.5:
            score += 5
        
        # Strike distance (closer is better)
        if strike_distance < 2.0:
            score += 10
        elif strike_distance < 5.0:
            score += 5
        
        # Delta (ATM range preferred)
        if 0.35 <= delta <= 0.65:
            score += 10
        elif 0.25 <= delta <= 0.75:
            score += 5
        
        # DTE (short-term = higher conviction)
        if 0 < dte <= 7:
            score += 10
        elif 7 < dte <= 14:
            score += 5
        
        return min(score, 100)
    
    def _classify_moneyness(self, strike: float, spot: float, option_type: str) -> str:
        """Classify option as ITM, ATM, or OTM."""
        if spot <= 0:
            return 'ATM'
        
        distance = abs(strike - spot) / spot
        
        if distance < 0.02:
            return 'ATM'
        
        if option_type == 'CALL':
            return 'ITM' if strike < spot else 'OTM'
        else:
            return 'ITM' if strike > spot else 'OTM'

    @timed()
    async def scan_and_post(self):
        """
        Full scan - scans ALL watchlist symbols every cycle for large sweeps.
        """
        logger.info(f"{self.name} starting full scan of {len(self.watchlist)} symbols")

        # Only scan during market hours (9:30 AM - 4:00 PM EST, Monday-Friday)
        if not MarketHours.is_market_open(include_extended=False):
            logger.debug(f"{self.name} - Market closed, skipping scan")
            self.deduplicator.cleanup_old_signals()
            return
        
        # Full scan - all symbols at once with concurrency control
        all_sweeps = []
        max_alerts = self.max_alerts_per_scan  # Limit alerts per cycle (from config)
        
        semaphore = asyncio.Semaphore(self.concurrency_limit)
        
        async def scan_with_limit(symbol: str):
            async with semaphore:
                return await self._scan_symbol(symbol)
        
        tasks = [scan_with_limit(symbol) for symbol in self.watchlist]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for result in results:
            if isinstance(result, list):
                all_sweeps.extend(result)
        
        logger.info(f"{self.name} found {len(all_sweeps)} sweep candidates from watchlist")
        
        # Sort by enhanced score and post top signals
        all_sweeps.sort(key=lambda x: x.get('enhanced_score', x.get('sweep_score', 0)), reverse=True)
        
        posted = 0
        for sweep in all_sweeps[:max_alerts]:
            try:
                success = await self._post_signal(sweep)
                if success:
                    posted += 1
                    # Add delay between posts to avoid Discord rate limits
                    if posted < max_alerts:
                        await asyncio.sleep(1.5)
            except Exception as e:
                logger.error(f"{self.name} error posting signal: {e}")
        
        logger.info(f"{self.name} scan complete - posted {posted} alerts")
        
        # Periodic cleanup
        self.deduplicator.cleanup_old_signals()
    
    async def _scan_symbol(self, symbol: str) -> List[Dict]:
        """
        Scan a symbol for large sweeps using efficient REST flow detection.

        NEW APPROACH (REST):
        - Uses detect_unusual_flow() with $50K premium threshold
        - Volume delta analysis for sweep detection
        - Enhanced with volume ratio and score boosting
        """
        try:
            sweeps = await self._scan_sweeps(symbol)

            # Enhance and filter signals
            enhanced_sweeps = []
            for sweep in sweeps:
                try:
                    # Volume Ratio Analysis (prefer option metrics, fallback to neutral)
                    volume_ratio_source = "vol_oi_delta"
                    ratio_data_available = False
                    raw_ratio = sweep.get("vol_oi_ratio") or 0.0
                    if raw_ratio and raw_ratio > 0:
                        ratio_data_available = True
                        volume_ratio = float(raw_ratio)
                    else:
                        open_interest = sweep.get("open_interest")
                        if open_interest and open_interest > 0:
                            volume_ratio = sweep["volume"] / open_interest
                            ratio_data_available = True
                            volume_ratio_source = "volume_over_oi"
                        else:
                            volume_ratio = await self.enhanced_analyzer.calculate_volume_ratio(
                                symbol, sweep["volume"]
                            )
                            volume_ratio_source = "fallback"
                            if not volume_ratio or volume_ratio <= 0:
                                volume_ratio = 1.0

                    sweep["volume_ratio"] = round(float(volume_ratio), 2)
                    sweep["volume_ratio_source"] = volume_ratio_source
                    sweep["volume_ratio_data_available"] = ratio_data_available

                    # Skip volume ratio check if SKIP_VOLUME_RATIO_CHECK is set (e.g., Golden Sweeps)
                    # For $1M+ sweeps, premium size IS the conviction signal
                    skip_volume_ratio = getattr(self, 'SKIP_VOLUME_RATIO_CHECK', False)

                    if not skip_volume_ratio and ratio_data_available and sweep["volume_ratio"] < self.MIN_VOLUME_RATIO:
                        flex_threshold = self.MIN_VOLUME_RATIO * self.VOLUME_RATIO_FLEX_MULTIPLIER
                        if not (
                            sweep["premium"] >= self.STRIKE_DISTANCE_OVERRIDE_PREMIUM
                            and sweep["volume_ratio"] >= flex_threshold
                        ):
                            self._log_skip(
                                symbol,
                                f"volume ratio {sweep['volume_ratio']:.2f}x < {self.MIN_VOLUME_RATIO:.2f}x",
                            )
                            continue

                    # Price action alignment check (fallback to neutral if data unavailable)
                    # Skip alignment check entirely if SKIP_ALIGNMENT_CHECK is set (e.g., Golden Sweeps)
                    skip_alignment = getattr(self, 'SKIP_ALIGNMENT_CHECK', False)
                    
                    if skip_alignment:
                        # Bypass alignment - premium size IS the conviction signal
                        price_aligned = True
                        alignment_confidence = 100
                        momentum_strength = 0.0
                        alignment_data_available = False
                        sweep["alignment_details"] = {"aligned": True, "reason": "alignment check disabled"}
                    else:
                        alignment = await self.enhanced_analyzer.check_price_action_alignment(
                            symbol, sweep["type"]
                        )
                        alignment_data_available = alignment is not None
                        price_aligned = True
                        alignment_confidence = 0
                        momentum_strength = 0.0
                        if alignment_data_available:
                            alignment_confidence = alignment.get("confidence", 0)
                            momentum_strength = alignment.get("strength", 0.0)
                            price_aligned = alignment.get("aligned", False) and alignment_confidence >= self.MIN_ALIGNMENT_CONFIDENCE
                            sweep["alignment_details"] = alignment
                        else:
                            sweep["alignment_details"] = {"aligned": None, "reason": "insufficient intraday data"}

                    sweep["price_aligned"] = price_aligned
                    sweep["alignment_confidence"] = alignment_confidence
                    sweep["momentum_strength"] = momentum_strength
                    sweep["alignment_data_available"] = alignment_data_available

                    if not skip_alignment and alignment_data_available and not price_aligned:
                        alignment_override = (
                            sweep["premium"] >= self.PRICE_ALIGNMENT_OVERRIDE_PREMIUM
                            or sweep["volume_ratio"] >= self.PRICE_ALIGNMENT_OVERRIDE_VOI
                        )
                        if not alignment_override:
                            self._log_skip(symbol, "price action misaligned (<confidence threshold)")
                            continue

                    # Boost score for unusual volume
                    volume_boost = 0
                    volume_ratio = sweep["volume_ratio"]
                    if ratio_data_available:
                        if volume_ratio >= 3.0:
                            volume_boost = 18
                        elif volume_ratio >= 2.0:
                            volume_boost = 12
                        elif volume_ratio >= 1.5:
                            volume_boost = 6
                        elif volume_ratio >= 1.2:
                            volume_boost = 3

                    if not alignment_data_available:
                        alignment_boost = 0
                    elif price_aligned:
                        alignment_boost = 6
                    else:
                        alignment_boost = -6

                    sweep["enhanced_score"] = max(
                        0,
                        min(
                            sweep.get("sweep_score", 50) + volume_boost + alignment_boost,
                            100,
                        ),
                    )

                    # Filter by minimum score
                    if sweep["enhanced_score"] >= self.MIN_SCORE:
                        enhanced_sweeps.append(sweep)
                    else:
                        self._log_skip(
                            symbol,
                            f"sweep score {sweep.get('enhanced_score', sweep.get('sweep_score'))} < {self.MIN_SCORE}",
                        )

                except Exception as e:
                    logger.debug(f"Error enhancing sweep: {e}")
                    # Include unenhanced sweep if it meets threshold
                    if sweep.get("enhanced_score", sweep.get("sweep_score", 0)) >= self.MIN_SCORE:
                        enhanced_sweeps.append(sweep)

            # Return top signals per symbol sorted by enhanced score
            return sorted(
                enhanced_sweeps,
                key=lambda x: x.get("enhanced_score", x.get("sweep_score", 0)),
                reverse=True,
            )[: self.TOP_SWEEPS_PER_SYMBOL]

        except Exception as e:
            logger.error(f"Error scanning {symbol} for sweeps: {e}")
            return []

    async def _scan_sweeps(self, symbol: str) -> List[Dict]:
        """
        Scan for sweep orders using efficient flow detection.

        NEW APPROACH (REST):
        - Single API call via detect_unusual_flow()
        - $50K+ premium threshold
        - Volume delta indicates aggressive buying/selling
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
                min_premium=self.MIN_SWEEP_PREMIUM,
                min_volume_delta=self.MIN_VOLUME_DELTA
            )

            # Process each flow signal
            for flow in flows:
                # Extract flow data
                opt_type = flow['type']
                strike = flow['strike']
                expiration = flow['expiration']
                premium = flow['premium']
                
                # STRICT FILTER: Skip any sweep that qualifies as "Golden" ($1M+)
                # These are handled by the dedicated GoldenSweepsBot
                # FALLBACK: If Golden bot appears unhealthy, emit in standard channel
                if premium >= Config.GOLDEN_MIN_PREMIUM:
                    if not self._is_golden_bot_healthy():
                        logger.info(f"{self.name} emitting golden fallback for {symbol} ${premium:,.0f} (GoldenSweepsBot unhealthy)")
                        # Mark as fallback and continue processing
                        flow['_golden_fallback'] = True
                    else:
                        self._log_skip(symbol, f"sweep premium ${premium:,.0f} qualifies as golden sweep (skipped in standard channel)")
                        continue
                
                total_volume = flow['total_volume']
                volume_delta = flow['volume_delta']
                open_interest = flow.get('open_interest')

                # Filter: Minimum volume threshold
                if total_volume < self.MIN_VOLUME or volume_delta < self.MIN_VOLUME_DELTA:
                    self._log_skip(symbol, f"sweep volume too small ({total_volume} total / {volume_delta} delta)")
                    continue

                if open_interest is not None and total_volume <= open_interest:
                    # Relaxed filter: Don't skip just because Vol < OI. 
                    # Sweeps are about aggressive execution, not just OI accumulation.
                    pass

                # Calculate DTE
                exp_date = datetime.strptime(expiration, '%Y-%m-%d')
                days_to_expiry = (exp_date - datetime.now()).days

                # Filter: Valid DTE range (1-90 days)
                if days_to_expiry <= 0 or days_to_expiry > 90:
                    continue

                # Calculate probability ITM
                prob_itm = self.analyzer.calculate_probability_itm(
                    opt_type, strike, current_price, days_to_expiry
                )

                # Strike analysis with tiered premium-based allowances
                strike_distance = ((strike - current_price) / current_price) * 100
                abs_distance = abs(strike_distance)
                
                # Determine max allowed strike distance based on premium tier
                max_allowed_distance = self.MAX_STRIKE_DISTANCE
                for premium_threshold, allowed_distance in self.STRIKE_DISTANCE_PREMIUM_TIERS:
                    if premium >= premium_threshold:
                        max_allowed_distance = allowed_distance
                        break
                
                # Short DTE gets additional allowance
                if days_to_expiry <= self.SHORT_DTE_THRESHOLD:
                    max_allowed_distance += self.SHORT_DTE_STRIKE_EXTENSION
                
                if abs_distance > max_allowed_distance:
                    self._log_skip(symbol, f'sweep strike distance {strike_distance:.1f}% exceeds {max_allowed_distance}% (premium ${premium:,.0f}, DTE {days_to_expiry})')
                    continue
                if opt_type == 'CALL':
                    moneyness = 'ITM' if strike < current_price else 'OTM' if strike > current_price else 'ATM'
                else:
                    moneyness = 'ITM' if strike > current_price else 'OTM' if strike < current_price else 'ATM'

                # Calculate sweep score (estimate 3+ fills based on volume delta)
                num_fills = max(3, int(volume_delta / 50))  # Estimate fills from volume
                sweep_score = self._calculate_sweep_score(
                    premium, total_volume, num_fills, abs(strike_distance)
                )

                # Create sweep signal
                sweep = {
                    'ticker': symbol,
                    'symbol': symbol,
                    'type': opt_type,
                    'strike': strike,
                    'expiration': expiration,
                    'current_price': current_price,
                    'days_to_expiry': days_to_expiry,
                    'premium': premium,
                    'volume': total_volume,
                    'num_fills': num_fills,
                    'moneyness': moneyness,
                    'strike_distance': strike_distance,
                    'probability_itm': prob_itm,
                    'sweep_score': sweep_score,
                    'time_span': 0,  # Not available in REST (was time between trades)
                    'volume_delta': volume_delta,
                    'open_interest': flow.get('open_interest', 0),
                    'delta': flow.get('delta', 0),
                    'gamma': flow.get('gamma', 0),
                    'vega': flow.get('vega', 0)
                }

                is_block_contract = (
                    volume_delta >= getattr(Config, "BULLSEYE_MIN_BLOCK_CONTRACTS", 400)
                    and premium >= getattr(Config, "BULLSEYE_MIN_PREMIUM", 1_000_000)
                )
                sweep['execution_type'] = 'BLOCK' if is_block_contract else 'SWEEP'
                if is_block_contract:
                    sweep['block_reason'] = f"{volume_delta:,} contracts vs OI {flow.get('open_interest', 0):,}"

                # CRITICAL FEATURE #4: Smart Deduplication
                signal_key = f"{symbol}_{opt_type}_{strike}_{expiration}"
                dedup_result = self.deduplicator.should_alert(signal_key, premium)

                if dedup_result['should_alert']:
                    if self._cooldown_active(signal_key):
                        self._log_skip(symbol, f'sweep cooldown {signal_key}')
                        continue
                    sweep['alert_type'] = dedup_result['type']
                    sweep['alert_reason'] = dedup_result['reason']
                    sweeps.append(sweep)
                    self._mark_cooldown(signal_key)

        except Exception as e:
            logger.error(f"Error scanning sweeps for {symbol}: {e}")

        return sweeps

    def _is_golden_bot_healthy(self) -> bool:
        """
        Check if GoldenSweepsBot appears healthy based on last known status.
        If we haven't heard from it in a while, assume unhealthy.
        """
        if self._golden_bot_last_healthy is None:
            # No status received yet - assume healthy for first few minutes of operation
            return True
        
        elapsed = (datetime.now() - self._golden_bot_last_healthy).total_seconds()
        return elapsed < self._golden_fallback_threshold_seconds
    
    def update_golden_bot_health(self, healthy: bool) -> None:
        """
        Called by bot manager to update Golden bot health status.
        This allows SweepsBot to emit fallback alerts when Golden is down.
        """
        if healthy:
            self._golden_bot_last_healthy = datetime.now()

    def _calculate_sweep_score(self, premium: float, volume: int,
                               num_fills: int, strike_distance: float) -> int:
        """Calculate sweep conviction score using generic scoring system"""
        score = self.calculate_score({
            'premium': (premium, [
                (500000, 40),  # $500k+ → 40 points (40%)
                (250000, 35),  # $250k+ → 35 points
                (100000, 30),  # $100k+ → 30 points
                (50000, 25)    # $50k+ → 25 points
            ]),
            'volume': (volume, [
                (1000, 25),  # 1000+ → 25 points (25%)
                (500, 20),   # 500+ → 20 points
                (250, 15),   # 250+ → 15 points
                (100, 10)    # 100+ → 10 points
            ]),
            'fills': (num_fills, [
                (5, 20),  # 5+ fills → 20 points (20%)
                (3, 15),  # 3+ fills → 15 points
                (2, 10)   # 2+ fills → 10 points
            ])
        })

        # Strike proximity (15%) - lower distance = higher score
        if strike_distance <= 2:
            score += 15
        elif strike_distance <= 5:
            score += 10
        elif strike_distance <= 10:
            score += 5

        return score

    async def _post_signal(self, sweep: Dict):
        """Post enhanced sweep signal to Discord"""
        color = 0x00FF00 if sweep['type'] == 'CALL' else 0xFF0000
        emoji = "🔥" if sweep['type'] == 'CALL' else "🔥"
        
        # ORAKL v3.0 Brain Validation - Get market context (skip hedge check for sweeps - too expensive)
        brain_metadata = {}
        if self.context_manager:
            try:
                context = self.context_manager.get_context(sweep['symbol'])
                brain_metadata = {
                    "regime": context.get('regime', 'NEUTRAL'),
                    "net_gex": context.get('net_gex', 0),
                    "flip_level": context.get('flip_level', 0),
                    "G": context.get('G', 0.5),
                    "brain_validated": True
                }
            except Exception as e:
                logger.debug(f"[{self.name}] ContextManager check failed for {sweep['symbol']}: {e}")
        
        # Check if golden fallback alert
        is_golden_fallback = sweep.get('_golden_fallback', False)
        if is_golden_fallback:
            emoji = "🏆⚠️"  # Golden + warning
            color = 0xFFD700  # Gold color

        # Check if accumulation alert
        if sweep.get('alert_type') == 'ACCUMULATION':
            emoji = "🔥⚡🔥"
            color = 0xFF4500  # Orange-red

        execution_type = sweep.get('execution_type', 'SWEEP').upper()

        # Determine sentiment / labeling
        if execution_type == 'BLOCK':
            sentiment = "Institutional Block Trade"
            emoji = "🧱🔥"
        elif sweep['moneyness'] == 'ITM':
            sentiment = "Aggressive ITM Sweep"
        elif sweep['moneyness'] == 'ATM':
            sentiment = "ATM Sweep"
        else:
            sentiment = "Bullish OTM Sweep" if sweep['type'] == 'CALL' else "Bearish OTM Sweep"

        final_score = sweep.get('enhanced_score', sweep['sweep_score'])

        # Only notify when sweep score meets tightened threshold
        if int(final_score) < self.MIN_SCORE:
            logger.debug(f"{self.name} - Skipping alert: score {int(final_score)} < {self.MIN_SCORE}")
            return False

        # Symbol-level cooldown to prevent firehose (Strike-Specific)
        # Key: SYMBOL_STRIKE_TYPE_EXPIRATION (e.g., AAPL_270.0_CALL_20251128)
        strike_part = f"{float(sweep['strike']):.1f}"
        expiration_part = sweep['expiration'].replace("-", "")
        symbol_cooldown_key = f"{sweep['symbol']}_{strike_part}_{sweep['type']}_{expiration_part}"
        
        # Check cooldown with Escalation Logic
        if self._cooldown_active(symbol_cooldown_key, cooldown_seconds=self.symbol_cooldown_seconds):
            # Allow bypass if:
            # 1. Golden Sweep (>$1M)
            # 2. Significant size increase (>2x previous premium)
            
            current_premium = float(sweep['premium'])
            last_alerted_premium = 0.0 # TODO: We need to track this in self.signal_history or self._cooldowns metadata
            # Since BaseAutoBot cooldowns is just Dict[str, datetime], we can't easily store the premium there.
            # However, SweepsBot has self.signal_history = {} initialized in __init__ but not really used?
            # Let's use a new cache for premium tracking: self._last_alerted_premium
            
            if not hasattr(self, '_last_alerted_premium'):
                self._last_alerted_premium = {}
            
            last_alerted_premium = self._last_alerted_premium.get(symbol_cooldown_key, 0.0)
            
            is_golden = current_premium >= 1_000_000
            is_escalation = last_alerted_premium > 0 and current_premium >= (last_alerted_premium * 2.0)
            
            if is_golden or is_escalation:
                logger.info(f"{self.name} bypassing cooldown for {symbol_cooldown_key}: Golden={is_golden}, Escalation={is_escalation} (${current_premium:,.0f} vs ${last_alerted_premium:,.0f})")
            else:
                self._log_skip(sweep['symbol'], f"cooldown active ({self.symbol_cooldown_seconds // 60}m) for {strike_part} {sweep['type']}")
                return False

        # Build embed
        title_prefix = "[Golden Fallback] " if is_golden_fallback else ""
        block_suffix = " • Block" if execution_type == 'BLOCK' else ""
        title = f"{emoji} {title_prefix}{sweep['ticker']} - {sentiment}{block_suffix}"
        
        premium_fmt = f"${sweep['premium']/1_000_000:.1f}M" if sweep['premium'] >= 1_000_000 else f"${sweep['premium']/1_000:.0f}K"
        
        oi_value = sweep.get('open_interest')

        contract_pretty = format_option_contract_pretty(
            sweep.get("symbol", ""),
            sweep.get("expiration", ""),
            sweep.get("strike"),
            sweep.get("type", ""),
        )
        contract_id = normalize_option_ticker(sweep.get("contract"))

        fields = [
            {"name": "Contract", "value": contract_pretty, "inline": False},
            {"name": "Contract ID", "value": f"`{contract_id}`" if contract_id else "Unavailable", "inline": False},
            {"name": "Strike", "value": f"${sweep['strike']:.2f}", "inline": True},
            {"name": "Expiration", "value": sweep['expiration'], "inline": True},
            {"name": "DTE", "value": str(sweep['days_to_expiry']), "inline": True},
            {"name": "Premium", "value": premium_fmt, "inline": True},
            {"name": "Volume", "value": f"{sweep['volume']:,}", "inline": True},
            {"name": "Fills", "value": str(sweep.get('num_fills', 'N/A')), "inline": True},
            {"name": "Current Price", "value": f"${sweep['current_price']:.2f}", "inline": True},
            {"name": "Strike Distance", "value": f"{sweep['strike_distance']:.1f}%", "inline": True},
            {"name": "Score", "value": f"{int(final_score)}/100", "inline": True},
        ]
        
        if oi_value is not None:
            fields.insert(5, {"name": "Open Interest", "value": f"{int(oi_value):,}", "inline": True})

        # Add volume ratio if available
        if sweep.get('volume_ratio'):
            fields.append({"name": "Vol Ratio", "value": f"{sweep['volume_ratio']:.2f}x", "inline": True})
        
        # ORAKL v3.0 Brain - GEX Regime Context
        if brain_metadata.get("brain_validated"):
            gex_regime = brain_metadata.get("regime", "NEUTRAL")
            if gex_regime != "NEUTRAL":
                gex_emojis = {"POSITIVE_GAMMA": "🟢", "NEGATIVE_GAMMA": "🔴"}
                gex_emoji = gex_emojis.get(gex_regime, "⚪")
                gex_text = f"{gex_emoji} {gex_regime.replace('_', ' ').title()}"
                flip = brain_metadata.get("flip_level", 0)
                if flip > 0:
                    gex_text += f" | Flip: ${flip:.0f}"
                fields.append({"name": "GEX", "value": gex_text, "inline": True})
        
        footer_text = "Golden Sweep Fallback" if is_golden_fallback else "Sweeps Bot"
        embed = self.create_signal_embed_with_disclaimer(
            title=title,
            description=f"**{sweep['type']}** sweep detected with **{sweep['moneyness']}** positioning",
            color=color,
            fields=fields,
            footer=footer_text
        )

        success = await self.post_to_discord(embed)
        if success:
            logger.info(f"🚨 SWEEP: {sweep['ticker']} {sweep['type']} ${sweep['strike']} Premium:${sweep['premium']:,.0f} Score:{int(final_score)}")
            self._mark_cooldown(symbol_cooldown_key)
            
            # Update last alerted premium
            if not hasattr(self, '_last_alerted_premium'):
                self._last_alerted_premium = {}
            self._last_alerted_premium[symbol_cooldown_key] = float(sweep['premium'])

        return success
