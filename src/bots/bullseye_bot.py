"""Bullseye Bot - Institutional Swing Trade Scanner"""
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Any
from collections import defaultdict
import contextlib
import pandas as pd
import asyncio
import numpy as np
from scipy.stats import norm
from .base_bot import BaseAutoBot
from src.data_fetcher import DataFetcher
from src.options_analyzer import OptionsAnalyzer
from src.config import Config
from src.utils.market_hours import MarketHours
from src.utils.market_context import MarketContext
from src.utils.exit_strategies import ExitStrategies

logger = logging.getLogger(__name__)

class BullseyeBot(BaseAutoBot):
    """
    Bullseye Bot - Institutional Swing Trade Scanner
    Tracks INSTITUTIONAL positioning for 1-5 day swing trades
    Large premium = Smart money expecting big moves
    """

    def __init__(self, webhook_url: str, watchlist: List[str], fetcher: DataFetcher, analyzer: OptionsAnalyzer):
        super().__init__(webhook_url, "Bullseye Bot", scan_interval=Config.BULLSEYE_INTERVAL)
        self.watchlist = watchlist
        self.fetcher = fetcher
        self.analyzer = analyzer
        self.last_momentum = None  # Initialize for scoring
        self._outcome_task: Optional[asyncio.Task] = None
        self._weekly_report_metadata_key = f"{self.name}_weekly_report"
        
        # Load all thresholds from Config for consistency
        self.MIN_PREMIUM = Config.BULLSEYE_MIN_PREMIUM
        self.MIN_VOLUME = Config.BULLSEYE_MIN_VOLUME
        self.MIN_VOLUME_DELTA = Config.BULLSEYE_MIN_VOLUME_DELTA
        self.MIN_OPEN_INTEREST = Config.BULLSEYE_MIN_OPEN_INTEREST
        self.MIN_DTE = int(Config.BULLSEYE_MIN_DTE)
        self.MAX_DTE = int(Config.BULLSEYE_MAX_DTE)
        self.MIN_VOI_RATIO = Config.BULLSEYE_MIN_VOI_RATIO
        self.MIN_ITM_PROBABILITY = Config.BULLSEYE_MIN_ITM_PROBABILITY
        self.DELTA_RANGE = (Config.BULLSEYE_DELTA_MIN, Config.BULLSEYE_DELTA_MAX)
        self.MAX_STRIKE_DISTANCE = Config.BULLSEYE_MAX_STRIKE_DISTANCE
        self.MAX_SPREAD_PCT = Config.BULLSEYE_MAX_SPREAD_PCT

    async def scan_and_post(self):
        """Scan for institutional swing trade opportunities"""
        logger.info(f"{self.name} scanning for institutional swing positions")

        if not MarketHours.is_market_open(include_extended=False):
            logger.debug(f"{self.name} - Market closed, skipping scan")
            return
        
        now_est = MarketHours.now_est()
        if now_est.hour >= Config.BULLSEYE_EOD_SKIP_HOUR:
            logger.debug(f"{self.name} - EOD hedging window, skipping scan")
            return
        
        market_context = await MarketContext.get_market_context(self.fetcher)
        
        semaphore = asyncio.Semaphore(max(1, Config.MAX_CONCURRENT_REQUESTS))

        async def run_symbol(symbol: str):
            async with semaphore:
                return await self._scan_for_institutional_swings(symbol, market_context)
        
        tasks = [run_symbol(symbol) for symbol in self.watchlist]
        all_signals = await asyncio.gather(*tasks, return_exceptions=True)
        
        flat_signals = [signal for sublist in all_signals if isinstance(sublist, list) for signal in sublist]
        
        # Filter out likely hedges
        directional_signals = [s for s in flat_signals if not self._is_likely_hedge(s)]
        
        # Rank by institutional score and post top signals
        top_signals = sorted(directional_signals, key=lambda x: x['institutional_score'], reverse=True)
        
        # Limit alerts per symbol
        posted_symbols = set()
        alerts_posted = 0
        
        for signal in top_signals:
            if signal['ticker'] not in posted_symbols:
                await self._post_institutional_signal(signal)
                posted_symbols.add(signal['ticker'])
                alerts_posted += 1
                if alerts_posted >= 3:  # Max 3 alerts per scan
                    break

    async def _scan_for_institutional_swings(self, symbol: str, market_context: Dict) -> List[Dict]:
        """
        Scan for INSTITUTIONAL positioning for 1-2 day swing trades.
        Large premium trades = institutions expecting moves NOW.
        """
        signals = []
        try:
            current_price = await self.fetcher.get_stock_price(symbol)
            if not current_price:
                return signals

            # NEW: Use efficient flow detection (single API call)
            flows = await self.fetcher.detect_unusual_flow(
                underlying=symbol,
                min_premium=self.MIN_PREMIUM,
                min_volume_delta=self.MIN_VOLUME_DELTA
            )
            flows = self._filter_suspected_spreads(symbol, flows)
            flows = self._filter_stale_flows(symbol, flows, max_hours=Config.BULLSEYE_MAX_FLOW_AGE_HOURS)
            if not flows:
                return signals

            # Price Action Confirmation
            momentum = await self._calculate_momentum(symbol)
            if not momentum:
                return signals

            atr = await self._get_atr(symbol)

            # Process each flow signal
            for flow in flows:
                # Extract flow data
                opt_type = flow['type']
                strike = flow['strike']
                expiration = flow['expiration']
                premium = flow['premium']
                
                if premium < self.MIN_PREMIUM:
                    self._log_skip(symbol, f"bullseye premium ${premium:,.0f} < ${self.MIN_PREMIUM:,.0f}")
                    continue
                total_volume = flow['total_volume']
                volume_delta = flow.get('volume_delta', 0)
                if total_volume < self.MIN_VOLUME or volume_delta < self.MIN_VOLUME_DELTA:
                    self._log_skip(symbol, f"bullseye volume too small ({total_volume}/{volume_delta})")
                    continue
                open_interest = flow.get('open_interest', 0)
                delta = flow.get('delta', 0)
                bid = flow.get('bid', 0)
                ask = flow.get('ask', 0)
                last_price = flow.get('last_price', 0)
                implied_volatility = flow.get('implied_volatility', 0)
                volume_velocity = flow.get('volume_velocity', 0)
                flow_intensity = flow.get('flow_intensity', 'NORMAL')
                
                # Determine actual execution side (don't assume!)
                execution_side = self._determine_execution_side(last_price, ask, bid)
                
                # Filter: Require ask-side for institutional buying conviction
                if execution_side not in ['ASK', 'UNKNOWN']:
                    self._log_skip(symbol, f"bullseye not ask-side (execution: {execution_side})")
                    continue

                # Calculate DTE
                exp_date = datetime.strptime(expiration, '%Y-%m-%d')
                days_to_expiry = (exp_date - datetime.now()).days

                # Filter 1: DTE range (1-3 days for short-dated trades)
                if days_to_expiry < self.MIN_DTE or days_to_expiry > self.MAX_DTE:
                    self._log_skip(symbol, f'bullseye DTE {days_to_expiry} outside {self.MIN_DTE}-{self.MAX_DTE}')
                    continue

                # Filter 2: Liquidity guards - simple OI floor
                # Require baseline open interest for tradable contracts
                if open_interest < self.MIN_OPEN_INTEREST:
                    self._log_skip(symbol, f'bullseye OI {open_interest} < required {self.MIN_OPEN_INTEREST}')
                    continue
                # Bid-ask spread check (configurable)
                if bid > 0 and ask > 0:
                    mid_price = (bid + ask) / 2
                    spread_pct = ((ask - bid) / mid_price) * 100 if mid_price > 0 else 100
                    if spread_pct > self.MAX_SPREAD_PCT:
                        self._log_skip(symbol, f"bullseye spread {spread_pct:.2f}% > {self.MAX_SPREAD_PCT}%")
                        continue

                # Filter 3: VOI ratio (volume_delta / OI)
                if open_interest == 0:
                    self._log_skip(symbol, 'bullseye open interest zero')
                    continue

                voi_ratio = volume_delta / open_interest
                if voi_ratio < self.MIN_VOI_RATIO:
                    self._log_skip(symbol, f'bullseye VOI {voi_ratio:.2f}x < {self.MIN_VOI_RATIO:.2f}x')
                    continue

                # Filter 4: ATM to slightly OTM (institutional range)
                if abs(delta) < self.DELTA_RANGE[0] or abs(delta) > self.DELTA_RANGE[1]:
                    self._log_skip(symbol, f"bullseye delta {abs(delta):.2f} outside range {self.DELTA_RANGE[0]}-{self.DELTA_RANGE[1]}")
                    continue

                # Filter 5: Strike distance (configurable max distance)
                strike_distance = abs(strike - current_price) / current_price
                if strike_distance > self.MAX_STRIKE_DISTANCE:
                    self._log_skip(symbol, f"bullseye strike {strike_distance*100:.1f}% from price (max {self.MAX_STRIKE_DISTANCE*100:.1f}%)")
                    continue

                # Filter 6: ITM Probability (Phase 1 - Tuned)
                # Calculate P(ITM) using Black-Scholes d2
                T_years = days_to_expiry / 365.0
                itm_probability = self._calculate_itm_probability(
                    S=current_price,
                    K=strike,
                    T=T_years,
                    IV=implied_volatility,
                    opt_type=opt_type
                )

                # Require P(ITM) threshold for institutional-grade probability
                if itm_probability < self.MIN_ITM_PROBABILITY:
                    self._log_skip(symbol, f"bullseye ITM probability {itm_probability*100:.1f}% < {self.MIN_ITM_PROBABILITY*100:.1f}%")
                    continue

                logger.debug(f"✓ {symbol} ${strike} {opt_type}: ITM probability {itm_probability*100:.1f}% passed")

                # Filter 7: 5-Day Expected Move (CRITICAL - prevents unrealistic strikes)
                # Strike must be within 5-day expected move to ensure realistic probability
                em5 = self._calculate_expected_move(
                    S=current_price,
                    IV=implied_volatility,
                    days=5
                )

                strike_diff = abs(strike - current_price)
                if strike_diff > em5:
                    self._log_skip(symbol, f"bullseye strike ${strike_diff:.2f} outside EM5 ${em5:.2f}")
                    continue
                
                logger.debug(f"✓ {symbol} ${strike} {opt_type}: strike ${strike_diff:.2f} within EM5 ${em5:.2f}")

                # Filter 8: Momentum scoring (not a hard filter - institutions lead price action)
                # Allow contrarian trades - institutions often position before momentum shifts
                # Momentum alignment will be reflected in scoring, not as rejection criteria
                momentum_aligned = (
                    (opt_type == 'CALL' and momentum['direction'] == 'bullish') or
                    (opt_type == 'PUT' and momentum['direction'] == 'bearish')
                )
                
                # Log but don't reject - contrarian institutional plays can be high-conviction
                if not momentum_aligned:
                    logger.debug(f"⚠️ {symbol} ${strike} {opt_type}: CONTRARIAN to {momentum['direction']} momentum (allowed)")

                last_trade_timestamp = flow.get('last_trade_timestamp') or flow.get('timestamp')
                flow_recency_minutes = None
                if isinstance(last_trade_timestamp, datetime):
                    reference_now = datetime.now(last_trade_timestamp.tzinfo) if last_trade_timestamp.tzinfo else datetime.now()
                    flow_recency_minutes = (reference_now - last_trade_timestamp).total_seconds() / 60

                # All filters passed!
                logger.info(f"✅ {symbol} ${strike} {opt_type} passed all filters - ITM: {itm_probability*100:.1f}%, VOI: {voi_ratio:.1f}x, Score: calculating...")

                # Calculate liquidity quality score (0-1)
                liquidity_score = self._calculate_liquidity_score(
                    open_interest=open_interest,
                    spread_pct=spread_pct if bid > 0 and ask > 0 else 5.0
                )

                # Prepare trade data for institutional scoring
                trade_data = {
                    'symbol': symbol,
                    'premium': premium,
                    'volume': total_volume,
                    'open_interest': open_interest,
                    'option_type': opt_type,
                    'strike': strike,
                    'delta': delta,
                    'execution': execution_side,  # Use actual execution side, not assumption
                    'is_sweep': flow_intensity == 'HIGH',
                    'is_block': total_volume >= 5000,
                    'voi_ratio': voi_ratio,
                    'dte': days_to_expiry
                }
                
                # Calculate institutional swing score
                institutional_score, trade_tag = self._calculate_institutional_swing_score(trade_data)
                
                if institutional_score >= 65:  # Minimum score for institutional trades
                    signal = {
                        'ticker': symbol,
                        'type': opt_type,
                        'strike': strike,
                        'expiration': expiration,
                        'current_price': current_price,
                        'days_to_expiry': days_to_expiry,
                        'premium': premium,
                        'volume': total_volume,
                        'open_interest': open_interest,
                        'voi_ratio': voi_ratio,
                        'momentum_strength': momentum['strength'],
                        'momentum_direction': momentum['direction'],
                        'institutional_score': institutional_score,
                        'trade_tag': trade_tag,
                        'market_context': market_context,
                        'volume_delta': volume_delta,
                        'delta': delta,
                        'gamma': flow.get('gamma', 0),
                        'vega': flow.get('vega', 0),
                        'theta': flow.get('theta', 0),
                        'itm_probability': itm_probability,
                        'expected_move_5d': em5,
                        'liquidity_score': liquidity_score,
                        'bid': bid,
                        'ask': ask,
                        'bid_ask_spread_pct': spread_pct if bid > 0 and ask > 0 else None,
                        'implied_volatility': implied_volatility,
                        'flow_intensity': flow_intensity,
                        'execution': execution_side,  # Use actual execution side
                        'is_sweep': flow_intensity == 'HIGH',
                        'is_block': total_volume >= 5000,
                        'atr': atr,
                        'last_trade_timestamp': last_trade_timestamp,
                        'flow_recency_minutes': flow_recency_minutes,
                        'signal_key': signal_key,
                        'option_ticker': flow.get('ticker')
                    }

                    # Deduplication: Use BaseAutoBot cooldown mechanism (4 hour cooldown)
                    signal_key = f"{symbol}_{opt_type}_{strike}_{expiration}"
                    if self._cooldown_active(signal_key, cooldown_seconds=14400):  # 4 hours
                        self._log_skip(symbol, f'bullseye cooldown active for {signal_key}')
                        continue
                    
                    signals.append(signal)
                    self._mark_cooldown(signal_key)

        except Exception as e:
            logger.error(f"Error scanning for swing trades on {symbol}: {e}")

        return signals

    def _determine_execution_side(self, trade_price: float, ask_price: float, bid_price: float) -> str:
        """
        Determine actual execution side from trade price vs quotes.
        
        Returns 'ASK', 'BID', or 'MID' based on where trade executed.
        """
        if not trade_price or trade_price <= 0:
            return 'UNKNOWN'
        
        # Ask-side (aggressive buying)
        if ask_price and ask_price > 0:
            if trade_price >= ask_price * 0.995:  # Allow small tolerance
                return 'ASK'
        
        # Bid-side (aggressive selling)
        if bid_price and bid_price > 0:
            if trade_price <= bid_price * 1.005:  # Allow small tolerance
                return 'BID'
        
        # Mid-spread
        if ask_price and bid_price and ask_price > 0 and bid_price > 0:
            mid_price = (ask_price + bid_price) / 2
            if abs(trade_price - mid_price) / mid_price < 0.02:  # Within 2% of mid
                return 'MID'
        
        # Fallback based on proximity
        if ask_price and bid_price:
            if trade_price > (ask_price + bid_price) / 2:
                return 'ASK'
            else:
                return 'BID'
        
        return 'UNKNOWN'

    def _calculate_liquidity_score(self, open_interest: int, spread_pct: float) -> float:
        """
        Calculate liquidity quality score (0-1).

        Args:
            open_interest: Contract open interest
            spread_pct: Bid-ask spread as percentage

        Returns:
            Score between 0.0 and 1.0
        """
        try:
            # OI score (50% weight)
            if open_interest >= 5000:
                oi_score = 1.0
            elif open_interest >= 2000:
                oi_score = 0.8
            elif open_interest >= 1000:
                oi_score = 0.6
            elif open_interest >= 500:
                oi_score = 0.4
            else:
                oi_score = 0.0

            # Spread score (50% weight)
            if spread_pct <= 1.0:
                spread_score = 1.0
            elif spread_pct <= 2.0:
                spread_score = 0.8
            elif spread_pct <= 3.5:
                spread_score = 0.6
            elif spread_pct <= 5.0:
                spread_score = 0.4
            else:
                spread_score = 0.0

            return (oi_score * 0.5) + (spread_score * 0.5)
        except Exception as e:
            logger.error(f"Error calculating liquidity score: {e}")
            return 0.0

    def _calculate_institutional_swing_score(self, trade: Dict) -> tuple:
        """
        Score based on institutional conviction + timing.
        Large premium trades = institutions expecting moves.
        
        Returns:
            Tuple of (score, trade_tag)
        """
        score = 0
        trade_tag = ""
        
        # 1. INSTITUTIONAL SIZE (35 points) - This DOES matter for swings!
        premium_score = 0
        
        if trade['premium'] >= 5000000:  # $5M+ whale trade
            premium_score = 35
            trade_tag = "🐋 WHALE"
        elif trade['premium'] >= 2000000:  # $2M+ 
            premium_score = 30
            trade_tag = "🦈 SHARK"
        elif trade['premium'] >= 1000000:  # $1M+
            premium_score = 25
            trade_tag = "🐟 BIG FISH"
        elif trade['premium'] >= 500000:  # $500K+
            premium_score = 20
            trade_tag = "📊 INSTITUTIONAL"
        elif trade['premium'] >= 250000:
            premium_score = 15
            trade_tag = "💰 SIGNIFICANT"
        else:
            return 0, ""  # Skip small trades for swing bot
        
        score += premium_score
        
        # 2. AGGRESSIVE POSITIONING (25 points)
        execution_score = 0
        
        # Sweeps at ask/bid = urgency
        if trade['is_sweep']:
            if trade['execution'] == 'ASK' and trade['option_type'] == 'CALL':
                execution_score = 25  # Aggressive bullish
            elif trade['execution'] == 'BID' and trade['option_type'] == 'PUT':
                execution_score = 25  # Aggressive bearish
            else:
                execution_score = 10  # Wrong side sweep
        
        # Block trades = institutional
        elif trade['is_block']:
            execution_score = 20  # Positioned trade
        
        # Regular at ask/bid
        elif trade['execution'] in ['ASK', 'BID']:
            execution_score = 15
        else:
            execution_score = 5  # Mid/spread trades
        
        score += execution_score
        
        # 3. VOLUME/OI DYNAMICS (20 points)
        flow_score = 0
        
        # Volume to OI ratio (fresh positioning vs hedging)
        voi_ratio = trade.get('voi_ratio', 0)
        
        if voi_ratio >= 2.0:  # Volume 2x OI = new positions
            flow_score += 10
        elif voi_ratio >= 1.0:
            flow_score += 7
        elif voi_ratio >= 0.5:
            flow_score += 5
        
        # Absolute volume significance
        if trade['volume'] >= 50000:  # Massive volume
            flow_score += 10
        elif trade['volume'] >= 25000:
            flow_score += 7
        elif trade['volume'] >= 10000:
            flow_score += 5
        
        score += min(flow_score, 20)
        
        # 4. TECHNICAL CATALYST (10 points)
        catalyst_score = 0
        
        # For now, simplified catalyst scoring
        # In full implementation, would check 52-week highs/lows, MA levels, etc.
        # Using momentum as proxy for technical setup
        if hasattr(self, 'last_momentum') and self.last_momentum:
            if self.last_momentum.get('strength', 0) >= 0.7:
                catalyst_score += 7
            elif self.last_momentum.get('strength', 0) >= 0.5:
                catalyst_score += 5
        
        # Check DTE sweet spot
        if 2 <= trade['dte'] <= 3:
            catalyst_score += 3
        
        score += min(catalyst_score, 10)
        
        # 5. REPEAT ACTIVITY (10 points) - Institutions scale in
        repeat_score = 0
        
        # Check recent signal history for same ticker
        recent_cutoff = datetime.now() - timedelta(hours=4)
        same_direction_count = 0
        
        for sig_key, sig_time in self.signal_history.items():
            if sig_time >= recent_cutoff:
                parts = sig_key.split('_')
                if len(parts) >= 2 and parts[0] == trade['symbol'] and parts[1] == trade['option_type']:
                    same_direction_count += 1
        
        if same_direction_count >= 3:
            repeat_score = 10  # Multiple institutions agreeing
        elif same_direction_count >= 2:
            repeat_score = 7
        elif same_direction_count >= 1:
            repeat_score = 4
        
        score += repeat_score
        
        return score, trade_tag

    def _is_likely_hedge(self, signal: Dict) -> bool:
        """Identify likely hedges vs directional bets"""
        
        # Deep ITM = likely hedge
        if abs(signal['delta']) > 0.85:
            return True
        
        # Massive volume in indices = hedge
        if signal['ticker'] in ['SPY', 'QQQ', 'IWM', 'VIX']:
            if signal['volume'] > 50000:
                return True
        
        # Very far OTM with huge volume = likely protection
        if abs(signal['delta']) < 0.15 and signal['volume'] > 25000:
            return True
        
        # Note: Removed "wrong-way momentum" hedge detection since we now allow contrarian trades
        # Contrarian institutional positioning is often high-conviction, not hedging
        
        return False


    def _calculate_itm_probability(self, S: float, K: float, T: float, IV: float, opt_type: str) -> float:
        """
        Calculate probability of option finishing ITM using Black-Scholes d2.

        Args:
            S: Current stock price
            K: Strike price
            T: Time to expiration in years
            IV: Implied volatility (annualized, e.g., 0.30 for 30%)
            opt_type: 'CALL' or 'PUT'

        Returns:
            Probability between 0.0 and 1.0
        """
        try:
            if T <= 0 or IV <= 0:
                return 0.0

            # Black-Scholes d2 calculation (risk-neutral probability of ITM)
            # d2 = (ln(S/K) + (r - 0.5*σ²)*T) / (σ*sqrt(T))
            # For options pricing, we assume r≈0 for simplicity (risk-free rate)
            r = 0.0

            d2 = (np.log(S / K) + (r - 0.5 * IV**2) * T) / (IV * np.sqrt(T))

            if opt_type == 'CALL':
                # P(S_T > K) = N(d2)
                return norm.cdf(d2)
            else:  # PUT
                # P(S_T < K) = N(-d2)
                return norm.cdf(-d2)

        except Exception as e:
            logger.error(f"Error calculating ITM probability: {e}")
            return 0.0

    def _calculate_expected_move(self, S: float, IV: float, days: int) -> float:
        """
        Calculate expected move over N days.

        EM_N = S * IV * sqrt(N/365)

        Args:
            S: Current stock price
            IV: Implied volatility (annualized)
            days: Number of days

        Returns:
            Expected move in dollars
        """
        try:
            if IV <= 0 or days <= 0:
                return 0.0

            return S * IV * np.sqrt(days / 365.0)
        except Exception as e:
            logger.error(f"Error calculating expected move: {e}")
            return 0.0

    async def _calculate_momentum(self, symbol: str) -> Optional[Dict]:
        """
        Calculate daily/4-hour momentum for swing trades.
        
        Returns None only if insufficient data.
        Returns 'neutral' direction when market is consolidating (valid state).
        """
        try:
            # Use daily bars for longer-term trend
            to_date = datetime.now().strftime('%Y-%m-%d')
            from_date = (datetime.now() - timedelta(days=90)).strftime('%Y-%m-%d')
            
            daily_bars = await self.fetcher.get_aggregates(
                symbol, 'day', 1, from_date, to_date
            )
            
            # Only return None if truly insufficient data
            if daily_bars.empty or len(daily_bars) < 20:
                return None
            
            # Simple Moving Averages
            sma_20 = daily_bars['close'].rolling(window=20).mean().iloc[-1]
            sma_50 = daily_bars['close'].rolling(window=50).mean().iloc[-1] if len(daily_bars) >= 50 else sma_20
            current_price = daily_bars['close'].iloc[-1]
            
            direction = 'neutral'
            strength = 0.5
            
            # Strong bullish trend
            if sma_20 > sma_50 * 1.01 and current_price > sma_20:
                direction = 'bullish'
                strength = 0.7 + min((current_price / sma_20 - 1) * 10, 0.3)
            # Strong bearish trend
            elif sma_20 < sma_50 * 0.99 and current_price < sma_20:
                direction = 'bearish'
                strength = 0.7 + min((sma_20 / current_price - 1) * 10, 0.3)
            # Neutral/consolidation - valid state for breakout setups
            else:
                direction = 'neutral'
                strength = 0.5
                
            momentum = {
                'direction': direction,
                'strength': min(max(strength, 0), 1),
                'is_consolidating': direction == 'neutral'  # Flag for scoring
            }
            
            # Store for use in scoring
            self.last_momentum = momentum
            
            return momentum
        except Exception as e:
            logger.error(f"Error calculating momentum for {symbol}: {e}")
            return None

    def _filter_suspected_spreads(self, symbol: str, flows: List[Dict]) -> List[Dict]:
        """Filter out flows that likely belong to multi-leg spreads."""
        if not flows:
            return []

        buckets: Dict[tuple, List[Dict]] = defaultdict(list)

        for flow in flows:
            trade_time = flow.get('last_trade_timestamp') or flow.get('timestamp')
            if isinstance(trade_time, datetime):
                minute_marker = trade_time.replace(second=0, microsecond=0)
            else:
                minute_marker = trade_time
            key = (flow.get('ticker'), minute_marker)
            buckets[key].append(flow)

        single_leg_flows: List[Dict] = []
        for (_, _), grouped_flows in buckets.items():
            if len(grouped_flows) == 1:
                single_leg_flows.append(grouped_flows[0])
            else:
                for grouped_flow in grouped_flows:
                    self._log_skip(
                        grouped_flow.get('underlying', symbol),
                        "bullseye potential multi-leg spread detected"
                    )

        return single_leg_flows

    def _filter_stale_flows(self, symbol: str, flows: List[Dict], max_hours: float = 2.0) -> List[Dict]:
        """Discard flows where the latest trade is older than max_hours."""
        if not flows:
            return []

        fresh_flows: List[Dict] = []
        for flow in flows:
            trade_time = flow.get('last_trade_timestamp') or flow.get('timestamp')
            if isinstance(trade_time, datetime):
                reference_now = datetime.now(trade_time.tzinfo) if trade_time.tzinfo else datetime.now()
                age_hours = (reference_now - trade_time).total_seconds() / 3600
                if age_hours > max_hours:
                    self._log_skip(symbol, f"bullseye flow stale ({age_hours:.1f}h old)")
                    continue
            fresh_flows.append(flow)
        return fresh_flows

    async def _get_atr(self, symbol: str, period: int = 5) -> Optional[float]:
        """Calculate Average True Range for the underlying."""
        try:
            to_date = datetime.now().strftime('%Y-%m-%d')
            from_date = (datetime.now() - timedelta(days=period + 20)).strftime('%Y-%m-%d')
            bars = await self.fetcher.get_aggregates(symbol, 'day', 1, from_date, to_date)

            if bars.empty or len(bars) <= period:
                return None

            bars = bars.sort_values('timestamp')
            highs = bars['high']
            lows = bars['low']
            closes = bars['close']
            prev_closes = closes.shift(1)

            true_range = pd.concat([
                highs - lows,
                (highs - prev_closes).abs(),
                (lows - prev_closes).abs()
            ], axis=1).max(axis=1)

            atr_series = true_range.rolling(window=period).mean()
            atr_value = atr_series.iloc[-1]
            if pd.isna(atr_value):
                return None

            return float(atr_value)
        except Exception as exc:
            logger.error(f"Error calculating ATR for {symbol}: {exc}")
            return None

    def _ensure_outcome_tracker(self) -> None:
        if not self.running:
            return
        if self._outcome_task and not self._outcome_task.done():
            return
        self._outcome_task = asyncio.create_task(self._track_outcomes())

    async def _track_outcomes(self):
        try:
            while True:
                await asyncio.sleep(max(60, Config.BULLSEYE_OUTCOME_POLL_SECONDS))
                pending = self._fetch_pending_outcomes()
                if not pending:
                    await self._maybe_post_weekly_performance()
                    continue

                for outcome in pending:
                    option_ticker = outcome['option_ticker']
                    snapshot = await self.fetcher.get_option_contract_snapshot(option_ticker)
                    if not snapshot:
                        continue

                    day_data = snapshot.get('day') or {}
                    last_trade = snapshot.get('last_trade') or {}

                    def _to_float(value):
                        return float(value) if isinstance(value, (int, float)) else None

                    last_price_candidates = [
                        day_data.get('close'),
                        day_data.get('c'),
                        last_trade.get('price'),
                        last_trade.get('p')
                    ]
                    last_price = next((val for val in map(_to_float, last_price_candidates) if val is not None), None)
                    high_price = _to_float(day_data.get('high') or day_data.get('h'))
                    low_price = _to_float(day_data.get('low') or day_data.get('l'))

                    updates: Dict[str, Any] = {}
                    stop_level = _to_float(outcome['stop'])

                    stop_hit = (low_price is not None and stop_level is not None and low_price <= stop_level)
                    if stop_hit:
                        updates['stopped_out'] = 1
                        updates['resolved'] = 1
                    else:
                        target1 = _to_float(outcome['target1'])
                        target2 = _to_float(outcome['target2'])
                        target3 = _to_float(outcome['target3'])

                        if high_price is not None:
                            if target1 is not None and high_price >= target1 and not outcome['hit_target1']:
                                updates['hit_target1'] = 1
                            if target2 is not None and high_price >= target2 and not outcome['hit_target2']:
                                updates['hit_target2'] = 1
                            if target3 is not None and high_price >= target3 and not outcome['hit_target3']:
                                updates['hit_target3'] = 1
                                updates['resolved'] = 1

                    if last_price is not None:
                        updates['last_price'] = last_price

                    if updates:
                        self._update_outcome_status(outcome['id'], updates)
                        if updates.get('resolved'):
                            self._maybe_flag_symbol(outcome['symbol'])

                await self._maybe_post_weekly_performance()
        except asyncio.CancelledError:
            logger.info(f"{self.name} outcome tracker stopped")
        except Exception as exc:
            logger.error(f"{self.name} outcome tracker error: {exc}")

    async def _maybe_post_weekly_performance(self):
        now = datetime.utcnow()
        if now.weekday() != Config.BULLSEYE_WEEKLY_REPORT_DAY:  # Configurable report day
            return

        last_report = self._get_metadata(self._weekly_report_metadata_key)
        if last_report:
            try:
                last_dt = datetime.fromisoformat(last_report)
                if last_dt.date() == now.date():
                    return
            except ValueError:
                pass

        summary = self._summarize_outcomes(days=7)
        signals = summary['signals']
        if signals == 0:
            return

        win_rate_pct = summary['win_rate'] * 100
        expected_gain_pct = summary['expected_gain'] * 100
        targets_line = (
            f"T1: {summary['hit_target1']} | "
            f"T2: {summary['hit_target2']} | "
            f"T3: {summary['hit_target3']} | "
            f"Stopped: {summary['stopped_out']}"
        )

        embed = self.create_embed(
            title="📊 Weekly Performance",
            description=f"{signals} signals in the last 7 days",
            color=0x1F8B4C,
            fields=[
                {"name": "Win Rate", "value": f"**{win_rate_pct:.1f}%** hit Target 1", "inline": False},
                {"name": "Targets Reached", "value": targets_line, "inline": False},
                {"name": "Expected Gain", "value": f"Approx. **{expected_gain_pct:.1f}%** per signal", "inline": False},
            ],
            footer="Bullseye Bot • Weekly performance snapshot"
        )

        posted = await self.post_to_discord(embed)
        if posted:
            self._set_metadata(self._weekly_report_metadata_key, now.isoformat())

    async def _post_institutional_signal(self, signal: Dict):
        """Post institutional swing alert with enhanced format"""
        color = 0x00FF00 if signal['type'] == 'CALL' else 0xFF0000
        
        # Calculate swing exits
        exits = self._calculate_swing_exits(signal['ask'], signal, signal.get('atr'))
        entry_price = signal['ask']
        stop_loss = exits['stop_loss']
        reward = exits['target1'] - entry_price
        risk = entry_price - stop_loss if entry_price > stop_loss else None
        rr_target1 = (reward / risk) if risk and risk > 0 else None
        theta_ratio = None
        if entry_price > 0 and signal.get('theta') is not None:
            theta_ratio = abs(signal['theta']) / entry_price

        recency_minutes = signal.get('flow_recency_minutes')
        distance_pct = ((signal['strike'] - signal['current_price']) / signal['current_price']) * 100
        distance_label = "OTM" if (signal['type'] == 'CALL' and distance_pct > 0) or (signal['type'] == 'PUT' and distance_pct < 0) else "ITM"
        description = f"Expiry: {signal['expiration']} ({signal['days_to_expiry']} DTE)"
        stop_basis_label = "ATR" if exits.get('stop_basis') == "atr" else "Percent"
        
        title = f"🎯 {signal['ticker']} ${signal['strike']} {signal['type']} • {signal['trade_tag']}"
        
        if signal['premium'] >= 1_000_000:
            premium_fmt = f"${signal['premium']/1_000_000:.1f}M"
        else:
            premium_fmt = f"${signal['premium']/1_000:.0f}K"
        
        flow_details: List[str] = [
            f"• Premium: **{premium_fmt}**",
            f"• Volume: **{signal['volume']:,}** contracts | VOI **{signal['voi_ratio']:.2f}x**",
            f"• Execution: **{signal['execution']}**"
        ]
        if recency_minutes is not None:
            flow_details.append(f"• Last trade: **{max(recency_minutes, 0):.0f} min ago**")
        if signal.get('flow_intensity'):
            flow_details.append(f"• Intensity: **{signal['flow_intensity']}**")
        if exits.get('atr'):
            flow_details.append(f"• ATR (5): **${exits['atr']:.2f}**")

        edge_lines: List[str] = [f"• ITM Probability: **{signal['itm_probability']:.1%}**"]
        if rr_target1 is not None:
            edge_lines.append(f"• Target 1 R:R: **{rr_target1:.2f}:1**")
        if theta_ratio is not None:
            edge_lines.append(f"• Theta Decay: **{theta_ratio:.1%}/day**")
        edge_lines.append(f"• Stop Basis: **{stop_basis_label}** (Stop @ ${exits['stop_loss']:.2f})")

        execution_plan = (
            f"1. Enter near **${entry_price:.2f}** (limit, no chasing)\n"
            f"2. Sell **50%** @ **${exits['target1']:.2f}**, then move stop → breakeven\n"
            f"3. Sell **30%** @ **${exits['target2']:.2f}**\n"
            f"4. Trail final **20%** with {int(exits['trail_percent']*100)}% stop"
        )

        fields = [
            {
                "name": "💰 Flow Snapshot",
                "value": "\n".join(flow_details),
                "inline": False
            },
            {
                "name": "📊 Setup",
                "value": (
                    f"• Score: **{signal['institutional_score']} / 100**\n"
                    f"• Momentum: **{self._get_momentum_status(signal)}**\n"
                    f"• Stock: **${signal['current_price']:.2f}** | Distance: **{abs(distance_pct):.1f}% {distance_label}**"
                ),
                "inline": False
            },
            {
                "name": "📈 Probability & Edge",
                "value": "\n".join(edge_lines),
                "inline": False
            },
            {
                "name": "🎯 Execution Plan",
                "value": execution_plan,
                "inline": False
            },
            {
                "name": "⏱️ Entry Timing",
                "value": "Wait 5-10 minutes after open for spreads < 3%. Use limit orders; avoid illiquid fills.",
                "inline": False
            },
        ]
        
        # Create embed
        embed = self.create_signal_embed_with_disclaimer(
            title=title,
            description=description,
            color=color,
            fields=fields,
            footer="ORAKL Institutional Scanner • 1-5 Day Swing Trades"
        )
        
        posted = await self.post_to_discord(embed)
        if posted:
            self._record_signal_outcome(signal, exits)
            self._ensure_outcome_tracker()
            await self._maybe_post_weekly_performance()
            logger.info(
                f"Posted Institutional Swing: {signal['ticker']} {signal['type']} ${signal['strike']} "
                f"Score:{signal['institutional_score']} Premium:{signal['premium']:,.0f} Tag:{signal['trade_tag']}"
            )
        else:
            logger.warning(
                f"{self.name} failed to post signal for {signal['ticker']} {signal['type']} ${signal['strike']}"
            )

    def _calculate_swing_exits(self, entry_price: float, flow_data: Dict, atr: Optional[float] = None) -> Dict:
        """
        1-2 day swing trades need wider stops, bigger targets
        These aren't scalps - institutions expect MOVES
        """
        
        dte = flow_data['days_to_expiry']
        delta_abs = abs(flow_data.get('delta', 0.5)) or 0.5
        atr_value = atr if atr is not None else flow_data.get('atr')

        if dte <= 2:  # 0-2 DTE swings
            stop_pct_floor = 0.30
            target_multipliers = (1.75, 2.50, 4.00)
            atr_multiple = Config.BULLSEYE_ATR_MULT_SHORT
        else:  # 3-5 DTE swings
            stop_pct_floor = 0.40
            target_multipliers = (2.00, 3.00, 5.00)
            atr_multiple = Config.BULLSEYE_ATR_MULT_LONG

        stop_loss = entry_price * (1 - stop_pct_floor)
        stop_basis = "static"
        stop_distance = None
        if atr_value and atr_value > 0:
            stop_distance_estimate = atr_value * delta_abs * atr_multiple
            if stop_distance_estimate > 0:
                stop_loss = max(entry_price - stop_distance_estimate, stop_loss)
                stop_distance = stop_distance_estimate
                stop_basis = "atr"

        target1 = entry_price * target_multipliers[0]
        target2 = entry_price * target_multipliers[1]
        target3 = entry_price * target_multipliers[2]

        # Trailing stop after target 1
        trail_trigger = target1
        trail_percent = 0.25  # Trail by 25%

        return {
            'stop_loss': round(stop_loss, 2),
            'stop_basis': stop_basis,
            'stop_distance': None if stop_distance is None else round(stop_distance, 2),
            'target1': round(target1, 2),
            'target2': round(target2, 2),
            'target3': round(target3, 2),
            'trail_trigger': trail_trigger,
            'trail_percent': trail_percent,
            'breakeven_trigger': round(target1, 2),
            'management': "Scale out: 50% @ T1, 30% @ T2, trail 20% remainder",
            'atr': None if atr_value is None else round(atr_value, 2)
        }
    
    async def _get_days_premium(self, symbol: str) -> float:
        """
        Get total premium for symbol today.
        
        Note: Currently returns default value. Future enhancement would aggregate
        all flows for the symbol from today's trading session.
        """
        try:
            # Placeholder for future implementation
            return 5000000.0  # Default $5M
        except Exception as e:
            logger.error(f"Error getting day's premium for {symbol}: {e}")
            return 5000000.0
    
    def _get_similar_flows(self, signal: Dict, hours: int = 24) -> list:
        """Get similar directional flows in past N hours"""
        similar = []
        cutoff = datetime.now() - timedelta(hours=hours)
        
        for sig_key, sig_time in self.signal_history.items():
            if sig_time >= cutoff:
                parts = sig_key.split('_')
                if len(parts) >= 2 and parts[0] == signal['ticker'] and parts[1] == signal['type']:
                    similar.append(sig_key)
        
        return similar
    
    def _generate_trade_thesis(self, signal: Dict) -> str:
        """Generate narrative explanation for the trade"""
        
        if signal['trade_tag'] in ['🐋 WHALE', '🦈 SHARK']:
            size_narrative = f"This {signal['trade_tag']} trade represents MASSIVE institutional conviction"
        else:
            size_narrative = "Large institutional money is positioning"
        
        if signal['is_sweep']:
            urgency_narrative = "executed as an URGENT SWEEP at the ask"
        elif signal['is_block']:
            urgency_narrative = "came through as a positioned BLOCK trade"
        else:
            urgency_narrative = "shows clear directional intent"
        
        momentum_narrative = ""
        if signal['momentum_direction'] == signal['type'].lower()[:-1] + 'ish':
            momentum_narrative = f" The {signal['momentum_direction'].upper()} momentum supports this directional bet."
        
        dte_narrative = f"With only {signal['days_to_expiry']} days to expiry, this institution expects a move SOON."
        
        return f"{size_narrative} - ${signal['premium']/1_000_000:.1f}M {urgency_narrative}.{momentum_narrative} {dte_narrative}"
    
    def _get_momentum_status(self, signal: Dict) -> str:
        """Get formatted momentum status"""
        direction = signal['momentum_direction'].upper()
        strength = signal['momentum_strength']
        
        if strength >= 0.7:
            strength_text = "STRONG"
        elif strength >= 0.5:
            strength_text = "MODERATE"
        else:
            strength_text = "WEAK"
        
        alignment = "✅ ALIGNED" if (
            (direction == "BULLISH" and signal['type'] == "CALL") or 
            (direction == "BEARISH" and signal['type'] == "PUT")
        ) else "⚠️ CONTRARIAN"
        
        return f"{direction} ({strength_text} {strength:.2f}) {alignment}"

    async def stop(self):
        if self._outcome_task and not self._outcome_task.done():
            self._outcome_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._outcome_task
            self._outcome_task = None
        await super().stop()
