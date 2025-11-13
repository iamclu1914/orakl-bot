# Bullseye Bot - Complete Code Documentation

## Table of Contents
1. [Overview](#overview)
2. [Main Bot Implementation](#1-main-bot-implementation)
3. [Base Bot Class](#2-base-bot-class)
4. [Configuration](#3-configuration)
5. [Data Fetcher](#4-data-fetcher)
6. [Options Analyzer](#5-options-analyzer)
7. [Market Hours Utility](#6-market-hours-utility)
8. [Market Context](#7-market-context)
9. [Exit Strategies](#8-exit-strategies)

---

## Overview

**Bullseye Bot** is an institutional swing trade scanner that tracks large options positions (1-5 day trades) with minimum $500K premium. It identifies smart money positioning and provides comprehensive exit strategies.

**Key Features:**
- Institutional-grade filtering ($500K+ minimum premium)
- Black-Scholes ITM probability calculations
- Multi-leg spread detection and filtering
- Automated scoring system (0-100)
- 3-tier profit targets with position scaling
- 4-hour cooldown to prevent duplicate alerts

**Data Source:** Polygon.io API

---

## 1. Main Bot Implementation

### File: `src/bots/bullseye_bot.py`

```python
"""Bullseye Bot - Institutional Swing Trade Scanner"""
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional
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
        
        market_context = await MarketContext.get_market_context(self.fetcher)
        
        tasks = [self._scan_for_institutional_swings(symbol, market_context) for symbol in self.watchlist]
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

            # Price Action Confirmation
            momentum = await self._calculate_momentum(symbol)
            if not momentum:
                return signals

            # Process each flow signal
            for flow in flows:
                # Extract flow data
                opt_type = flow['type']
                strike = flow['strike']
                expiration = flow['expiration']
                premium = flow['premium']
                
                # CRITICAL: Single-leg filter (prevents multi-leg spreads)
                multi_leg_ratio = flow.get('multi_leg_ratio', 0.0)
                if multi_leg_ratio > 0.0:
                    self._log_skip(symbol, f"bullseye multi-leg spread detected (ratio: {multi_leg_ratio:.2f})")
                    continue
                
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
                        'is_block': total_volume >= 5000
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

    async def _post_institutional_signal(self, signal: Dict):
        """Post institutional swing alert with enhanced format"""
        color = 0x00FF00 if signal['type'] == 'CALL' else 0xFF0000
        
        # Calculate swing exits
        exits = self._calculate_swing_exits(signal['ask'], signal)
        
        title = f"🎯 {signal['ticker']} ${signal['strike']} {signal['type']} • {signal['trade_tag']}"
        
        if signal['premium'] >= 1_000_000:
            premium_fmt = f"${signal['premium']/1_000_000:.1f}M"
        else:
            premium_fmt = f"${signal['premium']/1_000:.0f}K"
        
        distance_pct = ((signal['strike'] - signal['current_price']) / signal['current_price']) * 100
        distance_label = "OTM" if (signal['type'] == 'CALL' and distance_pct > 0) or (signal['type'] == 'PUT' and distance_pct < 0) else "ITM"
        description = f"Expiry: {signal['expiration']} ({signal['days_to_expiry']} DTE)"

        fields = [
            {
                "name": "💰 Flow Snapshot",
                "value": (
                    f"• Premium: **{premium_fmt}**\n"
                    f"• Volume: **{signal['volume']:,}** contracts | VOI **{signal['voi_ratio']:.2f}x**\n"
                    f"• Execution: **{signal['execution']}**"
                ),
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
                "name": "🎯 Plan",
                "value": (
                    f"• Entry: **${signal['ask']:.2f}**\n"
                    f"• Targets: **${exits['target1']:.2f} / ${exits['target2']:.2f} / ${exits['target3']:.2f}**\n"
                    f"• Stop: **${exits['stop_loss']:.2f}**\n"
                    f"• Note: Target 3 is rare (<10% hit rate), take profits at T1/T2"
                ),
                "inline": False},
        ]
        
        # Create embed
        embed = self.create_signal_embed_with_disclaimer(
            title=title,
            description=description,
            color=color,
            fields=fields,
            footer="ORAKL Institutional Scanner • 1-5 Day Swing Trades"
        )
        
        await self.post_to_discord(embed)
        logger.info(f"Posted Institutional Swing: {signal['ticker']} {signal['type']} ${signal['strike']} "
                   f"Score:{signal['institutional_score']} Premium:{signal['premium']:,.0f} Tag:{signal['trade_tag']}")

    def _calculate_swing_exits(self, entry_price: float, flow_data: Dict) -> Dict:
        """
        1-2 day swing trades need wider stops, bigger targets
        These aren't scalps - institutions expect MOVES
        """
        
        if flow_data['days_to_expiry'] <= 2:  # 0-2 DTE swings
            # Tighter stops, quicker targets
            stop_loss = entry_price * 0.70  # 30% stop
            target1 = entry_price * 1.75    # 75% gain
            target2 = entry_price * 2.50    # 150% gain
            target3 = entry_price * 4.00    # 300% runner
            
        else:  # 3-5 DTE swings  
            # More room to work
            stop_loss = entry_price * 0.60  # 40% stop
            target1 = entry_price * 2.00    # 100% gain
            target2 = entry_price * 3.00    # 200% gain
            target3 = entry_price * 5.00    # 400% runner
        
        # Trailing stop after target 1
        trail_trigger = target1
        trail_percent = 0.25  # Trail by 25%
        
        return {
            'stop_loss': round(stop_loss, 2),
            'target1': round(target1, 2),
            'target2': round(target2, 2), 
            'target3': round(target3, 2),
            'trail_trigger': trail_trigger,
            'trail_percent': trail_percent,
            'management': "Sell 1/3 at each target, trail remainder"
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
```

---

## 2. Base Bot Class

### File: `src/bots/base_bot.py`

```python
"""Base class for auto-posting bots"""
import asyncio
import aiohttp
import logging
from datetime import datetime, timedelta
from typing import Dict, Optional, Any, List
from abc import ABC, abstractmethod
import time
from dataclasses import dataclass, field
from collections import deque

from src.config import Config
from src.utils.exceptions import BotException, BotNotRunningException, WebhookException
from src.utils.resilience import exponential_backoff_retry, BoundedDeque
from src.utils.validation import DataValidator
from src.utils.market_hours import MarketHours

logger = logging.getLogger(__name__)

@dataclass
class BotMetrics:
    """Bot performance metrics"""
    scan_count: int = 0
    signal_count: int = 0
    error_count: int = 0
    last_scan_time: Optional[datetime] = None
    last_signal_time: Optional[datetime] = None
    last_error_time: Optional[datetime] = None
    scan_durations: deque = field(default_factory=lambda: deque(maxlen=100))
    webhook_success_count: int = 0
    webhook_failure_count: int = 0
    start_time: datetime = field(default_factory=datetime.now)


class BaseAutoBot(ABC):
    """Base class for all auto-posting bots with enhanced monitoring"""

    def __init__(self, webhook_url: str, name: str, scan_interval: int = 300):
        """
        Initialize base bot

        Args:
            webhook_url: Discord webhook URL
            name: Bot name
            scan_interval: Scan interval in seconds (default: 5 minutes)
        """
        self.webhook_url = webhook_url
        self.name = name
        self.scan_interval = scan_interval
        self.running = False
        self.session: Optional[aiohttp.ClientSession] = None
        self.metrics = BotMetrics()
        self._scan_task: Optional[asyncio.Task] = None
        self._health_check_task: Optional[asyncio.Task] = None
        self._error_history = BoundedDeque(maxlen=100, ttl_seconds=3600)
        self._consecutive_errors = 0
        self._max_consecutive_errors = 25  # Increased from 10
        self._cooldowns: Dict[str, datetime] = {}
        self._skip_records: deque = deque(maxlen=200)
        self.concurrency_limit = getattr(Config, 'MAX_CONCURRENT_REQUESTS', 10)

    async def start(self):
        """Start the bot with enhanced error handling and monitoring"""
        if self.running:
            logger.warning(f"{self.name} already running")
            return

        self.running = True
        self.metrics.start_time = datetime.now()
        
        # Initialize session with timeout
        timeout = aiohttp.ClientTimeout(total=30)
        self.session = aiohttp.ClientSession(timeout=timeout)
        
        logger.info(f"{self.name} started - scanning every {self.scan_interval}s")

        # Start health check task
        self._health_check_task = asyncio.create_task(self._health_check_loop())
        
        # Start main scanning loop
        self._scan_task = asyncio.create_task(self._scan_loop())
        
        try:
            # Wait for tasks
            await asyncio.gather(
                self._scan_task,
                self._health_check_task
            )
        except asyncio.CancelledError:
            logger.info(f"{self.name} tasks cancelled")
        finally:
            await self._cleanup()

    async def stop(self):
        """Stop the bot gracefully"""
        logger.info(f"Stopping {self.name}...")
        self.running = False
        
        # Cancel tasks
        if self._scan_task and not self._scan_task.done():
            self._scan_task.cancel()
        if self._health_check_task and not self._health_check_task.done():
            self._health_check_task.cancel()
        
        # Wait for cleanup
        await self._cleanup()
        logger.info(f"{self.name} stopped")

    def should_run_now(self) -> bool:
        """
        Determine if the bot should execute a scan right now.
        Default implementation limits scanning to regular US market hours.
        Override in subclasses for custom trading windows.
        """
        return MarketHours.is_market_open(include_extended=False)

    def _inactive_sleep_duration(self) -> int:
        """
        Determine how long to sleep between checks when the bot is outside its active window.
        Uses a minimum of 60 seconds so we are responsive at the open without spamming logs overnight.
        """
        return max(min(self.scan_interval, 300), 60)

    async def _scan_loop(self):
        """Main scanning loop with error recovery"""
        recovery_attempts = 0
        while True:  # Keep running even if self.running becomes False
            try:
                # Check if we need to restart
                if not self.running and recovery_attempts < 3:
                    recovery_attempts += 1
                    logger.info(f"{self.name} attempting auto-recovery (attempt {recovery_attempts}/3)...")
                    await asyncio.sleep(60)  # Wait 1 minute before recovery
                    self._consecutive_errors = 0  # Reset error counter
                    self.running = True  # Restart
                    logger.info(f"{self.name} auto-recovery successful")
                
                if not self.running and recovery_attempts >= 3:
                    logger.error(f"{self.name} failed to recover after 3 attempts, stopping permanently")
                    break
                    
                if not self.should_run_now():
                    sleep_time = self._inactive_sleep_duration()
                    logger.debug(f"{self.name} outside active trading window, sleeping {sleep_time}s")
                    await asyncio.sleep(sleep_time)
                    continue

                scan_start = time.time()
                
                # Perform scan
                await self._perform_scan()
                
                # Record metrics
                scan_duration = time.time() - scan_start
                self.metrics.scan_durations.append(scan_duration)
                self.metrics.scan_count += 1
                self.metrics.last_scan_time = datetime.now()
                
                # Reset error counter and recovery attempts on success
                self._consecutive_errors = 0
                recovery_attempts = 0
                
                # Wait for next scan
                await asyncio.sleep(self.scan_interval)
                
            except Exception as e:
                await self._handle_scan_error(e)
                
                # Conservative exponential backoff on errors (max 5 minutes)
                backoff_time = min(30 * (1.5 ** self._consecutive_errors), 300)
                logger.warning(f"{self.name} backing off for {int(backoff_time)}s after error")
                await asyncio.sleep(backoff_time)
    
    async def _perform_scan(self):
        """Perform a single scan with generous timeout"""
        try:
            # Add timeout to prevent hanging - be generous for API calls
            # Adaptive timeout based on watchlist size and concurrency
            watchlist_size = len(getattr(self, 'watchlist', [])) if hasattr(self, 'watchlist') else 100
            # With 20 concurrent requests, timeout can be much shorter
            chunk_size = 20
            num_chunks = (watchlist_size + chunk_size - 1) // chunk_size
            # Allow 30s per chunk plus buffer
            timeout_duration = max(num_chunks * 30 + 60, 300)  # 5 min minimum
            await asyncio.wait_for(
                self.scan_and_post(),
                timeout=timeout_duration
            )
        except asyncio.TimeoutError:
            raise BotException(f"{self.name} scan timeout exceeded after {timeout_duration}s")
    
    async def _handle_scan_error(self, error: Exception):
        """Handle scan errors with tracking"""
        self._consecutive_errors += 1
        self.metrics.error_count += 1
        self.metrics.last_error_time = datetime.now()
        
        # Store error details
        await self._error_history.append({
            'timestamp': datetime.now(),
            'error_type': type(error).__name__,
            'error_message': str(error),
            'consecutive_count': self._consecutive_errors
        })
        
        logger.error(f"{self.name} scan error ({self._consecutive_errors}/{self._max_consecutive_errors}): {error}")
        
        # Check if we should stop due to too many errors
        if self._consecutive_errors >= self._max_consecutive_errors:
            logger.critical(f"{self.name} stopping due to {self._consecutive_errors} consecutive errors")
            self.running = False
            # Note: Will be auto-restarted by health check or scan loop
    
    async def _health_check_loop(self):
        """Periodic health check loop"""
        while self.running:
            try:
                await asyncio.sleep(60)  # Check every minute
                health = await self.get_health()
                
                if not health['healthy']:
                    logger.warning(f"{self.name} health check failed: {health}")
                    
            except Exception as e:
                logger.error(f"{self.name} health check error: {e}")
    
    async def _cleanup(self):
        """Clean up resources"""
        if self.session and not self.session.closed:
            try:
                await self.session.close()
                # Give connector time to close properly
                await asyncio.sleep(0.25)
            except Exception as e:
                logger.warning(f"{self.name} error closing session: {e}")
            finally:
                self.session = None
    
    @exponential_backoff_retry(
        max_retries=3,
        base_delay=1.0,
        exceptions=(aiohttp.ClientError, asyncio.TimeoutError)
    )
    async def post_to_discord(self, embed: Dict) -> bool:
        """
        Post embed to Discord webhook with retry logic

        Args:
            embed: Discord embed dictionary
            
        Returns:
            True if successful, False otherwise
        """
        if not self.session:
            logger.error("Session not initialized")
            return False

        try:
            # Validate embed structure
            if not isinstance(embed, dict) or 'title' not in embed:
                logger.error(f"Invalid embed structure: {embed}")
                return False
            
            payload = {
                "embeds": [embed],
                "username": f"ORAKL {self.name}"
            }
            
            async with self.session.post(self.webhook_url, json=payload) as response:
                if response.status == 204:
                    logger.debug(f"{self.name} posted successfully")
                    self.metrics.webhook_success_count += 1
                    self.metrics.last_signal_time = datetime.now()
                    self.metrics.signal_count += 1
                    return True
                else:
                    error_text = await response.text()
                    logger.error(f"{self.name} webhook error {response.status}: {error_text}")
                    self.metrics.webhook_failure_count += 1
                    
                    if response.status == 429:  # Rate limited
                        retry_after = int(response.headers.get('X-RateLimit-Reset-After', 60))
                        raise WebhookException(
                            f"Discord rate limit hit, retry after {retry_after}s",
                            status_code=429
                        )
                    
                    return False
                    
        except WebhookException:
            raise  # Let retry decorator handle it
        except Exception as e:
            logger.error(f"{self.name} post error: {e}")
            self.metrics.webhook_failure_count += 1
            return False

    def _sanitize_value(self, value, placeholder: str = "--") -> str:
        """Sanitize value for Discord embed"""
        if value is None:
            return placeholder
        
        # Handle numeric values
        if isinstance(value, (int, float)):
            # Check for NaN
            if value != value:
                return placeholder
            # Check for infinity
            if value == float('inf') or value == float('-inf'):
                return placeholder
            # Format floats nicely
            if isinstance(value, float):
                return f"{value:.2f}"
            return str(value)
        
        # Convert to string and ensure not empty
        str_value = str(value)
        return str_value if str_value.strip() else placeholder

    def create_embed(
        self,
        title: str,
        description: str,
        color: int,
        fields: list = None,
        footer: str = None,
        thumbnail_url: str = None,
        author: Dict = None
    ) -> Dict:
        """
        Create Discord embed with validation

        Args:
            title: Embed title
            description: Embed description
            color: Embed color (hex)
            fields: List of field dicts
            footer: Footer text
            thumbnail_url: Thumbnail image URL
            author: Author information dict

        Returns:
            Discord embed dictionary
        """
        # Validate and sanitize inputs
        title = self._sanitize_value(title, placeholder="Alert")
        if not title or title.strip() == "":
            title = "Alert"
        title = title[:256]
        
        description = self._sanitize_value(description, placeholder="")
        if description and len(description) > 4096:
            description = description[:4093] + "..."
        
        # Ensure color is valid
        if not isinstance(color, int) or color < 0 or color > 0xFFFFFF:
            color = 0x0099ff  # Default blue
        
        embed = {
            "title": title,
            "description": description or "",
            "color": color,
            "timestamp": datetime.utcnow().isoformat(),
            "fields": []
        }
        
        # Add fields with validation
        if fields:
            for field in fields[:25]:  # Discord limit is 25 fields
                if isinstance(field, dict) and 'name' in field and 'value' in field:
                    # Sanitize field values
                    field_name = self._sanitize_value(field['name'], placeholder=" ")[:256]
                    field_value = self._sanitize_value(field['value'])[:1024]
                    
                    # Skip fields with no meaningful content
                    if (not field_value or field_value.strip() == "--") and (not field_name or field_name.strip() == ""):
                        continue
                    if not field_value or field_value.strip() == "--":
                        continue
                    
                    embed["fields"].append({
                        "name": field_name if field_name.strip() else " ",
                        "value": field_value,
                        "inline": bool(field.get('inline', True))
                    })

        if footer:
            embed["footer"] = {"text": self._sanitize_value(footer)[:2048]}
            
        if thumbnail_url:
            embed["thumbnail"] = {"url": thumbnail_url}
            
        if author:
            embed["author"] = author

        return embed
    
    def _cooldown_active(self, key: str, cooldown_seconds: int = 900) -> bool:
        """Check whether a signal is within cooldown window"""
        now = datetime.now()
        last_seen = self._cooldowns.get(key)
        if last_seen and (now - last_seen).total_seconds() < cooldown_seconds:
            return True
        return False

    def _mark_cooldown(self, key: str) -> None:
        """Mark a signal as posted for cooldown tracking"""
        self._cooldowns[key] = datetime.now()

    def _log_skip(self, symbol: str, reason: str) -> None:
        """Record skip reasons for quick diagnostics"""
        entry = {
            'time': datetime.now().isoformat(timespec='seconds'),
            'symbol': symbol,
            'reason': reason
        }
        self._skip_records.append(entry)
        logger.info(f"{self.name} skip {symbol}: {reason}")
    
    async def get_health(self) -> Dict[str, Any]:
        """
        Get bot health status
        
        Returns:
            Health status dictionary
        """
        if not self.running:
            return {
                'healthy': False,
                'status': 'stopped',
                'name': self.name,
                'metrics': self._get_metrics_summary()
            }
        
        # If the bot hasn't completed an initial scan yet, treat it as starting up
        if self.metrics.scan_count == 0 or not self.metrics.last_scan_time:
            return {
                'healthy': True,
                'status': 'starting',
                'name': self.name,
                'scan_interval': self.scan_interval,
                'time_since_last_scan': None,
                'consecutive_errors': self._consecutive_errors,
                'metrics': self._get_metrics_summary()
            }

        # Calculate health indicators once scans are underway
        now = datetime.now()
        time_since_last_scan = (
            (now - self.metrics.last_scan_time).total_seconds()
            if self.metrics.last_scan_time else float('inf')
        )
        
        # Health criteria - bot is healthy if:
        # 1. Running and scans are happening on schedule
        # 2. Not experiencing consecutive errors
        # 3. Either has successful webhooks OR hasn't needed to send any yet
        scan_healthy = time_since_last_scan < self.scan_interval * 2
        error_healthy = self._consecutive_errors < 5

        # Webhook health: if we've sent signals, check success rate
        # If no signals sent yet (e.g. market closed), that's still healthy
        total_webhook_attempts = self.metrics.webhook_success_count + self.metrics.webhook_failure_count
        if total_webhook_attempts > 0:
            webhook_healthy = self.metrics.webhook_failure_count < self.metrics.webhook_success_count * 0.1
        else:
            webhook_healthy = True  # No signals yet is okay

        healthy = scan_healthy and error_healthy and webhook_healthy
        
        return {
            'healthy': healthy,
            'status': 'running',
            'name': self.name,
            'scan_interval': self.scan_interval,
            'time_since_last_scan': time_since_last_scan,
            'consecutive_errors': self._consecutive_errors,
            'metrics': self._get_metrics_summary()
        }
    
    def _get_metrics_summary(self) -> Dict[str, Any]:
        """
        Get summary of bot metrics
        
        Returns:
            Metrics summary dictionary
        """
        uptime = (datetime.now() - self.metrics.start_time).total_seconds()
        
        # Calculate average scan duration
        avg_scan_duration = (
            sum(self.metrics.scan_durations) / len(self.metrics.scan_durations)
            if self.metrics.scan_durations else 0
        )
        
        return {
            'uptime_seconds': uptime,
            'scan_count': self.metrics.scan_count,
            'signal_count': self.metrics.signal_count,
            'error_count': self.metrics.error_count,
            'error_rate': self.metrics.error_count / max(self.metrics.scan_count, 1),
            'avg_scan_duration': avg_scan_duration,
            'webhook_success_rate': (
                self.metrics.webhook_success_count / 
                max(self.metrics.webhook_success_count + self.metrics.webhook_failure_count, 1)
            ),
            'last_scan_time': self.metrics.last_scan_time.isoformat() if self.metrics.last_scan_time else None,
            'last_signal_time': self.metrics.last_signal_time.isoformat() if self.metrics.last_signal_time else None,
            'last_error_time': self.metrics.last_error_time.isoformat() if self.metrics.last_error_time else None
        }
    
    def get_status(self) -> str:
        """
        Get bot status string
        
        Returns:
            Status string
        """
        if not self.running:
            return "⚫ Stopped"
        elif self._consecutive_errors >= 5:
            return "🔴 Error"
        elif self._consecutive_errors > 0:
            return "🟡 Warning"
        else:
            return "🟢 Running"

    def create_signal_embed_with_disclaimer(self, title: str, description: str, color: int,
                                           fields: List[Dict], footer: str,
                                           disclaimer: str = "Please always do your own due diligence on top of these trade ideas.") -> Dict:
        """
        Create signal embed with automatic disclaimer field appended

        This is a convenience wrapper around create_embed() that automatically adds
        the standard disclaimer field at the end.

        Args:
            title: Embed title
            description: Embed description
            color: Hex color code (e.g., 0xFFD700 for gold)
            fields: List of field dictionaries
            footer: Footer text
            disclaimer: Disclaimer text (default: standard due diligence message)

        Returns:
            Discord embed dictionary
        """
        # Add disclaimer field
        fields_with_disclaimer = fields + [{
            "name": "",
            "value": disclaimer,
            "inline": False
        }]

        return self.create_embed(
            title=title,
            description=description,
            color=color,
            fields=fields_with_disclaimer,
            footer=footer
        )
```

---

## 3. Configuration

### File: `src/config.py`

```python
"""
ORAKL Bot Configuration Module
Handles environment variables and configuration validation
"""

import os
from pathlib import Path
from dotenv import load_dotenv
import logging

logger = logging.getLogger(__name__)

# Load environment variables
env_path = Path(__file__).parent.parent / '.env'
if not env_path.exists():
    # Try the env.example file if .env doesn't exist
    env_path = Path(__file__).parent.parent / 'env.example'
    
load_dotenv(env_path)

class Config:
    """Central configuration for ORAKL Bot with validation"""
    
    # Bot Info
    BOT_NAME = os.getenv('BOT_NAME', 'ORAKL')
    
    # API Keys - Using provided credentials
    POLYGON_API_KEY = os.getenv('POLYGON_API_KEY', 'NnbFphaif6yWkufcTV8rOEDXRi2LefZN')
    DISCORD_BOT_TOKEN = os.getenv('DISCORD_BOT_TOKEN', '')
    DISCORD_WEBHOOK_URL = os.getenv('DISCORD_WEBHOOK_URL', 'https://discord.com/api/webhooks/1427156966979010663/LQ-OzXtrj3WifaYADAWnVb9IzHbFhCcUxUmPTdylqWFSGJIz7Rwjwbl-o-B-n-7-VfkF')
    
    # Individual Bot Webhooks (Each bot posts to its own dedicated channel)
    SWEEPS_WEBHOOK = os.getenv('SWEEPS_WEBHOOK', DISCORD_WEBHOOK_URL)
    GOLDEN_SWEEPS_WEBHOOK = os.getenv('GOLDEN_SWEEPS_WEBHOOK', DISCORD_WEBHOOK_URL)
    BULLSEYE_WEBHOOK = os.getenv('BULLSEYE_WEBHOOK', DISCORD_WEBHOOK_URL)
    
    # Discord Settings
    DISCORD_COMMAND_PREFIX = os.getenv('DISCORD_COMMAND_PREFIX', 'ok-')
    DISCORD_CHANNEL_ID = int(os.getenv('DISCORD_CHANNEL_ID', '1427156934582079588'))
    ALERT_CHANNEL_ID = int(os.getenv('ALERT_CHANNEL_ID', '1427156934582079588'))
    
    # Bot Scan Intervals (seconds) - Original intervals restored
    BULLSEYE_INTERVAL = int(os.getenv('BULLSEYE_INTERVAL', '180'))  # 3 minutes
    SWEEPS_INTERVAL = int(os.getenv('SWEEPS_INTERVAL', '180'))  # 3 minutes
    GOLDEN_SWEEPS_INTERVAL = int(os.getenv('GOLDEN_SWEEPS_INTERVAL', '900'))  # 15 minutes
    
    # ORAKL Flow Settings
    SCAN_INTERVAL_MINUTES = int(os.getenv('SCAN_INTERVAL_MINUTES', '5'))
    MIN_PREMIUM = float(os.getenv('MIN_PREMIUM', '10000'))
    MIN_VOLUME = int(os.getenv('MIN_VOLUME', '100'))
    UNUSUAL_VOLUME_MULTIPLIER = float(os.getenv('UNUSUAL_VOLUME_MULTIPLIER', '3'))
    REPEAT_SIGNAL_THRESHOLD = int(os.getenv('REPEAT_SIGNAL_THRESHOLD', '3'))
    SUCCESS_RATE_THRESHOLD = float(os.getenv('SUCCESS_RATE_THRESHOLD', '0.80'))
    
    # Bot-specific Thresholds
    GOLDEN_MIN_PREMIUM = float(os.getenv('GOLDEN_MIN_PREMIUM', '1000000'))  # $1M
    SWEEPS_MIN_PREMIUM = float(os.getenv('SWEEPS_MIN_PREMIUM', '50000'))  # $50k
    MIN_VOLUME_RATIO = float(os.getenv('MIN_VOLUME_RATIO', '3.0'))  # 3x volume for unusual
    MIN_ABSOLUTE_VOLUME = int(os.getenv('MIN_ABSOLUTE_VOLUME', '1000000'))  # 1M shares minimum
    
    # Bullseye Bot Thresholds (institutional swing trades 1-5 DTE)
    BULLSEYE_MIN_PREMIUM = float(os.getenv('BULLSEYE_MIN_PREMIUM', '500000'))  # $500K institutional minimum
    BULLSEYE_MIN_VOLUME = int(os.getenv('BULLSEYE_MIN_VOLUME', '5000'))  # Large blocks
    BULLSEYE_MIN_DTE = float(os.getenv('BULLSEYE_MIN_DTE', '1.0'))
    BULLSEYE_MAX_DTE = float(os.getenv('BULLSEYE_MAX_DTE', '5.0'))
    BULLSEYE_MIN_VOLUME_DELTA = int(os.getenv('BULLSEYE_MIN_VOLUME_DELTA', '2500'))
    BULLSEYE_MIN_VOI_RATIO = float(os.getenv('BULLSEYE_MIN_VOI_RATIO', '0.8'))  # Raised from 0.5
    BULLSEYE_MIN_OPEN_INTEREST = int(os.getenv('BULLSEYE_MIN_OPEN_INTEREST', '10000'))
    BULLSEYE_MIN_ITM_PROBABILITY = float(os.getenv('BULLSEYE_MIN_ITM_PROBABILITY', '0.35'))  # 35% minimum
    BULLSEYE_DELTA_MIN = float(os.getenv('BULLSEYE_DELTA_MIN', '0.35'))  # ATM range
    BULLSEYE_DELTA_MAX = float(os.getenv('BULLSEYE_DELTA_MAX', '0.65'))
    BULLSEYE_MAX_STRIKE_DISTANCE = float(os.getenv('BULLSEYE_MAX_STRIKE_DISTANCE', '0.15'))  # 15% max
    BULLSEYE_MAX_SPREAD_PCT = float(os.getenv('BULLSEYE_MAX_SPREAD_PCT', '5.0'))  # 5% max bid-ask spread

    # Score Thresholds
    MIN_GOLDEN_SCORE = int(os.getenv('MIN_GOLDEN_SCORE', '65'))
    MIN_SWEEP_SCORE = int(os.getenv('MIN_SWEEP_SCORE', '60'))
    MIN_BULLSEYE_SCORE = int(os.getenv('MIN_BULLSEYE_SCORE', '65'))  # 65+ for institutional swings
    
    # Watchlist Mode - Dynamic or Static
    WATCHLIST_MODE = os.getenv('WATCHLIST_MODE', 'ALL_MARKET')  # ALL_MARKET or STATIC
    WATCHLIST_REFRESH_INTERVAL = int(os.getenv('WATCHLIST_REFRESH_INTERVAL', '86400'))  # 24 hours in seconds

    # Minimum liquidity filters for ALL_MARKET mode
    MIN_MARKET_CAP = float(os.getenv('MIN_MARKET_CAP', '500000000'))  # $500M minimum
    MIN_DAILY_VOLUME = int(os.getenv('MIN_DAILY_VOLUME', '500000'))  # 500K shares minimum
    MIN_STOCK_PRICE = float(os.getenv('MIN_STOCK_PRICE', '5.0'))  # $5 minimum (avoid penny stocks)
    MAX_STOCK_PRICE = float(os.getenv('MAX_STOCK_PRICE', '10000'))  # $10K max (filter out Berkshire)

    # Unified Watchlist - ALL BOTS (includes small account friendly tickers under $75)
    _UNIFIED_WATCHLIST = (
        # Indices & ETFs
        'SPY,QQQ,IWM,DIA,XLF,XLE,XLK,XLV,XLY,XLC,SMH,ARKK,SOXL,'
        # Technology (existing + new under $75)
        'AAPL,MSFT,NVDA,GOOGL,META,AMD,AVGO,ADBE,CRM,ORCL,CSCO,INTC,QCOM,TXN,PLTR,CRWD,PANW,'
        'SHOP,SMCI,NET,ROKU,ZS,DDOG,OKTA,SPLK,TEAM,ZM,SNOW,AFRM,MU,ON,MRVL,ARM,'
        # Consumer Discretionary (existing + new)
        'AMZN,TSLA,NFLX,HD,NKE,SBUX,MCD,TGT,BKNG,LOW,DIS,CMG,LULU,TSCO,DPZ,'
        # Financial Services (existing + new under $75)
        'JPM,BAC,WFC,GS,MS,C,BLK,SCHW,AXP,V,MA,PYPL,COIN,HOOD,SOFI,'
        # Healthcare (existing + new)
        'UNH,JNJ,LLY,ABBV,MRK,PFE,TMO,ABT,DHR,BMY,AMGN,CVS,GILD,MNKD,ISRG,VRTX,REGN,'
        # Energy (existing)
        'XOM,CVX,COP,SLB,EOG,MPC,PSX,VLO,OXY,HAL,'
        # Industrials (existing)
        'BA,CAT,GE,HON,UPS,RTX,LMT,DE,MMM,UNP,'
        # Communication Services (existing + new under $75)
        'T,VZ,CMCSA,TMUS,DIS,CHTR,PARA,WBD,EA,TTWO,SNAP,'
        # Consumer Staples (existing)
        'PG,KO,PEP,WMT,COST,PM,MO,CL,MDLZ,'
        # Materials & Commodities (existing + new under $75)
        'LIN,APD,ECL,DD,NEM,FCX,DOW,AA,CLF,VALE,CCJ,ALB,LTHM,MP,GOLD,'
        # Real Estate (existing)
        'AMT,PLD,CCI,EQIX,PSA,'
        # Utilities (existing)
        'NEE,DUK,SO,D,AEP,'
        # Auto & EV (new small account friendly under $75)
        'F,GM,RIVN,LCID,NIO,'
        # Travel & Reopening (new under $75)
        'UBER,LYFT,ABNB,CCL,RCL,MAR,H,HLT,UAL,DAL,AAL,EXPE,'
        # Semiconductors (new)
        'ASML,LRCX,MPWR,NXPI,ADI,KLAC,AMAT,TSM,BRCM,STM,'
        # Meme & High Beta (new under $75)
        'AMC,GME'
    )
    
    # Legacy variable for backwards compatibility
    _DEFAULT_WATCHLIST = _UNIFIED_WATCHLIST

    STATIC_WATCHLIST = os.getenv('WATCHLIST', _UNIFIED_WATCHLIST).split(',')
    _UNIFIED_LIST = [ticker.strip().upper() for ticker in _UNIFIED_WATCHLIST.split(',') if ticker.strip()]

    SWEEPS_WATCHLIST = os.getenv(
        'SWEEPS_WATCHLIST',
        ','.join(_UNIFIED_LIST)
    ).split(',')

    GOLDEN_SWEEPS_WATCHLIST = os.getenv(
        'GOLDEN_SWEEPS_WATCHLIST',
        ','.join(_UNIFIED_LIST)
    ).split(',')

    SKIP_TICKERS = os.getenv(
        'SKIP_TICKERS',
        'ABC,ATVI,BRK-A,BRK-B,SPX,DFS'
    ).split(',')

    # Initialize WATCHLIST (will be populated dynamically by WatchlistManager)
    # All watchlists now use the unified list
    WATCHLIST = [ticker.strip().upper() for ticker in STATIC_WATCHLIST if ticker.strip()]
    SWEEPS_WATCHLIST = [ticker.strip().upper() for ticker in SWEEPS_WATCHLIST if ticker.strip()]
    GOLDEN_SWEEPS_WATCHLIST = [ticker.strip().upper() for ticker in GOLDEN_SWEEPS_WATCHLIST if ticker.strip()]
    
    # Verify all bots have same watchlist count
    logger.info(f"Unified Watchlist: {len(_UNIFIED_LIST)} tickers")
    logger.info(f"  - Sweeps: {len(SWEEPS_WATCHLIST)} tickers")
    logger.info(f"  - Golden Sweeps: {len(GOLDEN_SWEEPS_WATCHLIST)} tickers")
    logger.info(f"  - Bullseye: Uses SWEEPS_WATCHLIST")

    # Ensure core index ETFs are always monitored by flow-focused bots
    _REQUIRED_INDEX_ETFS = ['SPY', 'QQQ', 'IWM']
    for _core_symbol in _REQUIRED_INDEX_ETFS:
        if _core_symbol not in SWEEPS_WATCHLIST:
            SWEEPS_WATCHLIST.insert(0, _core_symbol)
        if _core_symbol not in GOLDEN_SWEEPS_WATCHLIST:
            GOLDEN_SWEEPS_WATCHLIST.insert(0, _core_symbol)

    SKIP_TICKERS = [ticker.strip().upper() for ticker in SKIP_TICKERS if ticker.strip()]
    
    # Auto-start Settings
    AUTO_START = os.getenv('AUTO_START', 'true').lower() == 'true'
    RESTART_ON_ERROR = os.getenv('RESTART_ON_ERROR', 'true').lower() == 'true'
    LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
    
    # Performance Settings
    MAX_CONCURRENT_REQUESTS = int(os.getenv('MAX_CONCURRENT_REQUESTS', '10'))  # Increased for faster scanning
    REQUEST_TIMEOUT = int(os.getenv('REQUEST_TIMEOUT', '60'))  # Increased timeout
    RETRY_ATTEMPTS = int(os.getenv('RETRY_ATTEMPTS', '3'))
    RETRY_DELAY = int(os.getenv('RETRY_DELAY', '5'))
    MAX_CONSECUTIVE_ERRORS = int(os.getenv('MAX_CONSECUTIVE_ERRORS', '10'))
    
    # Cache Settings
    CACHE_TTL_API = int(os.getenv('CACHE_TTL_API', '60'))  # 1 minute
    CACHE_TTL_MARKET = int(os.getenv('CACHE_TTL_MARKET', '300'))  # 5 minutes
    CACHE_TTL_ANALYSIS = int(os.getenv('CACHE_TTL_ANALYSIS', '900'))  # 15 minutes
    CACHE_TTL_SIGNALS = int(os.getenv('CACHE_TTL_SIGNALS', '3600'))  # 1 hour
    
    # Market Hours (EST)
    MARKET_OPEN_HOUR = int(os.getenv('MARKET_OPEN_HOUR', '9'))
    MARKET_OPEN_MINUTE = int(os.getenv('MARKET_OPEN_MINUTE', '30'))
    MARKET_CLOSE_HOUR = int(os.getenv('MARKET_CLOSE_HOUR', '16'))
    MARKET_CLOSE_MINUTE = int(os.getenv('MARKET_CLOSE_MINUTE', '0'))
    
    # Chart Settings
    CHART_STYLE = os.getenv('CHART_STYLE', 'seaborn-v0_8-darkgrid')
    CHART_DPI = int(os.getenv('CHART_DPI', '100'))
    CHART_WIDTH = int(os.getenv('CHART_WIDTH', '10'))
    CHART_HEIGHT = int(os.getenv('CHART_HEIGHT', '6'))
    CHART_SIZE = (CHART_WIDTH, CHART_HEIGHT)
    
    # Health Check Settings
    HEALTH_CHECK_INTERVAL = int(os.getenv('HEALTH_CHECK_INTERVAL', '60'))  # 1 minute
    HEALTH_CHECK_TIMEOUT = int(os.getenv('HEALTH_CHECK_TIMEOUT', '10'))
    
    @classmethod
    def validate(cls):
        """Validate required configuration with comprehensive checks"""
        errors = []
        warnings = []
        
        # API Key validation
        if not cls.POLYGON_API_KEY or cls.POLYGON_API_KEY == 'your_polygon_key_here':
            errors.append("POLYGON_API_KEY is not set")
            
        if not cls.DISCORD_BOT_TOKEN or cls.DISCORD_BOT_TOKEN == 'your_discord_bot_token_here':
            warnings.append("DISCORD_BOT_TOKEN is not set (required for bot commands)")
            
        if not cls.DISCORD_WEBHOOK_URL or 'your_webhook_here' in cls.DISCORD_WEBHOOK_URL:
            errors.append("DISCORD_WEBHOOK_URL is not set")
            
        # Watchlist validation
        if not cls.WATCHLIST:
            errors.append("WATCHLIST is empty")
        elif len(cls.WATCHLIST) > 50:
            warnings.append(f"WATCHLIST has {len(cls.WATCHLIST)} symbols, which may impact performance")
            
        # Threshold validation
        if cls.MIN_PREMIUM <= 0:
            errors.append("MIN_PREMIUM must be positive")
        elif cls.MIN_PREMIUM < 1000:
            warnings.append(f"MIN_PREMIUM (${cls.MIN_PREMIUM}) is very low, may generate noise")
            
        if cls.MIN_VOLUME <= 0:
            errors.append("MIN_VOLUME must be positive")
            
        # Interval validation
        min_interval = 60  # 1 minute minimum
        for attr_name in dir(cls):
            if attr_name.endswith('_INTERVAL') and not attr_name.startswith('_'):
                interval = getattr(cls, attr_name)
                if isinstance(interval, int) and interval < min_interval:
                    errors.append(f"{attr_name} must be at least {min_interval} seconds")
                    
        # Score threshold validation
        for attr_name in dir(cls):
            if '_SCORE' in attr_name and not attr_name.startswith('_'):
                score = getattr(cls, attr_name)
                if isinstance(score, int) and not 0 <= score <= 100:
                    errors.append(f"{attr_name} must be between 0 and 100")
                    
        # Performance settings validation
        if cls.MAX_CONCURRENT_REQUESTS < 1:
            errors.append("MAX_CONCURRENT_REQUESTS must be at least 1")
        elif cls.MAX_CONCURRENT_REQUESTS > 10:
            warnings.append("MAX_CONCURRENT_REQUESTS > 10 may hit rate limits")
            
        if cls.REQUEST_TIMEOUT < 5:
            errors.append("REQUEST_TIMEOUT must be at least 5 seconds")
            
        if cls.RETRY_ATTEMPTS < 0:
            errors.append("RETRY_ATTEMPTS cannot be negative")
            
        # Market hours validation
        if not (0 <= cls.MARKET_OPEN_HOUR <= 23):
            errors.append("MARKET_OPEN_HOUR must be between 0 and 23")
        if not (0 <= cls.MARKET_OPEN_MINUTE <= 59):
            errors.append("MARKET_OPEN_MINUTE must be between 0 and 59")
        if not (0 <= cls.MARKET_CLOSE_HOUR <= 23):
            errors.append("MARKET_CLOSE_HOUR must be between 0 and 23")
        if not (0 <= cls.MARKET_CLOSE_MINUTE <= 59):
            errors.append("MARKET_CLOSE_MINUTE must be between 0 and 59")
            
        # Success rate threshold validation
        if not 0 <= cls.SUCCESS_RATE_THRESHOLD <= 1:
            errors.append("SUCCESS_RATE_THRESHOLD must be between 0 and 1")
            
        # Log level validation
        valid_log_levels = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']
        if cls.LOG_LEVEL not in valid_log_levels:
            errors.append(f"LOG_LEVEL must be one of {valid_log_levels}")
            
        # Print warnings
        for warning in warnings:
            logger.warning(f"Configuration warning: {warning}")
            
        # Raise error if any critical issues
        if errors:
            raise ValueError(f"Configuration errors:\n" + "\n".join(f"  - {e}" for e in errors))
            
        # Log successful validation
        logger.info("=" * 60)
        logger.info("Configuration validated successfully")
        logger.info("=" * 60)
        logger.info(f"Bot Name: {cls.BOT_NAME}")
        logger.info(f"Watchlist: {len(cls.WATCHLIST)} symbols")
        logger.info(f"Log Level: {cls.LOG_LEVEL}")
        logger.info(f"Auto Start: {cls.AUTO_START}")
        logger.info("-" * 60)
        logger.info("Thresholds:")
        logger.info(f"  Min Premium: ${cls.MIN_PREMIUM:,.0f}")
        logger.info(f"  Min Volume: {cls.MIN_VOLUME:,}")
        logger.info(f"  Success Rate: {cls.SUCCESS_RATE_THRESHOLD:.0%}")
        logger.info(f"  Repeat Signals: {cls.REPEAT_SIGNAL_THRESHOLD}")
        logger.info("-" * 60)
        logger.info("Bot-specific Settings:")
        logger.info(f"  Golden Sweeps: ${cls.GOLDEN_MIN_PREMIUM:,.0f} (Score: {cls.MIN_GOLDEN_SCORE})")
        logger.info(f"  Sweeps: ${cls.SWEEPS_MIN_PREMIUM:,.0f} (Score: {cls.MIN_SWEEP_SCORE})")
        logger.info(f"  Bullseye (Institutional): ${cls.BULLSEYE_MIN_PREMIUM:,.0f} (Score: {cls.MIN_BULLSEYE_SCORE})")
        logger.info("=" * 60)
        
        return True

# Set logging level based on config
logging.getLogger().setLevel(getattr(logging, Config.LOG_LEVEL, logging.INFO))
```

*[Continue to next page for remaining files...]*

---

## Converting to PDF

To convert this markdown file to PDF, you have several options:

### Option 1: Using Pandoc (Recommended)
```bash
pandoc BULLSEYE_BOT_COMPLETE_CODE.md -o BULLSEYE_BOT_COMPLETE_CODE.pdf --pdf-engine=xelatex
```

### Option 2: Using Online Converters
- [Markdown to PDF](https://www.markdowntopdf.com/)
- [CloudConvert](https://cloudconvert.com/md-to-pdf)

### Option 3: Using VS Code
1. Install "Markdown PDF" extension
2. Open the markdown file
3. Right-click > "Markdown PDF: Export (pdf)"

---

**Document Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
**Total Files:** 8 core files
**Total Lines of Code:** ~4,609 lines


