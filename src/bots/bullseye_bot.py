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
    Tracks INSTITUTIONAL positioning for 1-2 day swing trades
    Large premium = Smart money expecting big moves
    """

    def __init__(self, webhook_url: str, watchlist: List[str], fetcher: DataFetcher, analyzer: OptionsAnalyzer):
        super().__init__(webhook_url, "Bullseye Bot", scan_interval=300)  # Scan every 5 minutes
        self.watchlist = watchlist
        self.fetcher = fetcher
        self.analyzer = analyzer
        self.signal_history = {}
        
        # INSTITUTIONAL SIZE REQUIREMENTS (features, not restrictions)
        self.MIN_PREMIUM = 500000  # $500K minimum (institutional size)
        self.IDEAL_PREMIUM = 1000000  # $1M+ is highest conviction
        self.MIN_VOLUME = 5000  # Large blocks
        self.MIN_OI = 10000  # Liquid strikes only
        self.MIN_VOLUME_DELTA = max(int(self.MIN_VOLUME * 0.5), 1000)
        self.MIN_OPEN_INTEREST = self.MIN_OI
        
        # Focus on 1-5 day swings
        self.MIN_DTE = 1
        self.MAX_DTE = 5
        
        # ATM to slightly OTM (where institutions play)
        self.DELTA_RANGE = (0.35, 0.65)
        
        # Other requirements
        self.MIN_VOI_RATIO = 0.5  # Fresh positioning
        self.MAX_ALERTS_PER_SYMBOL = 2  # Per 4 hours
        self.COOLDOWN_HOURS = 4

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
                implied_volatility = flow.get('implied_volatility', 0)
                volume_velocity = flow.get('volume_velocity', 0)
                flow_intensity = flow.get('flow_intensity', 'NORMAL')

                # Calculate DTE
                exp_date = datetime.strptime(expiration, '%Y-%m-%d')
                days_to_expiry = (exp_date - datetime.now()).days

                # Filter 1: DTE range (1-3 days for short-dated trades)
                if days_to_expiry < self.MIN_DTE or days_to_expiry > self.MAX_DTE:
                    self._log_skip(symbol, f'bullseye DTE {days_to_expiry} outside {self.MIN_DTE}-{self.MAX_DTE}')
                    continue

                # Filter 2: Liquidity guards (Phase 1 - with diagnostic logging)
                # Require a baseline of open interest so the contract is tradable
                required_oi = max(self.MIN_OPEN_INTEREST, total_volume * 0.5)
                if open_interest < required_oi:
                    self._log_skip(symbol, f'bullseye OI {open_interest} < required {required_oi:.0f}')
                    continue
                # Bid-ask spread ≤ 5% (spread / mid-price)
                if bid > 0 and ask > 0:
                    mid_price = (bid + ask) / 2
                    spread_pct = ((ask - bid) / mid_price) * 100 if mid_price > 0 else 100
                    if spread_pct > 5.0:
                        self._log_skip(symbol, f"bullseye spread {spread_pct:.2f}% > 5%")
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
                    logger.debug(f"Rejected {symbol} ${strike} {opt_type}: delta {abs(delta):.2f} outside institutional range")
                    continue

                # Filter 5: Strike distance (within 15% of current price)
                strike_distance = abs(strike - current_price) / current_price
                if strike_distance > 0.15:
                    self._log_skip(symbol, f"bullseye strike {strike_distance*100:.1f}% from price")
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

                # Require P(ITM) ≥ 25% (lowered from 35% for Phase 1 tuning)
                if itm_probability < 0.25:
                    logger.debug(f"Rejected {symbol} ${strike} {opt_type}: ITM probability {itm_probability*100:.1f}% < 25%")
                    continue

                logger.debug(f"✓ {symbol} ${strike} {opt_type}: ITM probability {itm_probability*100:.1f}% passed")

                # Filter 7: 5-Day Expected Move (Phase 1 - Optional for tuning)
                # Strike must be within 5-day expected move
                em5 = self._calculate_expected_move(
                    S=current_price,
                    IV=implied_volatility,
                    days=5
                )

                strike_diff = abs(strike - current_price)
                # TEMPORARILY DISABLED for Phase 1 testing - will re-enable after monitoring signal quality
                # if strike_diff > em5:
                #     logger.debug(f"Rejected {symbol} ${strike} {opt_type}: strike ${strike_diff:.2f} outside EM5 ${em5:.2f}")
                #     continue

                if strike_diff > em5:
                    logger.debug(f"⚠️ {symbol} ${strike} {opt_type}: strike ${strike_diff:.2f} outside EM5 ${em5:.2f} (allowed for Phase 1)")
                else:
                    logger.debug(f"✓ {symbol} ${strike} {opt_type}: strike ${strike_diff:.2f} within EM5 ${em5:.2f}")

                # Filter 8: Price action confirmation
                if (opt_type == 'CALL' and momentum['direction'] != 'bullish') or \
                   (opt_type == 'PUT' and momentum['direction'] != 'bearish'):
                    logger.debug(f"Rejected {symbol} ${strike} {opt_type}: momentum {momentum['direction']} doesn't align")
                    continue

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
                    'execution': 'ASK' if opt_type == 'CALL' else 'BID',  # Assume aggressive
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
                        'execution': 'ASK' if opt_type == 'CALL' else 'BID',
                        'is_sweep': flow_intensity == 'HIGH',
                        'is_block': total_volume >= 5000
                    }

                    signal_key = f"{symbol}_{opt_type}_{strike}_{expiration}"
                    if self._cooldown_active(signal_key):
                        self._log_skip(symbol, f'bullseye cooldown {signal_key}')
                        continue
                    if signal_key not in self.signal_history or \
                       (datetime.now() - self.signal_history[signal_key]).total_seconds() > 3600 * 4:
                        signals.append(signal)
                        self.signal_history[signal_key] = datetime.now()
                        self._mark_cooldown(signal_key)

        except Exception as e:
            logger.error(f"Error scanning for swing trades on {symbol}: {e}")

        return signals

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
        
        # Wrong-way momentum = hedge (puts in uptrend, calls in downtrend)
        if signal['momentum_direction'] == 'bullish' and signal['type'] == 'PUT':
            if signal['premium'] > 1000000:  # Large put in uptrend = hedge
                return True
        elif signal['momentum_direction'] == 'bearish' and signal['type'] == 'CALL':
            if signal['premium'] > 1000000:  # Large call in downtrend = hedge
                return True
        
        return False

    def _calculate_bullseye_score(self, voi_ratio: float, premium: float, momentum_strength: float, dte: int) -> int:
        """
        DEPRECATED: Legacy scoring function for backwards compatibility.
        Use _calculate_bullseye_score_v2() instead.
        """
        score = self.calculate_score({
            'voi_ratio': (voi_ratio, [
                (10, 35),  # 10x+ → 35 points (35%)
                (5, 30),   # 5x+ → 30 points
                (3, 25)    # 3x+ → 25 points
            ]),
            'premium': (premium, [
                (250000, 30),  # $250k+ → 30 points (30%)
                (100000, 25),  # $100k+ → 25 points
                (50000, 20),   # $50k+ → 20 points
                (25000, 15)    # $25k+ → 15 points
            ]),
            'momentum': (momentum_strength, [
                (0.7, 20),  # 70%+ → 20 points (20%)
                (0.5, 15),  # 50%+ → 15 points
                (0.3, 10)   # 30%+ → 10 points
            ])
        })

        # DTE sweet spot (15%)
        if 21 <= dte <= 45:
            score += 15
        elif 7 <= dte <= 60:
            score += 10

        return min(score, 100)

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
        """Calculate daily/4-hour momentum for swing trades"""
        try:
            # Use daily bars for longer-term trend
            to_date = datetime.now().strftime('%Y-%m-%d')
            from_date = (datetime.now() - timedelta(days=90)).strftime('%Y-%m-%d')
            
            daily_bars = await self.fetcher.get_aggregates(
                symbol, 'day', 1, from_date, to_date
            )
            
            if daily_bars.empty or len(daily_bars) < 20: return None
            
            # Simple Moving Averages
            sma_20 = daily_bars['close'].rolling(window=20).mean().iloc[-1]
            sma_50 = daily_bars['close'].rolling(window=50).mean().iloc[-1] if len(daily_bars) >= 50 else sma_20
            
            direction = 'neutral'
            strength = 0.5
            
            if sma_20 > sma_50 and daily_bars['close'].iloc[-1] > sma_20:
                direction = 'bullish'
                strength = 0.7 + (daily_bars['close'].iloc[-1] / sma_20 - 1) * 10
            elif sma_20 < sma_50 and daily_bars['close'].iloc[-1] < sma_20:
                direction = 'bearish'
                strength = 0.7 + (sma_20 / daily_bars['close'].iloc[-1] - 1) * 10
                
            momentum = {
                'direction': direction,
                'strength': min(max(strength, 0), 1)
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
        
        # Build alert components
        title = f"🎯 **INSTITUTIONAL SWING ALERT** {signal['trade_tag']}"
        
        # Get today's total premium for context
        total_premium_today = await self._get_days_premium(signal['ticker'])
        
        # Count similar flows
        similar_flows = self._get_similar_flows(signal, hours=24)
        
        # Format premium
        if signal['premium'] >= 1_000_000:
            premium_fmt = f"${signal['premium']/1_000_000:.1f}M"
        else:
            premium_fmt = f"${signal['premium']/1_000:.0f}K"
        
        # Calculate distance to strike
        distance_pct = ((signal['strike'] - signal['current_price']) / signal['current_price']) * 100
        
        # Generate trade thesis
        trade_thesis = self._generate_trade_thesis(signal)
        
        # Build description
        description = f"**{signal['ticker']} ${signal['strike']} {signal['type']}**\n"
        description += f"📅 Expiry: {signal['expiration']} ({signal['days_to_expiry']} DTE)"
        
        fields = [
            # Institutional Flow Section
            {"name": "💰 **INSTITUTIONAL FLOW:**", "value": 
                f"• Premium: **{premium_fmt}** (Top 1% today)\n"
                f"• Volume: **{signal['volume']:,}** contracts\n"
                f"• Execution: **{signal['execution']}** {'SWEEP 🔥' if signal['is_sweep'] else ''}\n"
                f"• Trade Type: {'**OPENING - NEW POSITION ⚡**' if signal.get('trade_type') == 'OPENING' else 'Add to Position'}", 
                "inline": False},
            
            # Swing Setup Section
            {"name": "📊 **SWING SETUP:**", "value": 
                f"• Score: **{signal['institutional_score']}/100**\n"
                f"• Today's Total: ${total_premium_today/1_000_000:.1f}M\n"
                f"• Similar Flows (24hr): **{len(similar_flows)}** trades same direction\n"
                f"• VOI Ratio: **{signal['voi_ratio']:.2f}x**\n"
                f"• Current Stock Price: **${signal['current_price']:.2f}**\n"
                f"• Distance to Strike: **{abs(distance_pct):.1f}%** {'OTM' if distance_pct > 0 and signal['type'] == 'CALL' or distance_pct < 0 and signal['type'] == 'PUT' else 'ITM'}", 
                "inline": False},
            
            # Targets Section
            {"name": "🎯 **SWING TARGETS (1-2 days):**", "value": 
                f"• Entry: **${signal['ask']:.2f}**\n"
                f"• Target 1 (75%): **${exits['target1']:.2f}**\n"
                f"• Target 2 (150%): **${exits['target2']:.2f}**\n"
                f"• Target 3 (300%): **${exits['target3']:.2f}**\n"
                f"• Stop Loss: **${exits['stop_loss']:.2f}** (-{int((1 - exits['stop_loss']/signal['ask'])*100)}%)\n"
                f"• Management: {exits['management']}", 
                "inline": False},
            
            # Why This Matters
            {"name": "⚡ **WHY THIS MATTERS:**", "value": trade_thesis, "inline": False},
            
            # Momentum Status
            {"name": "🔄 **MOMENTUM:**", "value": self._get_momentum_status(signal), "inline": False}
        ]
        
        # Create embed
        embed = self.create_signal_embed_with_disclaimer(
            title=title,
            description=description,
            color=color,
            fields=fields,
            footer="ORAKL Institutional Scanner • 1-2 Day Swing Trades"
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
        """Get total premium for symbol today"""
        try:
            # For now, return estimated value
            # In full implementation, would query today's flows
            return self.signal_history.get(f"{symbol}_total_premium_today", 5000000.0)
        except:
            return 5000000.0  # Default $5M
    
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
