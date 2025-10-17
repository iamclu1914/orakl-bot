"""
STRAT Pattern Detection Bot
Scans for 3-2-2 Reversal, 2-2 Reversal Retrigger, and 1-3-1 Miyagi patterns
"""
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, Optional, List
import pytz
from discord_webhook import DiscordWebhook, DiscordEmbed

from ..config import Config
from ..data_fetcher import DataFetcher
from src.utils.market_hours import MarketHours
from src.utils.sector_watchlist import STRAT_COMPLETE_WATCHLIST
import numpy as np

logger = logging.getLogger(__name__)

class STRATPatternBot:
    """Bot for detecting STRAT trading patterns"""

    def __init__(self, data_fetcher: DataFetcher = None):
        self.name = "STRAT Pattern Scanner"
        # Use provided data_fetcher or create new one with API key from config
        self.data_fetcher = data_fetcher if data_fetcher else DataFetcher(Config.POLYGON_API_KEY)
        self.webhook_url = Config.STRAT_WEBHOOK
        self.scan_interval = Config.STRAT_INTERVAL
        self.detected_today = {}
        self.is_running = False
        self.running = False  # Add for compatibility with BotManager.get_bot_status()
        self.est = pytz.timezone('America/New_York')
        self.pattern_states = {}  # Track patterns waiting for conditions

        logger.info(f"{self.name} initialized")

    def validate_bar(self, bar: Dict) -> bool:
        """Validate a bar has all required fields and valid data"""
        required_fields = ['h', 'l', 'o', 'c']

        for field in required_fields:
            if field not in bar:
                return False
            value = bar[field]
            if value is None or value < 0:
                return False

        high, low, open_price, close = bar['h'], bar['l'], bar['o'], bar['c']

        if high < low:
            return False
        if not (low <= open_price <= high) or not (low <= close <= high):
            return False

        return True

    def detect_bar_type(self, current: Dict, previous: Dict) -> int:
        """
        Identify STRAT bar types
        Returns: 3 (outside), 1 (inside), 2 (up), -2 (down), 0 (none)
        """
        if not self.validate_bar(current) or not self.validate_bar(previous):
            return 0

        curr_high, curr_low = current['h'], current['l']
        prev_high, prev_low = previous['h'], previous['l']

        if curr_high > prev_high and curr_low < prev_low:
            return 3  # Outside bar
        elif curr_high <= prev_high and curr_low >= prev_low:
            return 1  # Inside bar
        elif curr_high > prev_high and curr_low >= prev_low:
            return 2  # 2U (Up)
        elif curr_high <= prev_high and curr_low < prev_low:
            return -2  # 2D (Down)
        return 0

    async def calculate_dynamic_confidence(self, ticker: str, pattern_type: str, 
                                          pattern_data: Dict, bars: List[Dict]) -> float:
        """
        Calculate dynamic confidence score based on multiple factors:
        - Volume analysis (compare to average)
        - Trend alignment
        - Pattern clarity/strength
        - Market conditions
        - Recent price action
        """
        base_scores = {
            '3-2-2 Reversal': 0.65,      # Base 65%
            '2-2 Reversal': 0.60,         # Base 60%
            '1-3-1 Miyagi': 0.70          # Base 70%
        }
        
        confidence = base_scores.get(pattern_type, 0.65)
        adjustments = []
        
        try:
            # 1. Volume Analysis (±15%)
            if len(bars) >= 20:
                volumes = [b.get('v', 0) for b in bars[-20:] if 'v' in b and b['v'] > 0]
                if volumes:
                    avg_volume = np.mean(volumes)
                    recent_volume = bars[-1].get('v', 0) if bars else 0
                    
                    if recent_volume > avg_volume * 2:
                        volume_boost = 0.15
                        adjustments.append(("High volume", volume_boost))
                    elif recent_volume > avg_volume * 1.5:
                        volume_boost = 0.10
                        adjustments.append(("Above avg volume", volume_boost))
                    elif recent_volume > avg_volume:
                        volume_boost = 0.05
                        adjustments.append(("Normal volume", volume_boost))
                    else:
                        volume_boost = -0.05
                        adjustments.append(("Low volume", volume_boost))
                    
                    confidence += volume_boost
            
            # 2. Trend Alignment (±10%)
            if len(bars) >= 10:
                closes = [b['c'] for b in bars[-10:] if self.validate_bar(b)]
                if len(closes) >= 10:
                    sma = np.mean(closes)
                    current_price = closes[-1]
                    
                    # For reversal patterns, being far from SMA is good
                    distance_pct = abs(current_price - sma) / sma
                    if distance_pct > 0.03:  # More than 3% from SMA
                        trend_boost = 0.10
                        adjustments.append(("Extended from mean", trend_boost))
                    elif distance_pct > 0.02:  # 2-3% from SMA
                        trend_boost = 0.05
                        adjustments.append(("Moderate extension", trend_boost))
                    else:
                        trend_boost = 0
                        adjustments.append(("Near mean", trend_boost))
                    
                    confidence += trend_boost
            
            # 3. Pattern Clarity (±10%)
            if pattern_type == '3-2-2 Reversal' and 'bar_9am' in pattern_data:
                # Check how clear the 3-bar (outside bar) was
                bar_8am = pattern_data.get('bar_8am', {})
                bar_9am = pattern_data.get('bar_9am', {})
                
                if bar_8am and bar_9am:
                    # Larger outside bar = clearer pattern
                    bar_8am_range = bar_8am.get('h', 0) - bar_8am.get('l', 0)
                    bar_9am_range = bar_9am.get('h', 0) - bar_9am.get('l', 0)
                    
                    if bar_8am_range > bar_9am_range * 1.5:
                        clarity_boost = 0.10
                        adjustments.append(("Strong 3-bar", clarity_boost))
                    else:
                        clarity_boost = 0.05
                        adjustments.append(("Normal 3-bar", clarity_boost))
                    
                    confidence += clarity_boost
            
            # 4. Recent Volatility (±5%)
            if len(bars) >= 5:
                recent_ranges = [(b['h'] - b['l']) / b['c'] for b in bars[-5:] 
                               if self.validate_bar(b) and b['c'] > 0]
                if recent_ranges:
                    avg_range_pct = np.mean(recent_ranges) * 100
                    
                    if avg_range_pct > 2.0:  # High volatility
                        vol_boost = 0.05
                        adjustments.append(("High volatility", vol_boost))
                    elif avg_range_pct < 0.5:  # Low volatility
                        vol_boost = -0.05
                        adjustments.append(("Low volatility", vol_boost))
                    else:
                        vol_boost = 0
                        adjustments.append(("Normal volatility", vol_boost))
                    
                    confidence += vol_boost
            
            # 5. Time of Day Factor (±5%)
            now = datetime.now(self.est)
            hour = now.hour
            
            if 9 <= hour <= 10:  # First hour - high activity
                time_boost = 0.05
                adjustments.append(("Opening hour", time_boost))
            elif 15 <= hour <= 16:  # Last hour - high activity
                time_boost = 0.05
                adjustments.append(("Closing hour", time_boost))
            elif 11 <= hour <= 14:  # Mid-day - normal
                time_boost = 0
                adjustments.append(("Mid-day", time_boost))
            else:
                time_boost = -0.05
                adjustments.append(("Off-hours", time_boost))
            
            confidence += time_boost
            
        except Exception as e:
            logger.error(f"Error calculating dynamic confidence: {e}")
            # Return base confidence on error
            return base_scores.get(pattern_type, 0.65)
        
        # Cap confidence between 0.40 and 0.95
        confidence = max(0.40, min(0.95, confidence))
        
        # Log adjustments for debugging
        if adjustments:
            adj_str = ", ".join([f"{name}: {val:+.2f}" for name, val in adjustments])
            logger.debug(f"{ticker} {pattern_type} confidence adjustments: {adj_str}")
        
        return confidence

    def should_alert_pattern(self, pattern_type: str, signal: Dict) -> bool:
        """Check if pattern should be alerted based on time windows"""
        now = datetime.now(self.est)
        
        if pattern_type == '3-2-2 Reversal':
            # Alert only at 10:01 AM EST
            return now.hour == 10 and now.minute <= 5
        
        elif pattern_type == '2-2 Reversal':
            # Alert between 8:01 AM - 9:29 AM EST
            # Must have pullback confirmed
            return (now.hour == 8 or (now.hour == 9 and now.minute < 30)) and signal.get('pullback_confirmed', False)
        
        elif pattern_type == '1-3-1 Miyagi':
            # Alert at 4:01 AM or 4:01 PM EST
            return (now.hour in [4, 16] and now.minute <= 5)
        
        return False

    def track_pattern_state(self, ticker: str, pattern: Dict):
        """Track patterns that need monitoring (e.g., 2-2 waiting for pullback)"""
        key = f"{ticker}_{pattern['pattern']}"
        self.pattern_states[key] = {
            'pattern': pattern,
            'detected_time': datetime.now(self.est),
            'status': 'waiting_pullback' if pattern['pattern'] == '2-2 Reversal' else 'ready'
        }

    def check_322_reversal(self, bars: List[Dict], ticker: str) -> Optional[Dict]:
        """
        PRD Corrected: 3-2-2 Reversal Pattern (60-minute timeframe)
        1. 8:00 AM → Look for 3-bar (outside bar)
        2. 9:00 AM → 2-bar forms (any direction), mark high/low
        3. 10:00 AM → 2-bar opposite direction (high probability alert)
        """
        if len(bars) < 4:
            return None

        valid_bars = [b for b in bars if self.validate_bar(b)]
        if len(valid_bars) < 4:
            return None

        bars = valid_bars
        pattern_bars = []
        target_hours = {8: None, 9: None, 10: None}

        # Extract bars at 8am, 9am, 10am
        for bar in bars:
            if 't' not in bar:
                continue
            bar_time = datetime.fromtimestamp(bar['t'] / 1000, tz=self.est)
            bar['time'] = bar_time
            bar_hour = bar_time.hour

            if bar_hour in target_hours and target_hours[bar_hour] is None:
                target_hours[bar_hour] = bar

        for hour in [8, 9, 10]:
            if target_hours[hour] is not None:
                pattern_bars.append(target_hours[hour])

        if len(pattern_bars) < 3:
            return None

        bar_8am = pattern_bars[0]
        bar_9am = pattern_bars[1]
        bar_10am = pattern_bars[2]

        # Find previous bar for 8am comparison
        prev_bar = bars[0] if len(bars) > 0 else bar_8am

        # Step 1: 8am must be 3-bar (outside)
        bar1_type = self.detect_bar_type(bar_8am, prev_bar)
        if bar1_type != 3:
            return None

        # Step 2: 9am is a 2-bar (direction doesn't matter)
        bar2_type = self.detect_bar_type(bar_9am, bar_8am)
        if abs(bar2_type) != 2:
            return None

        # Step 3: 10am must be 2-bar in opposite direction
        bar3_type = self.detect_bar_type(bar_10am, bar_9am)
        if abs(bar3_type) != 2:
            return None

        signal = None
        
        # If 9am=2U and 10am=2D → Bearish reversal
        if bar2_type == 2 and bar3_type == -2:
            entry = bar_10am['c']
            stop = bar_9am['h']    # High of 9am bar
            risk = abs(entry - stop)
            target = entry - (risk * 2)  # 2:1 R:R target
            
            signal = {
                'pattern': '3-2-2 Reversal',
                'direction': 'Bearish',
                'ticker': ticker,
                'timeframe': '60min',
                'entry': entry,
                'target': target,
                'stop': stop,
                'risk_reward': 2.0  # Fixed 2:1 R:R
            }
        # If 9am=2D and 10am=2U → Bullish reversal
        elif bar2_type == -2 and bar3_type == 2:
            entry = bar_10am['c']
            stop = bar_9am['l']    # Low of 9am bar
            risk = abs(entry - stop)
            target = entry + (risk * 2)  # 2:1 R:R target
            
            signal = {
                'pattern': '3-2-2 Reversal',
                'direction': 'Bullish',
                'ticker': ticker,
                'timeframe': '60min',
                'entry': entry,
                'target': target,
                'stop': stop,
                'risk_reward': 2.0  # Fixed 2:1 R:R
            }

        return signal

    def check_22_reversal(self, bars: List[Dict], ticker: str) -> Optional[Dict]:
        """
        PRD Corrected: 2-2 Reversal Retrigger (4-hour timeframe)
        1. 4:00 AM → Look for 2-bar (2D or 2U)
        2. 8:00 AM → Opens inside previous bar, triggers opposite direction
        3. Target: High/Low of candle BEFORE 4am bar
        Alert sent after 8am candle closes
        """
        if len(bars) < 3:
            return None

        bar_4am = None
        bar_8am = None
        bar_before_4am = None

        for i, bar in enumerate(bars):
            if 't' not in bar:
                continue
            bar_time = datetime.fromtimestamp(bar['t'] / 1000, tz=self.est)
            bar['time'] = bar_time
            bar_hour = bar_time.hour

            if bar_hour == 0 and bar_before_4am is None:  # Midnight bar (before 4am)
                bar_before_4am = (i, bar)
            elif bar_hour == 4 and bar_4am is None:
                bar_4am = (i, bar)
            elif bar_hour == 8 and bar_8am is None:
                bar_8am = (i, bar)

        if not bar_4am or not bar_8am or not bar_before_4am:
            return None

        idx_before, data_before = bar_before_4am
        idx_4am, data_4am = bar_4am
        idx_8am, data_8am = bar_8am

        # Step 1: 4am must be a 2-bar (2D or 2U)
        bar1_type = self.detect_bar_type(data_4am, data_before)
        if abs(bar1_type) != 2:
            return None

        # Step 2: 8am must open inside 4am bar
        opened_inside = (data_8am['o'] <= data_4am['h'] and data_8am['o'] >= data_4am['l'])
        if not opened_inside:
            return None

        # Step 3: 8am must be opposite direction 2-bar
        bar2_type = self.detect_bar_type(data_8am, data_4am)
        if abs(bar2_type) != 2:
            return None

        signal = None

        # If 4am=2D and 8am=2U → Bullish reversal
        if bar1_type == -2 and bar2_type == 2:
            entry = data_8am['c']
            stop = data_4am['l']
            risk = abs(entry - stop)
            target = entry + (risk * 2)  # 2:1 R:R target
            
            signal = {
                'pattern': '2-2 Reversal',
                'direction': 'Bullish',
                'ticker': ticker,
                'timeframe': '4hour',
                'entry': entry,
                'target': target,
                'stop': stop,
                'risk_reward': 2.0  # Fixed 2:1 R:R
            }
        # If 4am=2U and 8am=2D → Bearish reversal
        elif bar1_type == 2 and bar2_type == -2:
            entry = data_8am['c']
            stop = data_4am['h']
            risk = abs(entry - stop)
            target = entry - (risk * 2)  # 2:1 R:R target
            
            signal = {
                'pattern': '2-2 Reversal',
                'direction': 'Bearish',
                'ticker': ticker,
                'timeframe': '4hour',
                'entry': entry,
                'target': target,
                'stop': stop,
                'risk_reward': 2.0  # Fixed 2:1 R:R
            }

        # Add pullback detection logic
        if signal and len(bars) > 0:
            # Check for pullback wick on the most recent bar
            current_bar = bars[-1]
            pullback_confirmed = False
            
            if self.validate_bar(current_bar):
                if signal['direction'] == 'Bullish':
                    # For bullish, check for lower wick (indicating pullback down)
                    wick_size = current_bar['o'] - current_bar['l']
                    body_size = abs(current_bar['c'] - current_bar['o'])
                    if body_size > 0 and wick_size > body_size * 0.5:  # Wick > 50% of body
                        pullback_confirmed = True
                else:
                    # For bearish, check for upper wick (indicating pullback up)
                    wick_size = current_bar['h'] - current_bar['o']
                    body_size = abs(current_bar['c'] - current_bar['o'])
                    if body_size > 0 and wick_size > body_size * 0.5:
                        pullback_confirmed = True
            
            signal['pullback_confirmed'] = pullback_confirmed

        return signal

    def check_131_miyagi(self, bars: List[Dict], ticker: str) -> Optional[Dict]:
        """
        PRD Corrected: 1-3-1 Miyagi Pattern (12-hour timeframe)
        1. Identify 1-3-1: Inside → Outside → Inside (3 consecutive candles)
        2. Calculate midpoint of 3rd candle (last 1-bar)
        3. 4th candle direction determines trade:
           - If 4th candle is 2U → take PUTS (reversal from overextension)
           - If 4th candle is 2D → take CALLS (reversal from overextension)
        """
        if len(bars) < 4:
            return None

        # Add time to bars
        for bar in bars:
            if 't' in bar:
                bar['time'] = datetime.fromtimestamp(bar['t'] / 1000, tz=self.est)

        # Get last 4 bars
        candle1 = bars[-4]
        candle2 = bars[-3]
        candle3 = bars[-2]
        candle4 = bars[-1]

        # Determine bar types for 1-3-1 pattern
        type1 = self.detect_bar_type(candle1, bars[-5] if len(bars) > 4 else candle1)
        type2 = self.detect_bar_type(candle2, candle1)
        type3 = self.detect_bar_type(candle3, candle2)
        type4 = self.detect_bar_type(candle4, candle3)

        # Step 1: Must have 1-3-1 pattern
        if not (type1 == 1 and type2 == 3 and type3 == 1):
            return None

        # Step 2: Calculate midpoint of 3rd candle (last 1-bar)
        midpoint = (candle3['h'] + candle3['l']) / 2

        signal = None

        # Step 3: 4th candle determines direction
        # If 4th is 2U (breaks above midpoint) → PUTS (reversal down expected)
        if type4 == 2:
            entry = candle4['c']
            stop = candle4['h']
            risk = abs(entry - stop)
            target = entry - (risk * 2)  # 2:1 R:R target
            
            signal = {
                'pattern': '1-3-1 Miyagi',
                'setup': '1-3-1 2U (Fade)',
                'direction': 'Bearish',  # Take PUTS
                'ticker': ticker,
                'timeframe': '12hour',
                'entry': entry,
                'target': target,
                'stop': stop,
                'risk_reward': 2.0  # Fixed 2:1 R:R
            }
        # If 4th is 2D (breaks below midpoint) → CALLS (reversal up expected)
        elif type4 == -2:
            entry = candle4['c']
            stop = candle4['l']
            risk = abs(entry - stop)
            target = entry + (risk * 2)  # 2:1 R:R target
            
            signal = {
                'pattern': '1-3-1 Miyagi',
                'setup': '1-3-1 2D (Fade)',
                'direction': 'Bullish',  # Take CALLS
                'ticker': ticker,
                'timeframe': '12hour',
                'entry': entry,
                'target': target,
                'stop': stop,
                'risk_reward': 2.0  # Fixed 2:1 R:R
            }

        return signal

    async def scan_ticker(self, ticker: str) -> List[Dict]:
        """PRD Enhanced: Scan with continuous pattern detection"""
        signals = []
        now = datetime.now(self.est)

        try:
            # 1-3-1 Miyagi - Always scan on 12H timeframe
            # Pattern can form at any time, not just at 4am/4pm
            df_12h = await self.data_fetcher.get_aggregates(
                ticker, 'hour', 12,
                (now - timedelta(days=5)).strftime('%Y-%m-%d'),
                now.strftime('%Y-%m-%d')
            )
            if not df_12h.empty:
                bars_12h = df_12h.to_dict('records')
                bars_12h = [{'h': b['high'], 'l': b['low'], 'o': b['open'], 'c': b['close'],
                            't': int(b['timestamp'].timestamp() * 1000), 'v': b.get('volume', 0)} for b in bars_12h]
                signal = self.check_131_miyagi(bars_12h, ticker)
                if signal:
                    # Calculate dynamic confidence
                    confidence = await self.calculate_dynamic_confidence(
                        ticker, '1-3-1 Miyagi', signal, bars_12h
                    )
                    signal['confidence_score'] = confidence
                    signals.append(signal)

            # 3-2-2 Reversal - Always scan, pattern must have formed after 10am ET
            # Get data from 7am to current time
            start_time = now.replace(hour=7, minute=0) if now.hour >= 7 else now - timedelta(days=1)
            df_60m = await self.data_fetcher.get_aggregates(
                ticker, 'minute', 60,
                start_time.strftime('%Y-%m-%d'),
                now.strftime('%Y-%m-%d')
            )
            if not df_60m.empty:
                bars_60m = df_60m.to_dict('records')
                bars_60m = [{'h': b['high'], 'l': b['low'], 'o': b['open'], 'c': b['close'],
                             't': int(b['timestamp'].timestamp() * 1000), 'v': b.get('volume', 0)} for b in bars_60m]
                signal = self.check_322_reversal(bars_60m, ticker)
                if signal:
                    # Calculate dynamic confidence
                    confidence = await self.calculate_dynamic_confidence(
                        ticker, '3-2-2 Reversal', signal, bars_60m
                    )
                    signal['confidence_score'] = confidence
                    signals.append(signal)

            # 2-2 Reversal - Always scan on 4H timeframe
            # Pattern can complete at any time after 8am
            df_4h = await self.data_fetcher.get_aggregates(
                ticker, 'hour', 4,
                (now - timedelta(days=2)).strftime('%Y-%m-%d'),
                now.strftime('%Y-%m-%d')
            )
            if not df_4h.empty:
                bars_4h = df_4h.to_dict('records')
                bars_4h = [{'h': b['high'], 'l': b['low'], 'o': b['open'], 'c': b['close'],
                           't': int(b['timestamp'].timestamp() * 1000), 'v': b.get('volume', 0)} for b in bars_4h]
                signal = self.check_22_reversal(bars_4h, ticker)
                if signal:
                    # Calculate dynamic confidence
                    confidence = await self.calculate_dynamic_confidence(
                        ticker, '2-2 Reversal', signal, bars_4h
                    )
                    signal['confidence_score'] = confidence
                    signals.append(signal)

        except Exception as e:
            logger.error(f"Error scanning {ticker}: {e}")

        return signals

    def send_alert(self, signal: Dict):
        """PRD Enhanced: Send Discord alert with confidence score"""
        try:
            webhook = DiscordWebhook(url=self.webhook_url, rate_limit_retry=True)

            color = 0x00FF00 if signal['direction'] == 'Bullish' else 0xFF0000

            embed = DiscordEmbed(
                title=f"🎯 {signal['pattern']} - {signal['ticker']}",
                description=f"**{signal['direction']}** setup detected",
                color=color
            )

            embed.add_embed_field(name="📊 Timeframe", value=signal['timeframe'], inline=True)
            embed.add_embed_field(name="📍 Entry", value=f"${signal['entry']:.2f}", inline=True)
            embed.add_embed_field(name="🎯 Target", value=f"${signal['target']:.2f}", inline=True)

            if 'stop' in signal:
                embed.add_embed_field(name="🛑 Stop", value=f"${signal['stop']:.2f}", inline=True)

            if 'risk_reward' in signal:
                embed.add_embed_field(name="💰 R:R", value="2.00", inline=True)  # Always 2:1

            # PRD Enhancement: Display confidence score
            if 'confidence_score' in signal:
                embed.add_embed_field(
                    name="🎲 Confidence",
                    value=f"{signal['confidence_score']*100:.0f}%",
                    inline=True
                )

            if 'setup' in signal:
                embed.add_embed_field(name="⚙️ Setup", value=signal['setup'], inline=False)

            # Add disclaimer
            embed.add_embed_field(
                name="",
                value="Please always do your own due diligence on top of these trade ideas.",
                inline=False
            )

            embed.set_footer(text=f"STRAT Pattern Scanner • {datetime.now(self.est).strftime('%Y-%m-%d %H:%M:%S EST')}")
            embed.set_timestamp()

            webhook.add_embed(embed)
            response = webhook.execute()

            if response.status_code == 200:
                logger.info(f"Alert sent for {signal['ticker']} - {signal['pattern']}")

        except Exception as e:
            logger.error(f"Failed to send alert: {e}")

    async def scan(self):
        """PRD Enhanced: Scan with best signal selection"""
        logger.info(f"{self.name} scan started")
        
        # STRAT bot scans 24/7 but only on trading days (weekdays, excluding holidays)
        if not MarketHours.is_trading_day():
            logger.debug(f"{self.name} - Not a trading day (weekend/holiday), skipping scan")
            return

        signals_found = []
        
        # Use comprehensive mega/large cap watchlist for STRAT bot
        watchlist = STRAT_COMPLETE_WATCHLIST
        logger.info(f"Scanning {len(watchlist)} mega/large cap stocks across all sectors")

        for ticker in watchlist:
            try:
                signals = await self.scan_ticker(ticker)

                # PRD Enhancement: Post only highest confidence signal per ticker
                if signals:
                    best_signal = max(signals, key=lambda x: x.get('confidence_score', 0))

                    # Track pattern state
                    self.track_pattern_state(ticker, best_signal)

                    # Check if alert time is appropriate
                    if self.should_alert_pattern(best_signal['pattern'], best_signal):
                        # Check if already detected today
                        key = f"{ticker}_{best_signal['pattern']}_{datetime.now(self.est).date()}"
                        if key not in self.detected_today:
                            self.send_alert(best_signal)
                            signals_found.append(best_signal)
                            self.detected_today[key] = True

                            logger.info(f"✅ STRAT signal: {ticker} {best_signal['pattern']} - "
                                      f"Confidence:{best_signal.get('confidence_score', 0):.2f}")
                    else:
                        logger.debug(f"Pattern {best_signal['pattern']} for {ticker} detected but outside alert window")

            except Exception as e:
                logger.error(f"Error scanning {ticker}: {e}")

        if signals_found:
            logger.info(f"Found {len(signals_found)} STRAT patterns")
        else:
            logger.info("No new STRAT patterns detected")

    async def get_next_scan_interval(self):
        """Calculate optimal scan interval based on current time"""
        now = datetime.now(self.est)
        
        # During critical alert windows, scan more frequently
        if (now.hour == 3 and now.minute >= 55) or (now.hour == 4 and now.minute <= 5):  # 1-3-1 window
            return 60  # 1 minute
        elif now.hour == 7 and now.minute >= 55:  # Pre 2-2 window
            return 60
        elif now.hour == 8 or (now.hour == 9 and now.minute < 30):  # 2-2 window
            return 120  # 2 minutes
        elif now.hour == 9 and now.minute >= 55:  # Pre 3-2-2 window
            return 60
        elif now.hour == 10 and now.minute <= 5:  # 3-2-2 window
            return 60
        elif (now.hour == 15 and now.minute >= 55) or (now.hour == 16 and now.minute <= 5):  # PM 1-3-1
            return 60
        else:
            return 300  # Default 5 minutes

    async def start(self):
        """Start the bot"""
        self.is_running = True
        self.running = True  # Sync with is_running
        logger.info(f"{self.name} started with dynamic scan intervals")

        while self.is_running:
            try:
                # Reset daily tracking at midnight
                now = datetime.now(self.est)
                if now.hour == 0 and now.minute == 0:
                    self.detected_today.clear()
                    self.pattern_states.clear()  # Also clear pattern states
                    logger.info("Daily pattern tracking and states reset")

                await self.scan()
                
                # Get dynamic scan interval based on current time
                next_interval = await self.get_next_scan_interval()
                logger.debug(f"Next scan in {next_interval}s")
                await asyncio.sleep(next_interval)

            except Exception as e:
                logger.error(f"{self.name} error: {e}")
                await asyncio.sleep(60)

    async def stop(self):
        """Stop the bot"""
        self.is_running = False
        self.running = False  # Sync with is_running
        logger.info(f"{self.name} stopped")
