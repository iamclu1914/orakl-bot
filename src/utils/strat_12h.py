"""
12-Hour STRAT Pattern Detection using Polygon.io REST API
Battle-tested implementation with proper ET alignment
"""
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import pytz
from dataclasses import dataclass

logger = logging.getLogger(__name__)

ET = pytz.timezone('America/New_York')

@dataclass
class AggBar:
    """Aggregated bar data"""
    o: float  # open
    h: float  # high
    l: float  # low
    c: float  # close
    v: int    # volume
    t: int    # timestamp (ms)
    
@dataclass
class TypedBar(AggBar):
    """Bar with STRAT type classification"""
    type: str  # "1", "2U", "2D", "3"


class STRAT12HourDetector:
    """
    12-Hour STRAT Pattern Detector
    
    Uses proper ET alignment (08:00-19:59 and 20:00-07:59)
    Implements battle-tested classification rules
    """
    
    @staticmethod
    def get_recent_12h_windows_et(n_bars: int = 10) -> List[Dict[str, str]]:
        """
        Get recent 12-hour ET windows
        
        Returns list of windows with:
        - start_utc: ISO timestamp
        - end_utc: ISO timestamp  
        - label_et: Human-readable ET label
        """
        # Get current time in ET
        now_et = datetime.now(ET)
        hour_et = now_et.hour
        
        # Determine last close boundary (08:00 or 20:00)
        last_close_et = now_et.replace(minute=0, second=0, microsecond=0)
        
        if hour_et >= 8 and hour_et < 20:
            # Currently in morning session, last close was 08:00 today
            close_hour = 8
        else:
            # Currently in evening session or early morning
            close_hour = 20
            
        last_close_et = last_close_et.replace(hour=close_hour)
        
        # If we haven't reached the close hour yet, go back one period
        if hour_et < close_hour or (hour_et == close_hour and now_et.minute == 0):
            last_close_et = last_close_et - timedelta(hours=12)
        
        # Build windows going backwards
        windows = []
        end_et = last_close_et
        
        for _ in range(n_bars):
            start_et = end_et - timedelta(hours=12)
            
            # Convert to UTC
            start_utc = start_et.astimezone(pytz.UTC)
            end_utc = end_et.astimezone(pytz.UTC)
            
            windows.insert(0, {
                'start_utc': start_utc.isoformat().replace('+00:00', 'Z'),
                'end_utc': end_utc.isoformat().replace('+00:00', 'Z'),
                'label_et': f"{start_et.strftime('%Y-%m-%d %H:%M')} → {end_et.strftime('%Y-%m-%d %H:%M')} ET"
            })
            
            end_et = start_et
            
        return windows
    
    @staticmethod
    def classify_bar(curr: Dict, prev: Dict) -> str:
        """
        Classify STRAT bar type based on CLOSE position
        
        Rules:
        - "3" (Outside): high > prevHigh AND low < prevLow  
        - "2U" (Up): close > prevClose (upward)
        - "2D" (Down): close < prevClose (downward)
        - "1" (Inside): close == prevClose OR inside previous range
        
        Args:
            curr: Current bar dict with h, l, c keys
            prev: Previous bar dict with h, l, c keys
            
        Returns:
            STRAT type: "1", "2U", "2D", or "3"
        """
        curr_h, curr_l, curr_c = curr['h'], curr['l'], curr['c']
        prev_h, prev_l, prev_c = prev['h'], prev['l'], prev['c']
        
        broke_high = curr_h > prev_h
        broke_low = curr_l < prev_l
        
        # Outside bar (broke both high and low)
        if broke_high and broke_low:
            return "3"
        
        # Inside bar (within previous range)
        if curr_h <= prev_h and curr_l >= prev_l:
            return "1"
        
        # Directional bars based on close
        if curr_c > prev_c:
            return "2U"  # Closed higher
        elif curr_c < prev_c:
            return "2D"  # Closed lower
        else:
            return "1"  # Closed same (inside)
    
    @staticmethod
    def attach_types(bars: List[Dict]) -> List[TypedBar]:
        """
        Attach STRAT types to bars
        
        Args:
            bars: List of bar dicts with o, h, l, c, v, t
            
        Returns:
            List of TypedBar objects
        """
        typed_bars = []
        
        for i in range(1, len(bars)):
            bar_type = STRAT12HourDetector.classify_bar(bars[i], bars[i-1])
            
            typed_bars.append(TypedBar(
                o=bars[i]['o'],
                h=bars[i]['h'],
                l=bars[i]['l'],
                c=bars[i]['c'],
                v=bars[i]['v'],
                t=bars[i]['t'],
                type=bar_type
            ))
            
        return typed_bars
    
    @staticmethod
    def detect_131_miyagi(typed: List[TypedBar]) -> List[Dict]:
        """
        Detect 1-3-1 Miyagi pattern
        
        Pattern: Inside bar → Outside bar → Inside bar
        Entry: Midpoint of 3rd bar (second inside bar)
        Direction: Determined by 4th bar (2U = PUTS bias, 2D = CALLS bias)
        
        Args:
            typed: List of TypedBar objects
            
        Returns:
            List of signal dicts
        """
        signals = []
        
        for i in range(2, len(typed)):
            bar_a = typed[i-2]  # First inside bar
            bar_b = typed[i-1]  # Outside bar
            bar_c = typed[i]    # Second inside bar
            
            if bar_a.type == "1" and bar_b.type == "3" and bar_c.type == "1":
                entry_midpoint = (bar_c.h + bar_c.l) / 2.0
                
                signal = {
                    'kind': '131-complete',
                    'completed_at': bar_c.t,
                    'entry': entry_midpoint,
                    'pattern_bars': {
                        'bar1': {'type': bar_a.type, 'h': bar_a.h, 'l': bar_a.l, 'c': bar_a.c},
                        'bar2': {'type': bar_b.type, 'h': bar_b.h, 'l': bar_b.l, 'c': bar_b.c},
                        'bar3': {'type': bar_c.type, 'h': bar_c.h, 'l': bar_c.l, 'c': bar_c.c}
                    }
                }
                
                signals.append(signal)
                
                # Check if 4th bar exists to determine direction
                if i + 1 < len(typed):
                    bar_d = typed[i+1]
                    
                    if bar_d.type == "2U":
                        signals.append({
                            'kind': '131-4th-2U-PUTS',
                            'at': bar_d.t,
                            'entry': entry_midpoint,
                            'direction': 'PUTS',
                            'setup_complete': True
                        })
                    elif bar_d.type == "2D":
                        signals.append({
                            'kind': '131-4th-2D-CALLS',
                            'at': bar_d.t,
                            'entry': entry_midpoint,
                            'direction': 'CALLS',
                            'setup_complete': True
                        })
                        
        return signals
    
    @staticmethod
    def detect_322_reversal(typed: List[TypedBar]) -> List[int]:
        """
        Detect 3-2-2 Reversal pattern
        
        Pattern: Outside bar → Directional → Opposite directional
        Example: 3 → 2U → 2D (bullish reversal)
                 3 → 2D → 2U (bearish reversal)
        
        Args:
            typed: List of TypedBar objects
            
        Returns:
            List of timestamps where pattern completes
        """
        hits = []
        
        for i in range(2, len(typed)):
            bar1 = typed[i-2]
            bar2 = typed[i-1]
            bar3 = typed[i]
            
            # Bullish reversal: 3 → 2U → 2D
            if bar1.type == "3" and bar2.type == "2U" and bar3.type == "2D":
                hits.append(bar3.t)
            
            # Bearish reversal: 3 → 2D → 2U  
            elif bar1.type == "3" and bar2.type == "2D" and bar3.type == "2U":
                hits.append(bar3.t)
                
        return hits
    
    @staticmethod
    def detect_22_reversal(typed: List[TypedBar]) -> List[int]:
        """
        Detect 2-2 Reversal pattern
        
        Pattern: Directional → Opposite directional
        Example: 2U → 2D or 2D → 2U
        
        Args:
            typed: List of TypedBar objects
            
        Returns:
            List of timestamps where pattern completes
        """
        hits = []
        
        for i in range(1, len(typed)):
            prev_bar = typed[i-1]
            curr_bar = typed[i]
            
            # 2U → 2D reversal
            if prev_bar.type == "2U" and curr_bar.type == "2D":
                hits.append(curr_bar.t)
            
            # 2D → 2U reversal
            elif prev_bar.type == "2D" and curr_bar.type == "2U":
                hits.append(curr_bar.t)
                
        return hits
    
    @staticmethod
    def detect_sequence(typed: List[TypedBar], sequence: List[str]) -> List[int]:
        """
        Generic sequence detector
        
        Args:
            typed: List of TypedBar objects
            sequence: List of STRAT types to match (e.g., ["3", "2U", "2D"])
            
        Returns:
            List of timestamps where sequence completes
        """
        hits = []
        seq_len = len(sequence)
        
        for i in range(seq_len - 1, len(typed)):
            match = True
            
            for k in range(seq_len):
                if typed[i - (seq_len - 1) + k].type != sequence[k]:
                    match = False
                    break
                    
            if match:
                hits.append(typed[i].t)
                
        return hits

