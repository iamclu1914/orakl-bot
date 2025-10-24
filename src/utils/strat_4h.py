"""
4-Hour STRAT Pattern Detection for 2-2 Reversal
Scans at 4 AM and 8 AM ET boundaries
"""
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import pytz
from collections import defaultdict

logger = logging.getLogger(__name__)

ET = pytz.timezone('America/New_York')

class STRAT4HourDetector:
    """
    4-Hour STRAT Pattern Detector for 2-2 Reversal
    
    Specific logic:
    1. 4:00 AM → Look for 2-bar (2D or 2U)
    2. 8:00 AM → Check if opposite direction AND opens inside previous bar
       - If 4am was 2D → 8am should be 2U
       - If 4am was 2U → 8am should be 2D
    """
    
    @staticmethod
    def compose_4h_bars(hourly_bars: List[Dict]) -> List[Dict]:
        """
        Compose 4-hour bars from 60-minute bars
        Aligned to 00:00, 04:00, 08:00, 12:00, 16:00, 20:00 ET
        
        Args:
            hourly_bars: List of 60-minute bar dicts
            
        Returns:
            List of 4-hour bars aligned to ET boundaries
        """
        if not hourly_bars:
            return []
        
        # Group bars into 4-hour buckets
        buckets = defaultdict(lambda: {
            'o': None,
            'h': float('-inf'),
            'l': float('inf'),
            'c': None,
            'v': 0,
            't': None
        })
        
        for bar in hourly_bars:
            timestamp_ms = bar.get('t', 0)
            if timestamp_ms == 0:
                continue
            
            # Handle pandas Timestamp or int
            if hasattr(timestamp_ms, 'timestamp'):
                bar_time_utc = datetime.fromtimestamp(timestamp_ms.timestamp(), tz=pytz.UTC)
            else:
                bar_time_utc = datetime.fromtimestamp(timestamp_ms / 1000, tz=pytz.UTC)
            
            bar_time_et = bar_time_utc.astimezone(ET)
            
            # Determine 4-hour bucket (00:00, 04:00, 08:00, 12:00, 16:00, 20:00)
            hour = bar_time_et.hour
            bucket_hour = (hour // 4) * 4
            
            # Create bucket end time
            bucket_end = bar_time_et.replace(hour=bucket_hour, minute=0, second=0, microsecond=0)
            if hour >= bucket_hour:
                bucket_end = bucket_end + timedelta(hours=4)
            
            bucket_key = int(bucket_end.timestamp() * 1000)
            
            # Update bucket
            bucket = buckets[bucket_key]
            
            if bucket['o'] is None:
                bucket['o'] = bar.get('o', 0)
            
            bucket['h'] = max(bucket['h'], bar.get('h', 0))
            bucket['l'] = min(bucket['l'], bar.get('l', 0))
            bucket['c'] = bar.get('c', 0)
            bucket['v'] += bar.get('v', 0)
            bucket['t'] = bucket_key
        
        # Convert to sorted list
        composed = []
        for ts in sorted(buckets.keys()):
            bucket = buckets[ts]
            if bucket['o'] is not None:
                composed.append({
                    'o': bucket['o'],
                    'h': bucket['h'],
                    'l': bucket['l'],
                    'c': bucket['c'],
                    'v': bucket['v'],
                    't': bucket['t']
                })
        
        return composed
    
    @staticmethod
    def classify_bar(curr: Dict, prev: Dict) -> str:
        """
        Classify STRAT bar type - EXACT TradingView/Strat rules
        
        Returns: "1", "2U", "2D", "3", or "0" (invalid)
        """
        curr_h, curr_l = curr.get('h', 0), curr.get('l', 0)
        prev_h, prev_l = prev.get('h', 0), prev.get('l', 0)
        
        if curr_h == 0 or curr_l == 0 or prev_h == 0 or prev_l == 0:
            return "0"
        
        # Outside bar - broke both sides
        if curr_h > prev_h and curr_l < prev_l:
            return "3"
        # Directional up - broke high but not low
        elif curr_h > prev_h and curr_l >= prev_l:
            return "2U"
        # Directional down - broke low but not high
        elif curr_l < prev_l and curr_h <= prev_h:
            return "2D"
        # Inside bar - didn't break either side
        else:
            return "1"
    
    @staticmethod
    def detect_22_reversal_4am_8am(bars_4h: List[Dict]) -> List[Dict]:
        """
        Detect 2-2 Reversal at 4 AM → 8 AM ET
        
        Requirements:
        1. 4:00 AM bar is a 2-bar (2D or 2U)
        2. 8:00 AM bar is opposite direction (2D→2U or 2U→2D)
        3. 8:00 AM bar opens inside the 4:00 AM bar
        
        Args:
            bars_4h: List of 4-hour bars
            
        Returns:
            List of signal dicts with pattern details
        """
        signals = []
        
        for i in range(1, len(bars_4h)):
            bar_4am = bars_4h[i-1]
            bar_8am = bars_4h[i]
            
            # Convert timestamps to ET to check if they're 4 AM and 8 AM
            time_4am = datetime.fromtimestamp(bar_4am['t'] / 1000, tz=pytz.UTC).astimezone(ET)
            time_8am = datetime.fromtimestamp(bar_8am['t'] / 1000, tz=pytz.UTC).astimezone(ET)
            
            # Check if this is the 4 AM → 8 AM pair
            if time_4am.hour != 4 or time_8am.hour != 8:
                continue
            
            # Classify both bars
            if i == 0:
                continue  # Need previous bar to classify
            
            prev_bar = bars_4h[i-2] if i >= 2 else None
            if not prev_bar:
                continue
            
            type_4am = STRAT4HourDetector.classify_bar(bar_4am, prev_bar)
            type_8am = STRAT4HourDetector.classify_bar(bar_8am, bar_4am)
            
            # Check if 4 AM is a 2-bar (directional)
            if type_4am not in ['2U', '2D']:
                continue
            
            # Check if 8 AM is opposite direction
            is_reversal = (
                (type_4am == '2D' and type_8am == '2U') or
                (type_4am == '2U' and type_8am == '2D')
            )
            
            if not is_reversal:
                continue
            
            # Check if 8 AM opens inside the 4 AM bar
            open_8am = bar_8am.get('o', 0)
            high_4am = bar_4am.get('h', 0)
            low_4am = bar_4am.get('l', 0)
            
            opens_inside = low_4am <= open_8am <= high_4am
            
            if not opens_inside:
                logger.debug(f"8am bar opens outside 4am range: open=${open_8am:.2f}, 4am range=${low_4am:.2f}-${high_4am:.2f}")
                continue
            
            # Valid 2-2 Reversal!
            signals.append({
                'kind': '22-reversal-4am-8am',
                'completed_at': bar_8am['t'],
                'bar_4am': {
                    'type': type_4am,
                    'h': bar_4am['h'],
                    'l': bar_4am['l'],
                    'c': bar_4am['c'],
                    'time': time_4am
                },
                'bar_8am': {
                    'type': type_8am,
                    'o': bar_8am['o'],
                    'h': bar_8am['h'],
                    'l': bar_8am['l'],
                    'c': bar_8am['c'],
                    'time': time_8am
                },
                'entry': bar_8am['c'],
                'direction': type_8am,
                'opens_inside': opens_inside
            })
            
            logger.info(f"✅ 2-2 Reversal detected: 4am {type_4am} → 8am {type_8am}, opens inside: {opens_inside}")
        
        return signals

