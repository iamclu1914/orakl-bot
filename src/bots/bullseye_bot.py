"""Bullseye Bot - AI signal tool for intraday movements"""
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
    Bullseye Bot - Swing Trading Signal Bot
    Identifies high-conviction swing trades that can pan out over a few days to a few weeks.
    Focuses on unusual volume, smart money, and price action confirmation.
    """

    def __init__(self, webhook_url: str, watchlist: List[str], fetcher: DataFetcher, analyzer: OptionsAnalyzer):
        super().__init__(webhook_url, "Bullseye Bot", scan_interval=300)  # Scan every 5 minutes
        self.watchlist = watchlist
        self.fetcher = fetcher
        self.analyzer = analyzer
        self.signal_history = {}

    async def scan_and_post(self):
        """Scan for high-conviction swing trades"""
        logger.info(f"{self.name} scanning for swing trade opportunities")

        if not MarketHours.is_market_open():
            logger.debug(f"{self.name} - Market closed, skipping scan")
            return
        
        market_context = await MarketContext.get_market_context(self.fetcher)
        
        tasks = [self._scan_for_swing_trade(symbol, market_context) for symbol in self.watchlist]
        all_signals = await asyncio.gather(*tasks, return_exceptions=True)
        
        flat_signals = [signal for sublist in all_signals if isinstance(sublist, list) for signal in sublist]
        
        # Rank and post top signals
        top_signals = sorted(flat_signals, key=lambda x: x['bullseye_score'], reverse=True)[:5] # Post top 5
        
        for signal in top_signals:
            await self._post_signal(signal)

    async def _scan_for_swing_trade(self, symbol: str, market_context: Dict) -> List[Dict]:
        """
        Scan a single symbol for swing trade setups using efficient REST flow detection.

        NEW APPROACH (REST):
        - Uses detect_unusual_flow() with $5K premium threshold
        - ATM filtering (delta 0.4-0.6 range)
        - 7-60 day DTE range for swing trades
        """
        signals = []
        try:
            current_price = await self.fetcher.get_stock_price(symbol)
            if not current_price:
                return signals

            # NEW: Use efficient flow detection (single API call)
            flows = await self.fetcher.detect_unusual_flow(
                underlying=symbol,
                min_premium=500,  # $500 minimum for testing (was Config.BULLSEYE_MIN_PREMIUM $5K)
                min_volume_delta=5  # At least 5 contracts of volume change (was 10)
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
                total_volume = flow['total_volume']
                volume_delta = flow['volume_delta']
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

                # Filter 1: DTE range (7-60 days for swing trades)
                if days_to_expiry < 7 or days_to_expiry > 60:
                    continue

                # Filter 2: Liquidity guards (Phase 1 - with diagnostic logging)
                # Minimum open interest ≥ 500
                if open_interest < 500:
                    logger.debug(f"Rejected {symbol} ${strike} {opt_type}: OI {open_interest} < 500")
                    continue

                # Bid-ask spread ≤ 5% (spread / mid-price)
                if bid > 0 and ask > 0:
                    mid_price = (bid + ask) / 2
                    spread_pct = ((ask - bid) / mid_price) * 100 if mid_price > 0 else 100
                    if spread_pct > 5.0:
                        logger.debug(f"Rejected {symbol} ${strike} {opt_type}: spread {spread_pct:.2f}% > 5%")
                        continue

                # Filter 3: VOI ratio (volume/OI > 3.0)
                if open_interest == 0 or total_volume < 100:
                    logger.debug(f"Rejected {symbol} ${strike} {opt_type}: insufficient volume {total_volume}")
                    continue

                voi_ratio = total_volume / open_interest
                if voi_ratio < 3.0:
                    logger.debug(f"Rejected {symbol} ${strike} {opt_type}: VOI {voi_ratio:.1f}x < 3.0x")
                    continue

                # Filter 4: ATM options only (delta 0.4-0.6 range)
                if abs(delta) < 0.4 or abs(delta) > 0.6:
                    logger.debug(f"Rejected {symbol} ${strike} {opt_type}: delta {abs(delta):.2f} outside 0.4-0.6")
                    continue

                # Filter 5: Strike distance (within 15% of current price)
                strike_distance = abs(strike - current_price) / current_price
                if strike_distance > 0.15:
                    logger.debug(f"Rejected {symbol} ${strike} {opt_type}: strike {strike_distance*100:.1f}% from price")
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

                # Calculate Bullseye score with new factors
                bullseye_score = self._calculate_bullseye_score_v2(
                    voi_ratio=voi_ratio,
                    premium=premium,
                    momentum_strength=momentum['strength'],
                    days_to_expiry=days_to_expiry,
                    itm_probability=itm_probability,
                    liquidity_score=liquidity_score
                )

                if bullseye_score >= Config.MIN_BULLSEYE_SCORE:
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
                        'bullseye_score': bullseye_score,
                        'market_context': market_context,
                        'volume_delta': volume_delta,
                        'delta': delta,
                        'gamma': flow.get('gamma', 0),
                        'vega': flow.get('vega', 0),
                        'itm_probability': itm_probability,
                        'expected_move_5d': em5,
                        'liquidity_score': liquidity_score,
                        'bid_ask_spread_pct': spread_pct if bid > 0 and ask > 0 else None,
                        'implied_volatility': implied_volatility,
                        # Volume velocity metrics (NEW)
                        'volume_velocity': volume_velocity,
                        'flow_intensity': flow_intensity
                    }

                    signal_key = f"{symbol}_{opt_type}_{strike}_{expiration}"
                    if signal_key not in self.signal_history or \
                       (datetime.now() - self.signal_history[signal_key]).total_seconds() > 3600 * 4:
                        signals.append(signal)
                        self.signal_history[signal_key] = datetime.now()

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

    def _calculate_bullseye_score_v2(self, voi_ratio: float, premium: float,
                                     momentum_strength: float, days_to_expiry: int,
                                     itm_probability: float, liquidity_score: float) -> int:
        """
        Calculate the Bullseye Score v2 with Phase 1 enhancements.

        Updated Weights:
        - VOI Ratio: 30% (reduced from 35%)
        - Premium: 25% (reduced from 30%)
        - Momentum: 15% (reduced from 20%)
        - ITM Probability: 15% (NEW)
        - DTE Sweet Spot: 10% (reduced from 15%)
        - Liquidity Quality: 5% (NEW)

        Returns:
            Score between 0-100
        """
        score = 0

        # VOI Ratio (30%)
        if voi_ratio >= 10:
            score += 30
        elif voi_ratio >= 5:
            score += 25
        elif voi_ratio >= 3:
            score += 20

        # Premium (25%)
        if premium >= 250000:
            score += 25
        elif premium >= 100000:
            score += 20
        elif premium >= 50000:
            score += 15
        elif premium >= 25000:
            score += 10

        # Momentum (15%)
        if momentum_strength >= 0.7:
            score += 15
        elif momentum_strength >= 0.5:
            score += 10
        elif momentum_strength >= 0.3:
            score += 5

        # ITM Probability (15% - NEW)
        if itm_probability >= 0.60:
            score += 15
        elif itm_probability >= 0.50:
            score += 12
        elif itm_probability >= 0.40:
            score += 9
        elif itm_probability >= 0.35:
            score += 6

        # DTE Sweet Spot (10%)
        if 21 <= days_to_expiry <= 45:
            score += 10
        elif 7 <= days_to_expiry <= 60:
            score += 6

        # Liquidity Quality (5% - NEW)
        score += int(liquidity_score * 5)

        return min(score, 100)

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
            sma_50 = daily_bars['close'].rolling(window=50).mean().iloc[-1]
            
            direction = 'neutral'
            strength = 0.5
            
            if sma_20 > sma_50 and daily_bars['close'].iloc[-1] > sma_20:
                direction = 'bullish'
                strength = 0.7 + (daily_bars['close'].iloc[-1] / sma_20 - 1) * 10
            elif sma_20 < sma_50 and daily_bars['close'].iloc[-1] < sma_20:
                direction = 'bearish'
                strength = 0.7 + (sma_20 / daily_bars['close'].iloc[-1] - 1) * 10
                
            return {
                'direction': direction,
                'strength': min(max(strength, 0), 1)
            }
        except Exception as e:
            logger.error(f"Error calculating momentum for {symbol}: {e}")
            return None

    async def _post_signal(self, signal: Dict):
        """Post Bullseye swing trade signal with unique ORAKL branding"""
        color = 0xFF6B35  # ORAKL Orange

        # ORAKL-style title and description
        title = f"🎯 {signal['ticker']} {signal['type']} - Bullseye Detected"

        itm_pct = signal['itm_probability'] * 100
        flow_intensity = signal.get('flow_intensity', 'NORMAL')

        # Create compelling description
        flow_emoji = {
            "AGGRESSIVE": "🔥",
            "STRONG": "⚡",
            "MODERATE": "📈",
            "NORMAL": "✅"
        }.get(flow_intensity, "✅")

        description = (
            f"{flow_emoji} **{flow_intensity} FLOW** detected with "
            f"**{signal['voi_ratio']:.1f}x** volume/OI ratio\n"
            f"💰 **${signal['premium']:,.0f}** in premium | "
            f"🎲 **{itm_pct:.1f}%** ITM probability"
        )

        # ORAKL-style fields with more context
        liquidity_quality = "Excellent" if signal['liquidity_score'] >= 0.8 else \
                           "Good" if signal['liquidity_score'] >= 0.6 else \
                           "Fair" if signal['liquidity_score'] >= 0.4 else "Moderate"

        sentiment = "BULLISH" if signal['type'] == "CALL" else "BEARISH"
        momentum_str = f"{signal['momentum_strength']:.2f}"

        fields = [
            # Contract details
            {"name": "📋 Contract", "value": f"**${signal['strike']}** {signal['type']} • Exp: **{signal['expiration']}**", "inline": False},

            # Key metrics row
            {"name": "💵 Premium", "value": f"${signal['premium']/1_000_000:.2f}M" if signal['premium'] >= 1_000_000 else f"${signal['premium']/1_000:.0f}K", "inline": True},
            {"name": "📊 Volume", "value": f"{signal.get('volume', 0):,}", "inline": True},
            {"name": "🎯 Open Interest", "value": f"{signal['open_interest']:,}", "inline": True},

            # Analysis row
            {"name": "🎲 ITM Probability", "value": f"**{itm_pct:.1f}%**", "inline": True},
            {"name": "📈 Momentum", "value": f"**{momentum_str}** {sentiment}", "inline": True},
            {"name": "💧 Liquidity", "value": liquidity_quality, "inline": True},

            # Trade info
            {"name": "⏰ Days to Expiry", "value": f"**{signal['days_to_expiry']}** days", "inline": True},
            {"name": "📏 Expected Move (5d)", "value": f"${signal['expected_move_5d']:.2f}", "inline": True},
            {"name": "🔥 Flow Intensity", "value": f"**{flow_intensity}**", "inline": True}
        ]

        # Create embed with ORAKL branding
        embed = self.create_signal_embed_with_disclaimer(
            title=title,
            description=description,
            color=color,
            fields=fields,
            footer=f"ORAKL Bullseye • Score: {signal['bullseye_score']}/100"
        )

        await self.post_to_discord(embed)
        logger.info(f"Posted Bullseye signal: {signal['ticker']} {signal['type']} ${signal['strike']} "
                   f"Score:{signal['bullseye_score']} Premium:{signal['premium']:,.0f} ITM:{itm_pct:.1f}%")
