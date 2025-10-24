"""
60-Minute STRAT Pattern Detection for 3-2-2 Reversal
Scans at 8 AM, 9 AM, and 10 AM ET boundaries
"""
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import pytz

logger = logging.getLogger(__name__)

ET = pytz.timezone('America/New_York')

class STRAT60MinuteDetector:
    """
    60-Minute STRAT Pattern Detector for 3-2-2 Reversal
    
    Specific logic:
    1. 8:00 AM EST → Look for 3-bar (outside bar)
    2. 9:00 AM → 2-bar forms (any direction), mark high/low
    3. 10:00 AM → Look for 2-bar in opposite direction
       - If 9am was 2U → 10am should be 2D
       - If 9am was 2D → 10am should be 2U
    """
    
    @staticmethod
    def classify_bar(curr: Dict, prev: Dict) -> str:
        """
        Classify STRAT bar type based on CLOSE position
        
        Returns: "1", "2U", "2D", "3", or "0" (invalid)
        """
        curr_h, curr_l, curr_c = curr.get('h', 0), curr.get('l', 0), curr.get('c', 0)
        prev_h, prev_l, prev_c = prev.get('h', 0), prev.get('l', 0), prev.get('c', 0)
        
        if curr_h == 0 or curr_l == 0 or prev_h == 0 or prev_l == 0:
            return "0"
        
        broke_high = curr_h > prev_h
        broke_low = curr_l < prev_l
        
        # Outside bar
        if broke_high and broke_low:
            return "3"
        
        # Inside bar
        if curr_h <= prev_h and curr_l >= prev_l:
            return "1"
        
        # Directional based on close
        if curr_c > prev_c:
            return "2U"
        elif curr_c < prev_c:
            return "2D"
        else:
            return "1"
    
    @staticmethod
    def find_bar_at_hour(bars: List[Dict], target_hour: int) -> Optional[Dict]:
        """
        Find bar that closes at target hour in ET
        
        Args:
            bars: List of 60-minute bars
            target_hour: Hour in ET (0-23)
            
        Returns:
            Bar dict or None
        """
        for bar in bars:
            timestamp_ms = bar.get('t', 0)
            if timestamp_ms == 0:
                continue
            
            # Handle pandas Timestamp or int
            if hasattr(timestamp_ms, 'timestamp'):
                bar_time = datetime.fromtimestamp(timestamp_ms.timestamp(), tz=pytz.UTC).astimezone(ET)
            else:
                bar_time = datetime.fromtimestamp(timestamp_ms / 1000, tz=pytz.UTC).astimezone(ET)
            
            # Check if this bar closes at the target hour
            # 60-minute bars close on the hour
            if bar_time.hour == target_hour and bar_time.minute == 0:
                return bar
        
        return None
    
    @staticmethod
    def detect_322_reversal_8am_10am(bars_60m: List[Dict]) -> List[Dict]:
        """
        Detect 3-2-2 Reversal at 8 AM → 9 AM → 10 AM ET
        
        Requirements:
        1. 8:00 AM bar is a 3-bar (outside bar)
        2. 9:00 AM bar is a 2-bar (either 2D or 2U)
        3. 10:00 AM bar is a 2-bar in opposite direction
        
        Args:
            bars_60m: List of 60-minute bars
            
        Returns:
            List of signal dicts
        """
        signals = []
        
        # Look through bars to find 8am-9am-10am sequences
        for i in range(2, len(bars_60m)):
            bar_8am_candidate = bars_60m[i-2]
            bar_9am_candidate = bars_60m[i-1]
            bar_10am_candidate = bars_60m[i]
            
            # Verify timestamps
            time_8am = None
            time_9am = None
            time_10am = None
            
            for bar, var_name in [(bar_8am_candidate, 'time_8am'), 
                                   (bar_9am_candidate, 'time_9am'), 
                                   (bar_10am_candidate, 'time_10am')]:
                timestamp_ms = bar.get('t', 0)
                if timestamp_ms == 0:
                    break
                    
                if hasattr(timestamp_ms, 'timestamp'):
                    bar_time = datetime.fromtimestamp(timestamp_ms.timestamp(), tz=pytz.UTC).astimezone(ET)
                else:
                    bar_time = datetime.fromtimestamp(timestamp_ms / 1000, tz=pytz.UTC).astimezone(ET)
                
                if var_name == 'time_8am':
                    time_8am = bar_time
                elif var_name == 'time_9am':
                    time_9am = bar_time
                else:
                    time_10am = bar_time
            
            if not all([time_8am, time_9am, time_10am]):
                continue
            
            # Check if times are 8 AM, 9 AM, 10 AM
            if time_8am.hour != 8 or time_9am.hour != 9 or time_10am.hour != 10:
                continue
            
            # Need bar before 8am to classify it
            if i < 3:
                continue
            
            bar_7am = bars_60m[i-3]
            
            # Classify bars
            type_8am = STRAT60MinuteDetector.classify_bar(bar_8am_candidate, bar_7am)
            type_9am = STRAT60MinuteDetector.classify_bar(bar_9am_candidate, bar_8am_candidate)
            type_10am = STRAT60MinuteDetector.classify_bar(bar_10am_candidate, bar_9am_candidate)
            
            # Check requirements
            # 1. 8 AM must be a 3-bar (outside bar)
            if type_8am != "3":
                continue
            
            # 2. 9 AM must be a 2-bar (either direction)
            if type_9am not in ["2U", "2D"]:
                continue
            
            # 3. 10 AM must be opposite direction 2-bar
            is_reversal = (
                (type_9am == "2U" and type_10am == "2D") or
                (type_9am == "2D" and type_10am == "2U")
            )
            
            if not is_reversal:
                continue
            
            # Valid 3-2-2 Reversal!
            signals.append({
                'kind': '322-reversal-8am-10am',
                'completed_at': bar_10am_candidate['t'],
                'bar_8am': {
                    'type': type_8am,
                    'h': bar_8am_candidate['h'],
                    'l': bar_8am_candidate['l'],
                    'c': bar_8am_candidate['c'],
                    'time': time_8am
                },
                'bar_9am': {
                    'type': type_9am,
                    'h': bar_9am_candidate['h'],
                    'l': bar_9am_candidate['l'],
                    'c': bar_9am_candidate['c'],
                    'time': time_9am
                },
                'bar_10am': {
                    'type': type_10am,
                    'h': bar_10am_candidate['h'],
                    'l': bar_10am_candidate['l'],
                    'c': bar_10am_candidate['c'],
                    'time': time_10am
                },
                'entry': bar_10am_candidate['c'],
                'pattern_sequence': f"3→{type_9am}→{type_10am}",
                'bias': 'Bullish' if type_10am == '2U' else 'Bearish'
            })
            
            logger.info(f"✅ 3-2-2 Reversal: 8am(3) → 9am({type_9am}) → 10am({type_10am})")
        
        return signals

