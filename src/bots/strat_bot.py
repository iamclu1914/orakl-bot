"""
STRAT Pattern Detection Bot (12-Hour Timeframe)
Battle-tested implementation with proper ET alignment (08:00 & 20:00)
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
from src.utils.strat_12h import STRAT12HourDetector
from src.utils.strat_12h_composer import STRAT12HourComposer
from src.utils.strat_4h import STRAT4HourDetector
from src.utils.strat_60m import STRAT60MinuteDetector
import numpy as np

logger = logging.getLogger(__name__)

ET = pytz.timezone('America/New_York')

class STRATPatternBot:
    """Bot for detecting STRAT trading patterns with database persistence"""

    def __init__(self, data_fetcher: DataFetcher = None, db_session=None):
        self.name = "STRAT Pattern Scanner"
        # Use provided data_fetcher or create new one with API key from config
        self.data_fetcher = data_fetcher if data_fetcher else DataFetcher(Config.POLYGON_API_KEY)
        self.webhook_url = Config.STRAT_WEBHOOK
        self.scan_interval = Config.STRAT_INTERVAL

        # Database integration
        self.db_session = db_session
        self.db_repo = None
        if db_session:
            from src.database.strat_repository import STRATRepository
            self.db_repo = STRATRepository(db_session)
            logger.info(f"{self.name} initialized with database persistence")
        else:
            logger.warning(f"{self.name} initialized WITHOUT database persistence (in-memory only)")

        # Legacy in-memory storage (fallback when no database)
        self.detected_today = {}

        self.is_running = False
        self.running = False  # Add for compatibility with BotManager.get_bot_status()
        self.est = pytz.timezone('America/New_York')
        self.pattern_states = {}  # Track patterns waiting for conditions
        self.watchlist = None  # Will be set by BotManager

        # STRAT detectors (battle-tested) - multiple timeframes
        self.strat_12h_detector = STRAT12HourDetector()  # 1-3-1 Miyagi
        self.strat_12h_composer = STRAT12HourComposer()
        self.strat_4h_detector = STRAT4HourDetector()     # 2-2 Reversal
        self.strat_60m_detector = STRAT60MinuteDetector() # 3-2-2 Reversal

        logger.info(f"{self.name} initialized with multi-timeframe detection:")
        logger.info(f"  • 1-3-1 Miyagi: 12h bars (08:00 & 20:00 ET)")
        logger.info(f"  • 2-2 Reversal: 4h bars (4am & 8am ET)")
        logger.info(f"  • 3-2-2 Reversal: 60m bars (8am, 9am, 10am ET)")

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
        Identify STRAT bar types (legacy method for compatibility)
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
    
    async def fetch_and_compose_12h_bars(self, symbol: str, n_bars: int = 10) -> List[Dict]:
        """
        Fetch 12-hour bars using best practice approach:
        1. Try direct 720-minute aggregates (most efficient)
        2. Fall back to composing from 60-minute bars if needed
        
        Args:
            symbol: Stock symbol
            n_bars: Number of 12-hour bars to get
            
        Returns:
            List of 12-hour bars aligned to 08:00 and 20:00 ET
        """
        try:
            # Need enough days to get n_bars of 12-hour bars (2 per day)
            # Add extra days to ensure we have sufficient data
            days_needed = (n_bars // 2) + 3  # Increased from +2 to +3
            end_date = datetime.now()
            start_date = end_date - timedelta(days=days_needed)
            
            # TRY 1: Direct 720-minute aggregates (12 hours = 720 minutes)
            logger.debug(f"{symbol}: Attempting direct 720-minute aggregates")
            
            bars_720m = await self.data_fetcher.get_aggregates(
                symbol,
                timespan='minute',
                multiplier=720,
                from_date=start_date.strftime('%Y-%m-%d'),
                to_date=end_date.strftime('%Y-%m-%d')
            )
            
            # Check if we got good data with proper alignment
            if bars_720m is not None and len(bars_720m) >= 4:
                if hasattr(bars_720m, 'to_dict'):
                    bars_list = bars_720m.to_dict('records')
                else:
                    bars_list = bars_720m
                
                # Normalize and check alignment
                normalized_720 = []
                for bar in bars_list:
                    # Handle timestamp - convert pandas Timestamp to int milliseconds
                    timestamp = bar.get('t', bar.get('timestamp', 0))
                    if hasattr(timestamp, 'timestamp'):
                        timestamp_ms = int(timestamp.timestamp() * 1000)
                    else:
                        timestamp_ms = int(timestamp) if timestamp else 0
                    
                    normalized_720.append({
                        'o': bar.get('o', bar.get('open', 0)),
                        'h': bar.get('h', bar.get('high', 0)),
                        'l': bar.get('l', bar.get('low', 0)),
                        'c': bar.get('c', bar.get('close', 0)),
                        'v': bar.get('v', bar.get('volume', 0)),
                        't': timestamp_ms
                    })
                
                # Verify ET alignment (bars should end at 08:00 or 20:00 ET)
                is_aligned = self._check_12h_alignment(normalized_720)
                
                if is_aligned:
                    logger.info(f"{symbol}: Using direct 720m bars ({len(normalized_720)} bars)")
                    return normalized_720
                else:
                    logger.warning(f"{symbol}: 720m bars not ET-aligned, falling back to composition")
            
            # FALLBACK: Compose from 60-minute bars
            logger.debug(f"{symbol}: Composing from 60-minute bars")
            
            bars_60m = await self.data_fetcher.get_aggregates(
                symbol,
                timespan='minute',
                multiplier=60,
                from_date=start_date.strftime('%Y-%m-%d'),
                to_date=end_date.strftime('%Y-%m-%d')
            )
            
            if bars_60m is None or len(bars_60m) == 0:
                return []
            
            if hasattr(bars_60m, 'to_dict'):
                bars_list = bars_60m.to_dict('records')
            else:
                bars_list = bars_60m
            
            normalized_60m = []
            for bar in bars_list:
                # Handle timestamp - convert pandas Timestamp to int milliseconds
                timestamp = bar.get('t', bar.get('timestamp', 0))
                if hasattr(timestamp, 'timestamp'):
                    timestamp_ms = int(timestamp.timestamp() * 1000)
                else:
                    timestamp_ms = int(timestamp) if timestamp else 0
                
                normalized_60m.append({
                    'o': bar.get('o', bar.get('open', 0)),
                    'h': bar.get('h', bar.get('high', 0)),
                    'l': bar.get('l', bar.get('low', 0)),
                    'c': bar.get('c', bar.get('close', 0)),
                    'v': bar.get('v', bar.get('volume', 0)),
                    't': timestamp_ms
                })
            
            # Compose into 12-hour bars with ET alignment
            composed = self.strat_12h_composer.compose_12h_bars(normalized_60m)
            logger.info(f"{symbol}: Composed {len(composed)} 12h bars from {len(normalized_60m)} 60m bars")
            return composed
            
        except Exception as e:
            logger.error(f"Error fetching/composing 12h bars for {symbol}: {e}")
            return []
    
    def _check_12h_alignment(self, bars: List[Dict]) -> bool:
        """
        Check if bars are properly aligned to 08:00 and 20:00 ET
        
        Args:
            bars: List of bar dicts with normalized 't' timestamps
            
        Returns:
            True if aligned, False otherwise
        """
        if not bars or len(bars) < 2:
            return False
        
        try:
            aligned_count = 0
            
            # Check last few bars for ET alignment
            for bar in bars[-min(3, len(bars)):]:
                timestamp_ms = bar.get('t', 0)
                if timestamp_ms == 0:
                    continue
                
                # Already normalized to int milliseconds
                bar_time = datetime.fromtimestamp(timestamp_ms / 1000, tz=pytz.UTC).astimezone(ET)
                
                # Check if hour is 8 or 20 and minute is 0
                # Allow some tolerance for minute (within 5 minutes)
                if bar_time.hour in [8, 20] and bar_time.minute <= 5:
                    aligned_count += 1
            
            # If at least 50% of checked bars are aligned, consider it aligned
            return aligned_count >= len(bars[-min(3, len(bars)):]) * 0.5
            
        except Exception as e:
            logger.error(f"Error checking alignment: {e}")
            return False
    
    async def scan_symbol_12h(self, symbol: str) -> List[Dict]:
        """
        Scan a symbol for 12-hour STRAT patterns
        
        Returns:
            List of pattern signals (1-3-1, 3-2-2, 2-2, etc.)
        """
        signals = []
        
        try:
            bars_12h = await self.fetch_and_compose_12h_bars(symbol, n_bars=10)
            
            if len(bars_12h) < 4:
                return signals
            
            typed_bars = self.strat_12h_detector.attach_types(bars_12h)
            
            if len(typed_bars) < 3:
                return signals
            
            # Detect all patterns
            miyagi_131 = self.strat_12h_detector.detect_131_miyagi(typed_bars)
            reversal_322 = self.strat_12h_detector.detect_322_reversal(typed_bars)
            reversal_22 = self.strat_12h_detector.detect_22_reversal(typed_bars)
            
            # Process 1-3-1 Miyagi
            for sig in miyagi_131:
                if sig['kind'] == '131-complete':
                    signals.append({
                        'pattern': '1-3-1 Miyagi',
                        'symbol': symbol,
                        'completed_at': sig['completed_at'],
                        'entry': sig['entry'],
                        'type': 'Pending',
                        'confidence_score': 0.75,
                        'pattern_bars': sig['pattern_bars']
                    })
                elif sig['kind'] in ['131-4th-2U-PUTS', '131-4th-2D-CALLS']:
                    signals.append({
                        'pattern': f"1-3-1 Miyagi ({sig.get('direction', 'N/A')} bias)",
                        'symbol': symbol,
                        'completed_at': sig['at'],
                        'entry': sig['entry'],
                        'type': sig.get('direction', 'N/A'),
                        'confidence_score': 0.80,
                        'setup_complete': True
                    })
            
            # Process 3-2-2 Reversals
            for ts in reversal_322[-1:]:  # Only most recent
                bar_idx = next((i for i, b in enumerate(typed_bars) if b.t == ts), None)
                if bar_idx and bar_idx >= 2:
                    bar3 = typed_bars[bar_idx]
                    signals.append({
                        'pattern': '3-2-2 Reversal',
                        'symbol': symbol,
                        'completed_at': ts,
                        'entry': bar3.c,
                        'type': 'Reversal',
                        'confidence_score': 0.70
                    })
            
            # Process 2-2 Reversals
            for ts in reversal_22[-1:]:  # Only most recent
                bar_idx = next((i for i, b in enumerate(typed_bars) if b.t == ts), None)
                if bar_idx and bar_idx >= 1:
                    bar2 = typed_bars[bar_idx]
                    signals.append({
                        'pattern': '2-2 Reversal',
                        'symbol': symbol,
                        'completed_at': ts,
                        'entry': bar2.c,
                        'type': 'Reversal',
                        'confidence_score': 0.65
                    })
            
            return signals
            
        except Exception as e:
            logger.error(f"Error in 12h scan for {symbol}: {e}")
            return []

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
        """
        Check if pattern should be alerted based on pattern-specific time windows

        Pattern-specific alert times (ET):
        - 1-3-1 Miyagi: ONLY after 20:00 (8pm) when evening bar closes
        - 2-2 Reversal: After 08:00 (when 8am bar completes)
        - 3-2-2 Reversal: After 10:00 (when 10am bar completes)
        """
        now = datetime.now(self.est)
        current_hour = now.hour
        current_minute = now.minute

        # 30-minute alert window after bar close
        alert_window = 30

        if 'Miyagi' in pattern_type or '1-3-1' in pattern_type:
            # ONLY alert after 8:00 PM (20:00 ET) evening bar close
            # This gives us 36 hours of data (3 bars × 12 hours)
            return ((current_hour == 20 and current_minute < alert_window) or
                    (current_hour == 21 and current_minute < 15))  # Extended window

        elif '2-2' in pattern_type:
            # Alert after 8:00 AM (when 8am bar completes the 4am→8am sequence)
            return (current_hour == 8 and current_minute < alert_window) or (current_hour == 9 and current_minute < 15)

        elif '3-2-2' in pattern_type:
            # Alert after 10:00 AM (when 10am bar completes the 8am→9am→10am sequence)
            return (current_hour == 10 and current_minute < alert_window) or (current_hour == 11 and current_minute < 15)

        # Default: deny alert outside windows
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

        # Use bar alignment utility to find 8am, 9am, 10am bars
        from src.utils.bar_alignment import get_bars_for_hours, get_previous_bar

        # Get pattern bars (60-minute timeframe)
        pattern_bars = get_bars_for_hours(bars, [8, 9, 10], timeframe_minutes=60, tz=self.est)

        bar_8am = pattern_bars.get(8)
        bar_9am = pattern_bars.get(9)
        bar_10am = pattern_bars.get(10)

        if not bar_8am or not bar_9am or not bar_10am:
            return None

        # Find bar before 8am for comparison (should be 7am bar)
        prev_bar = get_previous_bar(bars, bar_8am)

        if not prev_bar:
            # Fallback to first bar if previous not found
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

        # Use bar alignment utility to find 4am and 8am bars
        from src.utils.bar_alignment import get_bars_for_hours, get_previous_bar

        # Get 4am and 8am bars (4-hour timeframe)
        pattern_bars = get_bars_for_hours(bars, [4, 8], timeframe_minutes=240, tz=self.est)

        data_4am = pattern_bars.get(4)
        data_8am = pattern_bars.get(8)

        if not data_4am or not data_8am:
            return None

        # Get bar before 4am using sequential indexing (more robust)
        data_before = get_previous_bar(bars, data_4am)

        if not data_before:
            return None

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
        """
        Scan ticker for all STRAT patterns across multiple timeframes
        
        Patterns:
        - 1-3-1 Miyagi: 12h bars (08:00 & 20:00 ET)
        - 2-2 Reversal: 4h bars (4am & 8am ET)
        - 3-2-2 Reversal: 60m bars (8am, 9am, 10am ET)
        """
        signals = []
        now = datetime.now(self.est)

        try:
            # Fetch 60-minute bars (we'll compose into other timeframes)
            end_date = datetime.now()
            start_date = end_date - timedelta(days=5)
            
            bars_60m = await self.data_fetcher.get_aggregates(
                ticker,
                timespan='minute',
                multiplier=60,
                from_date=start_date.strftime('%Y-%m-%d'),
                to_date=end_date.strftime('%Y-%m-%d')
            )
            
            if bars_60m is None or len(bars_60m) == 0:
                return signals
            
            # Normalize bars
            if hasattr(bars_60m, 'to_dict'):
                bars_list = bars_60m.to_dict('records')
            else:
                bars_list = bars_60m
            
            normalized_60m = []
            for bar in bars_list:
                # Handle timestamp - convert pandas Timestamp to int milliseconds
                timestamp = bar.get('t', bar.get('timestamp', 0))
                if hasattr(timestamp, 'timestamp'):
                    timestamp_ms = int(timestamp.timestamp() * 1000)
                else:
                    timestamp_ms = int(timestamp) if timestamp else 0
                
                normalized_60m.append({
                    'o': bar.get('o', bar.get('open', 0)),
                    'h': bar.get('h', bar.get('high', 0)),
                    'l': bar.get('l', bar.get('low', 0)),
                    'c': bar.get('c', bar.get('close', 0)),
                    'v': bar.get('v', bar.get('volume', 0)),
                    't': timestamp_ms
                })
            
            # ===== 1. SCAN 3-2-2 REVERSAL (60m: 8am-9am-10am) =====
            patterns_322 = self.strat_60m_detector.detect_322_reversal_8am_10am(normalized_60m)
            for sig in patterns_322:
                signal = {
                    'pattern': '3-2-2 Reversal',
                    'symbol': ticker,
                    'completed_at': sig['completed_at'],
                    'entry': sig['entry'],
                    'type': sig['bias'],
                    'confidence_score': 0.75,
                    'bars': f"{sig['pattern_sequence']}",
                    'timeframe': '60m'
                }
                signals.append(signal)
            
            # ===== 2. SCAN 2-2 REVERSAL (4h: 4am-8am) =====
            # Try direct 240-minute aggregates first, fall back to composition
            bars_240m = await self.data_fetcher.get_aggregates(
                ticker,
                timespan='minute',
                multiplier=240,  # 4 hours = 240 minutes
                from_date=start_date.strftime('%Y-%m-%d'),
                to_date=end_date.strftime('%Y-%m-%d')
            )
            
            # Check if direct 240m is good, otherwise compose from 60m
            if bars_240m is not None and len(bars_240m) >= 4:
                if hasattr(bars_240m, 'to_dict'):
                    bars_4h_list = bars_240m.to_dict('records')
                else:
                    bars_4h_list = bars_240m
                
                normalized_240 = []
                for bar in bars_4h_list:
                    # Handle timestamp - convert pandas Timestamp to int milliseconds
                    timestamp = bar.get('t', bar.get('timestamp', 0))
                    if hasattr(timestamp, 'timestamp'):
                        timestamp_ms = int(timestamp.timestamp() * 1000)
                    else:
                        timestamp_ms = int(timestamp) if timestamp else 0
                    
                    normalized_240.append({
                        'o': bar.get('o', bar.get('open', 0)),
                        'h': bar.get('h', bar.get('high', 0)),
                        'l': bar.get('l', bar.get('low', 0)),
                        'c': bar.get('c', bar.get('close', 0)),
                        'v': bar.get('v', bar.get('volume', 0)),
                        't': timestamp_ms
                    })
                bars_4h = normalized_240
                logger.debug(f"{ticker}: Using direct 240m bars for 4h")
            else:
                # Compose from 60m
                bars_4h = self.strat_4h_detector.compose_4h_bars(normalized_60m)
                logger.debug(f"{ticker}: Composed 4h bars from 60m")
            
            patterns_22 = self.strat_4h_detector.detect_22_reversal_4am_8am(bars_4h)
            for sig in patterns_22:
                signal = {
                    'pattern': '2-2 Reversal',
                    'symbol': ticker,
                    'completed_at': sig['completed_at'],
                    'entry': sig['entry'],
                    'type': sig['direction'],
                    'confidence_score': 0.70,
                    'bars': f"{sig['bar_4am']['type']}→{sig['bar_8am']['type']}",
                    'timeframe': '4h'
                }
                signals.append(signal)
            
            # ===== 3. SCAN 1-3-1 MIYAGI (12h: 08:00 & 20:00) =====
            bars_12h = self.strat_12h_composer.compose_12h_bars(normalized_60m)
            if len(bars_12h) >= 4:
                typed_bars_12h = self.strat_12h_detector.attach_types(bars_12h)
                patterns_131 = self.strat_12h_detector.detect_131_miyagi(typed_bars_12h)
                
                for sig in patterns_131:
                    if sig['kind'] == '131-complete':
                        # Check if bar 3 closes at 20:00 today (going into next trading day)
                        timestamp_ms = sig['completed_at']
                        pattern_time = datetime.fromtimestamp(timestamp_ms / 1000, tz=pytz.UTC).astimezone(ET)
                        
                        # Only alert patterns where bar 3 closes at 20:00 TODAY
                        # Pattern: yesterday 20:00 (1) → today 08:00 (3) → today 20:00 (1)
                        if pattern_time.date() != now.date() or pattern_time.hour != 20:
                            logger.debug(f"{ticker}: Skipping 1-3-1 (not closing at 20:00 today)")
                            continue
                        
                        signal = {
                            'pattern': '1-3-1 Miyagi',
                            'symbol': ticker,
                            'completed_at': sig['completed_at'],
                            'entry': sig['entry'],
                            'type': 'Pending 4th bar',
                            'confidence_score': 0.75,
                            'pattern_bars': sig['pattern_bars'],
                            'timeframe': '12h'
                        }
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
            # Use 240-minute aggregation (4 hours) per MVP specification
            df_4h = await self.data_fetcher.get_aggregates(
                ticker, 'minute', 240,
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
        """Send Discord alert for STRAT pattern with trigger and price targets"""
        try:
            # Convert timestamp
            timestamp = signal.get('completed_at', 0)
            if hasattr(timestamp, 'timestamp'):
                completed_time = datetime.fromtimestamp(timestamp.timestamp(), tz=pytz.UTC).astimezone(ET)
            else:
                completed_time = datetime.fromtimestamp(timestamp / 1000, tz=pytz.UTC).astimezone(ET)

            webhook = DiscordWebhook(url=self.webhook_url, rate_limit_retry=True)

            # Color based on pattern and bias
            pattern_type = signal.get('pattern', '')
            bias = signal.get('type', signal.get('bias', ''))
            symbol = signal.get('symbol', '')
            
            if '1-3-1' in pattern_type:
                color = 0xFFD700  # Gold
                emoji = "🎯"
            elif '3-2-2' in pattern_type:
                color = 0xFF6B6B  # Red/salmon
                emoji = "🔄"
            elif '2-2' in pattern_type:
                color = 0x4ECDC4  # Teal
                emoji = "↩️"
            else:
                color = 0x95E1D3
                emoji = "📊"
            
            # Adjust color based on bias
            if 'Bullish' in str(bias) or 'CALLS' in str(bias) or '2U' in str(bias):
                color = 0x00FF00  # Green
            elif 'Bearish' in str(bias) or 'PUTS' in str(bias) or '2D' in str(bias):
                color = 0xFF0000  # Red

            title = f"{emoji} 1-3-1 Pattern Detected for {symbol}"
            
            embed = DiscordEmbed(title=title, color=color)
            
            # Calculate 50% trigger and price targets
            entry = signal.get('entry', 0)  # Already calculated as (H + L) / 2
            
            # For 1-3-1, get the 3rd bar (inside bar) details
            if 'pattern_bars' in signal and isinstance(signal['pattern_bars'], dict):
                bar3 = signal['pattern_bars'].get('bar3', {})
                high_bar3 = bar3.get('h', entry)
                low_bar3 = bar3.get('l', entry)
                
                # 50% Trigger = (High + Low) / 2 of the 3rd bar
                trigger_50 = (high_bar3 + low_bar3) / 2.0
            else:
                trigger_50 = entry
            
            # Price targets based on the inside bar's range
            # If open above trigger → PT is the low of bar 3
            # If open below trigger → PT is the high of bar 3
            pt_above = low_bar3 if 'pattern_bars' in signal else trigger_50 * 0.99
            pt_below = high_bar3 if 'pattern_bars' in signal else trigger_50 * 1.01
            
            # Simple description
            description = f"Completed: {completed_time.strftime('%m/%d %H:%M ET')}"
            embed.description = description
            
            # Add 50% Trigger
            embed.add_embed_field(
                name="🎯 50% Trigger",
                value=f"${trigger_50:.2f}",
                inline=False
            )
            
            # Add price targets based on open direction
            embed.add_embed_field(
                name=f"If we open above {trigger_50:.2f}",
                value=f"First PT is **{pt_above:.2f}**",
                inline=False
            )
            
            embed.add_embed_field(
                name=f"If we open below {trigger_50:.2f}",
                value=f"First PT is **{pt_below:.2f}**",
                inline=False
            )

            # Auto-append disclaimer
            self._add_disclaimer(embed)

            embed.set_footer(text="STRAT Scanner • Not Financial Advice")
            embed.set_timestamp()

            webhook.add_embed(embed)
            response = webhook.execute()

            if response.status_code == 200:
                logger.info(f"✅ Alert sent: {symbol} {pattern_type}")
            else:
                logger.warning(f"Discord post failed: {response.status_code}")

        except Exception as e:
            logger.error(f"Failed to send alert: {e}")

    def _add_disclaimer(self, embed: DiscordEmbed, disclaimer: str = "Please always do your own due diligence on top of these trade ideas."):
        """Add disclaimer field to embed - single source of truth"""
        embed.add_embed_field(name="", value=disclaimer, inline=False)

    async def scan(self):
        """PRD Enhanced: Scan with best signal selection - 24/7 monitoring"""
        logger.info(f"{self.name} scan started")

        # STRAT patterns work on any timeframe, so scan 24/7 including weekends
        # This allows detection of patterns forming outside regular market hours
        # Note: Actual trading signals should still be validated during market hours

        signals_found = []
        
        # Use watchlist from BotManager or fallback to complete list
        watchlist = self.watchlist if self.watchlist else STRAT_COMPLETE_WATCHLIST
        logger.info(f"Scanning {len(watchlist)} stocks from configured watchlist")

        for ticker in watchlist:
            try:
                signals = await self.scan_ticker(ticker)

                # FIX: Process ALL patterns that meet criteria, not just highest confidence
                # Multiple patterns can alert in their respective time windows
                if signals:
                    for signal in signals:
                        # Track pattern state
                        self.track_pattern_state(ticker, signal)

                        # Check confidence threshold (minimum 50%)
                        confidence = signal.get('confidence_score', 0)
                        if confidence < 0.50:
                            logger.debug(f"Pattern {signal['pattern']} for {ticker} below 50% confidence ({confidence:.1%}), skipping alert")
                            continue

                        # Check if alert time is appropriate for THIS pattern
                        if self.should_alert_pattern(signal['pattern'], signal):
                            # Check for duplicate alert (database-backed or in-memory fallback)
                            trading_date = datetime.now(self.est).date()
                            is_duplicate = self._check_duplicate_alert(ticker, signal['pattern'], trading_date)

                            if not is_duplicate:
                                # Save pattern and send alert
                                pattern_saved = self._save_pattern(ticker, signal)
                                self.send_alert(signal)
                                signals_found.append(signal)

                                # Mark as detected (in-memory cache)
                                key = f"{ticker}_{signal['pattern']}_{trading_date}"
                                self.detected_today[key] = True

                                logger.info(f"✅ STRAT signal: {ticker} {signal['pattern']} - "
                                          f"Confidence:{signal.get('confidence_score', 0):.2f}")
                            else:
                                logger.debug(f"Duplicate alert skipped: {ticker} {signal['pattern']} already alerted today")
                        else:
                            logger.debug(f"Pattern {signal['pattern']} for {ticker} detected but outside alert window")

            except Exception as e:
                logger.error(f"Error scanning {ticker}: {e}")

        if signals_found:
            logger.info(f"Found {len(signals_found)} STRAT patterns")
        else:
            logger.info("No new STRAT patterns detected")

    def _check_duplicate_alert(self, symbol: str, pattern_type: str, trading_date) -> bool:
        """
        Check for duplicate alert using database or in-memory fallback

        Args:
            symbol: Stock symbol
            pattern_type: Pattern name (e.g., '3-2-2 Reversal')
            trading_date: Trading date (date object)

        Returns:
            True if duplicate exists, False otherwise
        """
        # Try database first
        if self.db_repo:
            try:
                # Determine timeframe from pattern type
                timeframe = self._get_timeframe_for_pattern(pattern_type)
                return self.db_repo.check_duplicate_alert(symbol, pattern_type, timeframe, trading_date)
            except Exception as e:
                logger.error(f"Database duplicate check failed, falling back to in-memory: {e}")

        # Fallback to in-memory check
        key = f"{symbol}_{pattern_type}_{trading_date}"
        return key in self.detected_today

    def _save_pattern(self, symbol: str, signal: Dict) -> bool:
        """
        Save detected pattern to database

        Args:
            symbol: Stock symbol
            signal: Pattern signal dict

        Returns:
            True if saved successfully, False otherwise
        """
        if not self.db_repo:
            return False

        try:
            # Determine timeframe
            pattern_type = signal['pattern']
            timeframe = self._get_timeframe_for_pattern(pattern_type)

            # Prepare pattern data
            pattern_data = {
                'completion_bar_start_utc': datetime.utcnow(),
                'confidence': signal.get('confidence_score', 0.0),
                'direction': signal.get('type', 'UNKNOWN'),
                'entry': signal.get('entry', 0.0),
                'stop': signal.get('stop', 0.0),
                'target': signal.get('target', 0.0),
                'meta': {
                    'pattern': pattern_type,
                    'detected_at': datetime.now(self.est).isoformat(),
                    'bars': signal.get('bars', [])
                }
            }

            # Save pattern
            pattern = self.db_repo.save_pattern(symbol, pattern_type, timeframe, pattern_data)

            # Save alert record
            trading_date = datetime.now(self.est).date()
            alert_payload = {
                'symbol': symbol,
                'pattern': pattern_type,
                'confidence': signal.get('confidence_score', 0.0),
                'type': signal.get('type'),
                'entry': signal.get('entry'),
                'stop': signal.get('stop'),
                'target': signal.get('target')
            }

            self.db_repo.save_alert(
                pattern_id=pattern.id,
                symbol=symbol,
                pattern_type=pattern_type,
                timeframe=timeframe,
                trading_date=trading_date,
                payload=alert_payload
            )

            # Commit changes
            self.db_session.commit()

            logger.info(f"Pattern saved to database: {symbol} {pattern_type}")
            return True

        except Exception as e:
            logger.error(f"Failed to save pattern to database: {e}")
            if self.db_session:
                self.db_session.rollback()
            return False

    def _get_timeframe_for_pattern(self, pattern_type: str) -> str:
        """
        Get timeframe string for pattern type

        Args:
            pattern_type: Pattern name

        Returns:
            Timeframe string ('60m', '4h', or '12h')
        """
        if '3-2-2' in pattern_type:
            return '60m'
        elif '2-2' in pattern_type:
            return '4h'
        elif '1-3-1' in pattern_type or 'Miyagi' in pattern_type:
            return '12h'
        else:
            logger.warning(f"Unknown pattern type: {pattern_type}, defaulting to 60m")
            return '60m'

    async def get_next_scan_interval(self):
        """Calculate optimal scan interval based on current time"""
        now = datetime.now(self.est)

        # Scan more frequently during ALL alert windows (1 minute intervals)
        # 1-3-1 Miyagi: 8:00 AM and 8:00 PM
        # 2-2 Reversal: 4:00 AM and 8:00 AM
        # 3-2-2 Reversal: 10:01 AM
        alert_hours = [4, 8, 10, 20]
        if now.hour in alert_hours and now.minute <= 15:
            return 60  # 1 minute during alert windows
        elif now.hour == 19 and now.minute >= 55:  # Pre-alert window
            return 120  # 2 minutes before alert time
        else:
            return 300  # Default 5 minutes throughout the day

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

