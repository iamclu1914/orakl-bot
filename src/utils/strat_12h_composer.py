"""
12-Hour STRAT Bar Composer
Composes properly ET-aligned 12-hour bars from 60-minute or smaller bars
Following battle-tested Polygon.io implementation
"""
import logging
from datetime import datetime, timedelta
from typing import Dict, List
import pytz
from collections import defaultdict

logger = logging.getLogger(__name__)

ET = pytz.timezone('America/New_York')

class STRAT12HourComposer:
    """
    Compose 12-hour bars aligned to ET windows:
    - Morning session: 08:00 - 19:59 ET
    - Evening session: 20:00 - 07:59 ET (next day)
    """
    
    @staticmethod
    def get_12h_bucket_end(bar_time_et: datetime) -> datetime:
        """
        Get the 12-hour bucket end time for a given bar time
        
        Args:
            bar_time_et: Bar timestamp in ET timezone
            
        Returns:
            Bucket end time (08:00 or 20:00 ET)
        """
        hour = bar_time_et.hour
        
        # Create bucket end at 08:00 or 20:00
        bucket_end = bar_time_et.replace(minute=0, second=0, microsecond=0)
        
        if hour < 8:
            # Before 8 AM - belongs to evening session ending at 08:00
            bucket_end = bucket_end.replace(hour=8)
        elif hour < 20:
            # 8 AM - 7:59 PM - belongs to morning session ending at 20:00
            bucket_end = bucket_end.replace(hour=20)
        else:
            # 8 PM or later - belongs to evening session ending at 08:00 next day
            bucket_end = bucket_end.replace(hour=8) + timedelta(days=1)
        
        return bucket_end
    
    @staticmethod
    def compose_12h_bars(hourly_bars: List[Dict]) -> List[Dict]:
        """
        Compose 12-hour bars from 60-minute bars
        
        Args:
            hourly_bars: List of 60-minute bar dicts with keys: o, h, l, c, v, t (timestamp in ms)
            
        Returns:
            List of 12-hour bar dicts aligned to ET 08:00 and 20:00
        """
        if not hourly_bars:
            return []
        
        # Group bars into 12-hour buckets
        buckets = defaultdict(lambda: {
            'o': None,
            'h': float('-inf'),
            'l': float('inf'),
            'c': None,
            'v': 0,
            't': None,
            'bars_count': 0
        })
        
        for bar in hourly_bars:
            # Convert timestamp to ET
            timestamp_ms = bar.get('t', 0)
            if timestamp_ms == 0:
                continue
            
            # Handle pandas Timestamp or int
            if hasattr(timestamp_ms, 'timestamp'):
                # It's a pandas Timestamp - convert to seconds then to datetime
                bar_time_utc = datetime.fromtimestamp(timestamp_ms.timestamp(), tz=pytz.UTC)
            else:
                # It's milliseconds
                bar_time_utc = datetime.fromtimestamp(timestamp_ms / 1000, tz=pytz.UTC)
                
            bar_time_et = bar_time_utc.astimezone(ET)
            
            # Get bucket end time
            bucket_end = STRAT12HourComposer.get_12h_bucket_end(bar_time_et)
            bucket_key = int(bucket_end.timestamp() * 1000)  # Use ms timestamp as key
            
            # Get bucket
            bucket = buckets[bucket_key]
            
            # Update OHLCV
            if bucket['o'] is None:
                bucket['o'] = bar.get('o', 0)
            
            bucket['h'] = max(bucket['h'], bar.get('h', 0))
            bucket['l'] = min(bucket['l'], bar.get('l', 0))
            bucket['c'] = bar.get('c', 0)  # Last close wins
            bucket['v'] += bar.get('v', 0)
            bucket['t'] = bucket_key  # Bucket end timestamp
            bucket['bars_count'] += 1
        
        # Convert buckets to sorted list
        composed_bars = []
        for bucket_ts in sorted(buckets.keys()):
            bucket = buckets[bucket_ts]
            
            # Skip incomplete buckets
            if bucket['o'] is None or bucket['bars_count'] == 0:
                continue
            
            composed_bars.append({
                'o': bucket['o'],
                'h': bucket['h'],
                'l': bucket['l'],
                'c': bucket['c'],
                'v': bucket['v'],
                't': bucket['t']
            })
        
        logger.info(f"Composed {len(composed_bars)} 12-hour bars from {len(hourly_bars)} hourly bars")
        
        return composed_bars
    
    @staticmethod
    def get_recent_12h_windows(n_bars: int = 10) -> List[Dict[str, datetime]]:
        """
        Get recent 12-hour window boundaries in ET
        
        Args:
            n_bars: Number of 12-hour windows to return
            
        Returns:
            List of dicts with start_et and end_et datetime objects
        """
        now_et = datetime.now(ET)
        hour = now_et.hour
        
        # Find the most recent 12-hour boundary (08:00 or 20:00)
        if hour >= 20:
            # After 8 PM - last boundary was 20:00 today
            last_boundary = now_et.replace(hour=20, minute=0, second=0, microsecond=0)
        elif hour >= 8:
            # Between 8 AM and 8 PM - last boundary was 08:00 today
            last_boundary = now_et.replace(hour=8, minute=0, second=0, microsecond=0)
        else:
            # Before 8 AM - last boundary was 20:00 yesterday
            last_boundary = (now_et - timedelta(days=1)).replace(hour=20, minute=0, second=0, microsecond=0)
        
        # Build windows going backwards
        windows = []
        end_et = last_boundary
        
        for _ in range(n_bars):
            start_et = end_et - timedelta(hours=12)
            
            windows.insert(0, {
                'start_et': start_et,
                'end_et': end_et,
                'label': f"{start_et.strftime('%Y-%m-%d %H:%M')} → {end_et.strftime('%H:%M')} ET"
            })
            
            end_et = start_et
        
        return windows

